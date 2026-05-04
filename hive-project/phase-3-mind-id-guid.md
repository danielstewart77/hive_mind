# Phase 3 — Stable `mind_id` GUID

## Goal

Decouple a mind's identifier from its display name. Today, `mind_id` is the folder slug (`ada`, `bob`, etc.) and is hard-coded in the sessions DB, the lucent KG `agent_id` field, broker `from_mind` / `to_mind`, the `MIND_ID` container env var, and various skill arguments. Renaming a mind would silently break every cross-reference.

After this phase: every `runtime.yaml` has a top-level `mind_id: <uuid4>` field. That UUID is the canonical identifier in **persistence layers** (sessions DB, lucent KG, broker tables). The `name` field stays as a mutable display label and the **container env var, registry key, and HTTP routing key remain `name`** — operational paths still address minds by short name, and the GUID is only the key for persistent records.

This is a deliberately narrow scope. Treat the GUID as the **archival** identifier, not a replacement for `name` everywhere. A future phase could push the GUID further into routing if it ever matters.

## Current state

- Four minds: `ada`, `bob`, `bilby`, `nagatha`. (Plus `skippy` rows in sessions.db from a different deployment — leave those untouched.)
- `data/sessions.db` table `sessions`: column `mind_id TEXT DEFAULT 'ada'`. Distinct values today: `ada`, `nagatha`, `skippy`, `bob`.
- `data/sessions.db` table `group_sessions`: column `moderator_mind_id TEXT NOT NULL DEFAULT 'ada'`.
- `data/lucent.db`: tables `nodes`, `edges`, `memories`. `nodes.agent_id` distinct values: `ada`, `bob`, `nagatha`. The KG soul nodes are keyed by `agent_id`.
- `data/broker.db`: `messages.from_mind`, `messages.to_mind`, `minds.name`, `secret_scopes.mind_name`. All currently use the short name.

## Design

`mind_id` format: **uuid4 string** (lowercase, hyphenated, e.g. `1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed`). Generated once per mind, stored in `runtime.yaml`, and treated as the canonical archival key.

**Scope of the rename:**

| Layer | Before | After |
|---|---|---|
| `runtime.yaml` | (no mind_id field) | new top-level `mind_id: <uuid>` |
| `sessions.db sessions.mind_id` | short name | UUID |
| `sessions.db group_sessions.moderator_mind_id` | short name | UUID |
| `lucent.db nodes.agent_id` (and edges/memories with same column) | short name | UUID |
| `broker.db messages.from_mind, messages.to_mind` | short name | UUID |
| `broker.db minds.name` | short name | UUID **(renamed to `mind_id` column)** |
| `broker.db secret_scopes.mind_name` | short name | UUID **(renamed to `mind_id` column)** |
| Container `MIND_ID` env var | short name | **stays short name** (operational; not a persistent record) |
| Mind registry key | short name | **stays short name** (in-memory routing only) |
| Folder name `minds/<name>` | short name | **stays short name** |
| Service name in compose | short name | **stays short name** |

In other words: if it's stored on disk in a long-lived DB, switch to UUID. If it's an operational handle (env, registry, container name, HTTP host), leave it as the short name.

Code that needs to translate goes through the registry: `MindRegistry.get(name).mind_id` returns the UUID; `MindRegistry.lookup_by_id(uuid).name` returns the short name. Both lookups should be cheap (in-memory dict).

## File-by-file changes

### 1. Add `mind_id` to each `runtime.yaml`

Generate four fresh UUIDs and write them. Use `python -c "import uuid; print(uuid.uuid4())"` four times and capture each output. The resulting file:

```yaml
# Ada — self-contained runtime configuration
name: ada
mind_id: <generated-uuid-1>
gateway_url: http://ada:8420
...
```

Add `mind_id` as the second field after `name` in each `runtime.yaml` (ada, bob, bilby, nagatha). **Record the four UUIDs at the top of the migration script** (Step 4 below) so it knows which UUID maps to which name.

### 2. Update `core/mind_registry.py`

- Add `mind_id: str` field to `MindInfo` dataclass.
- Make `mind_id` a required field in `_REQUIRED_FIELDS` (extend the tuple).
- In `parse_mind_file`, read `data["mind_id"]` and pass into `MindInfo(...)`.
- Add a method `lookup_by_id(self, mind_id: str) -> MindInfo | None` that scans `self._minds.values()` for a matching `mind_id`.
- Keep `get(name)` keyed by short name (no behaviour change).

### 3. Update sessions DB schema

`core/sessions.py` owns the schema. Find the `CREATE TABLE` statements (around line 200 for `sessions`, line 215 for `group_sessions`). Don't change the column names — the column is still called `mind_id`; only the **values** stored shift from short names to UUIDs.

Add a migration function `_migrate_mind_id_to_uuid(con)` that runs once at startup (alongside or just after the existing migration block at `core/sessions.py:255–258`):

```python
def _migrate_mind_id_to_uuid(con: sqlite3.Connection, name_to_uuid: dict[str, str]) -> None:
    """One-time conversion of sessions.mind_id from short name to UUID.

    Idempotent: if the value is already a UUID, skip. If it's a short name
    that's in name_to_uuid, rewrite. If it's a short name we don't know
    about (e.g. 'skippy' from a different deployment), leave it.
    """
    import re
    UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    for table, col in [("sessions", "mind_id"), ("group_sessions", "moderator_mind_id")]:
        rows = con.execute(f"SELECT DISTINCT {col} FROM {table}").fetchall()
        for (val,) in rows:
            if val is None or UUID_RE.match(val):
                continue
            if val in name_to_uuid:
                con.execute(
                    f"UPDATE {table} SET {col} = ? WHERE {col} = ?",
                    (name_to_uuid[val], val),
                )
```

The `name_to_uuid` dict is built from the registry at startup: iterate `registry.list_all()` and build `{info.name: info.mind_id}`.

Call this migration in the `SessionManager.start` / equivalent init path. **The migration runs at every startup** — but the UUID check makes it a no-op after the first run.

### 4. Migration script for lucent KG and broker

Create `scripts/migrate_mind_ids.py`. This is a one-shot script the user runs manually after deploying the new code. It reads each `runtime.yaml`, builds a `{short_name: uuid}` map, and updates the lucent and broker DBs.

```python
#!/usr/bin/env python3
"""One-time migration: rewrite short-name mind identifiers to UUIDs in lucent and broker DBs.

Run AFTER deploying Phase 3 code (which adds mind_id to runtime.yaml and registers the
new schema). Idempotent.
"""

import re
import sqlite3
import sys
import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MINDS_DIR = REPO / "minds"
LUCENT_DB = REPO / "data" / "lucent.db"
BROKER_DB = REPO / "data" / "broker.db"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def load_name_to_uuid() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for sub in MINDS_DIR.iterdir():
        if not sub.is_dir():
            continue
        rt = sub / "runtime.yaml"
        if not rt.exists():
            continue
        data = yaml.safe_load(rt.read_text())
        name = data.get("name")
        mid = data.get("mind_id")
        if not name or not mid:
            print(f"SKIP: {sub.name} missing name or mind_id in runtime.yaml")
            continue
        mapping[name] = mid
    return mapping


def migrate_lucent(name_to_uuid: dict[str, str]) -> None:
    if not LUCENT_DB.exists():
        print(f"lucent DB not found at {LUCENT_DB}, skipping")
        return
    con = sqlite3.connect(LUCENT_DB)
    try:
        for table in ("nodes", "edges", "memories"):
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({table})")]
            if "agent_id" not in cols:
                continue
            for short, uid in name_to_uuid.items():
                cur = con.execute(
                    f"UPDATE {table} SET agent_id = ? WHERE agent_id = ?",
                    (uid, short),
                )
                if cur.rowcount:
                    print(f"lucent: {table}.agent_id  {short!r} -> {uid}  ({cur.rowcount} rows)")
        con.commit()
    finally:
        con.close()


def migrate_broker(name_to_uuid: dict[str, str]) -> None:
    if not BROKER_DB.exists():
        print(f"broker DB not found at {BROKER_DB}, skipping")
        return
    con = sqlite3.connect(BROKER_DB)
    try:
        # messages.from_mind / messages.to_mind
        for col in ("from_mind", "to_mind"):
            for short, uid in name_to_uuid.items():
                cur = con.execute(
                    f"UPDATE messages SET {col} = ? WHERE {col} = ?",
                    (uid, short),
                )
                if cur.rowcount:
                    print(f"broker: messages.{col}  {short!r} -> {uid}  ({cur.rowcount} rows)")

        # minds.name -> rename column to mind_id and store UUID values
        cols = [c[1] for c in con.execute("PRAGMA table_info(minds)")]
        if "name" in cols and "mind_id" not in cols:
            con.execute("ALTER TABLE minds RENAME COLUMN name TO mind_id")
            print("broker: minds.name -> minds.mind_id (column renamed)")
            cols = [c[1] for c in con.execute("PRAGMA table_info(minds)")]
        if "mind_id" in cols:
            for short, uid in name_to_uuid.items():
                cur = con.execute(
                    "UPDATE minds SET mind_id = ? WHERE mind_id = ?",
                    (uid, short),
                )
                if cur.rowcount:
                    print(f"broker: minds.mind_id  {short!r} -> {uid}  ({cur.rowcount} rows)")

        # secret_scopes.mind_name -> rename to mind_id
        cols = [c[1] for c in con.execute("PRAGMA table_info(secret_scopes)")]
        if "mind_name" in cols and "mind_id" not in cols:
            con.execute("ALTER TABLE secret_scopes RENAME COLUMN mind_name TO mind_id")
            print("broker: secret_scopes.mind_name -> secret_scopes.mind_id (column renamed)")
            cols = [c[1] for c in con.execute("PRAGMA table_info(secret_scopes)")]
        if "mind_id" in cols:
            for short, uid in name_to_uuid.items():
                cur = con.execute(
                    "UPDATE secret_scopes SET mind_id = ? WHERE mind_id = ?",
                    (uid, short),
                )
                if cur.rowcount:
                    print(f"broker: secret_scopes.mind_id  {short!r} -> {uid}  ({cur.rowcount} rows)")
        con.commit()
    finally:
        con.close()


def main() -> int:
    mapping = load_name_to_uuid()
    if not mapping:
        print("no mind_id mappings found — runtime.yaml files missing mind_id?")
        return 1
    print("name -> uuid mapping:")
    for n, u in mapping.items():
        print(f"  {n} -> {u}")
    migrate_lucent(mapping)
    migrate_broker(mapping)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 5. Update broker code that reads/writes the renamed columns

After the script renames `minds.name -> minds.mind_id` and `secret_scopes.mind_name -> secret_scopes.mind_id`, application code that references those columns must be updated. Search:

```bash
grep -rn "secret_scopes\|broker.*minds.*\(name\|mind_name\)" core/ server.py tools/ 2>&1
```

Update every SQL statement, ORM-style accessor, and any HTTP handler that exposes these columns to use the new column name. Notably check:

- `core/broker.py` (or wherever broker DB code lives)
- `server.py` `/broker/minds`, `/broker/minds/{name}` endpoints — keep the URL param as `{name}` (mutable display label is the natural URL key) but translate to `mind_id` for DB lookups via the registry.

### 6. Code that references mind identity in lucent

`core/sessions.py:104` calls `graph_query(entity_name=mind_name, agent_id=mind_id, depth=1)`. After migration, `agent_id` in lucent is a UUID. The call site passes `mind_id` directly — but inside this codebase `mind_id` is still the **short name** at the call site. Two options; pick one and apply consistently:

**Option A (preferred — minimal churn):** Translate at the boundary. In `_fetch_soul_sync`, look up the registry by short name and pass the UUID:

```python
def _fetch_soul_sync(mind_id: str = "ada") -> str | None:
    ...
    # mind_id parameter is the short name; lucent stores UUIDs
    from core.mind_registry import MindRegistry  # or wherever the singleton is
    registry = ...  # access the gateway's registry
    info = registry.get(mind_id)
    if not info:
        return None
    agent_id_uuid = info.mind_id
    result = json.loads(graph_query(entity_name=mind_name, agent_id=agent_id_uuid, depth=1))
    ...
```

The function signature stays `mind_id: str` (still the short name); only the value passed into `graph_query` changes.

**Option B:** Rename the parameter to `mind_name` throughout to make the distinction obvious. More churn, clearer naming. Defer unless A causes confusion in review.

Apply the same translation in `_fetch_memories_sync` (line 54 → `agent_id=mind_id`).

## Acceptance criteria

- Each `minds/<name>/runtime.yaml` has a top-level `mind_id: <uuid4>` field where the value matches the format `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`.
- `python -c "from core.mind_registry import MindRegistry; ..."` (run from repo root) loads all four minds and the printed `mind_id` matches the value in each `runtime.yaml`.
- `scripts/migrate_mind_ids.py` runs to completion. Re-running it is a no-op (zero rows updated on second run).
- After running the migration:
  - `sessions.mind_id` for all rows is either a UUID known to the registry, or an unknown short name (e.g. `skippy`) that was left alone.
  - `lucent.db nodes.agent_id` distinct values include only UUIDs (for ada/bob/bilby/nagatha) or unrelated identifiers from other systems.
  - `broker.db` has columns `minds.mind_id` and `secret_scopes.mind_id` (no longer `name` / `mind_name`).
- Soul fetch via `_fetch_soul_sync("ada")` still returns Ada's soul (translated through the registry).
- The gateway and the four mind containers boot without errors after restart. (Containers will still be running `mind_server.py` — that's Phase 4.)
- Renaming Ada's `name:` field in runtime.yaml from `ada` to `ada_v2` does NOT break sessions DB / KG / broker references — they're keyed by UUID. Only the in-process registry would no longer find a mind named `ada`. (This is the test of decoupling. Don't actually leave Ada renamed — verify, then revert.)

## Out of scope

- Removing `mind_server.py` (Phase 4)
- Renaming `MIND_ID` env var (stays as short name; operational only)
- Folder rename support (e.g. `minds/ada` to `minds/ada_v2`) — that's a follow-up if/when we want it
