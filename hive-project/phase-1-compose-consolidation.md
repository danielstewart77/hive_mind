# Phase 1 — Compose consolidation

## Goal

Move each mind's docker-compose service definition out of the central `# BEGIN GENERATED MINDS` block in `docker-compose.yml` into a per-mind fragment at `minds/<name>/container/compose.yaml`. Replace the generated block with an explicit `include:` list. Update the `hivemind:generate-compose` skill so it generates a per-mind fragment file (not a block in the top-level compose).

`MIND.md` deletion is **not** in this phase — it is Phase 2. This phase preserves `MIND.md` files unchanged.

## Current state (point in time)

- `docker-compose.yml` lines `358–454` contain the `# BEGIN GENERATED MINDS` / `# END GENERATED MINDS` block with four service definitions (`ada`, `bob`, `bilby`, `nagatha`).
- All four use `command: ["/opt/venv/bin/python3", "mind_server.py"]` — keep that command verbatim in the per-mind fragments. Phase 4 changes the command later.
- The `# BEGIN GENERATED VOLUMES` / `# END GENERATED VOLUMES` block (lines `465–466`) is empty and stays.
- `hivemind:generate-compose` skill source: `/home/daniel/Storage/Dev/hivemind-claude-plugin/skills/generate-compose/SKILL.md`. Today it scans `MIND.md` `container:` blocks and rewrites the block in `docker-compose.yml`.

## File-by-file changes

### 1. Create per-mind fragments

For each of `ada`, `bob`, `bilby`, `nagatha`, create `minds/<name>/container/compose.yaml`. The fragment is a **complete Compose file** with one service under `services:`. Copy the existing block from `docker-compose.yml` lines `358–454` verbatim — the only restructuring is wrapping it in `services:`.

Example — `minds/ada/container/compose.yaml`:

```yaml
services:
  ada:
    build: .
    container_name: hive-mind-ada
    working_dir: /usr/src/app
    environment:
      - MIND_ID=ada
      - CLAUDE_CONFIG_DIR=/usr/src/app/minds/ada/.claude
      - PYTHON_KEYRING_BACKEND=core.keyring_backend.HiveMindKeyring
      - PYTHONNOUSERSITE=1
      - PYTHONPATH=/usr/src/app/vendor
      - KEY_RING=/usr/src/app/data/keyring
    volumes:
      - ${HOST_DEV_DIR}:/mnt/dev:rw
      - ${HOST_PROJECT_DIR:-.}:/usr/src/app:rw
      - ${HOST_CLAUDE_DIR:-~/.claude}:/mnt/host-claude:ro
    restart: unless-stopped
    depends_on:
      - server
    networks:
      - hivemind
    tmpfs:
      - /tmp
    command: ["/opt/venv/bin/python3", "mind_server.py"]
```

Repeat for `bob`, `bilby`, `nagatha` using the existing blocks at the cited line ranges.

### 2. Replace the generated block in `docker-compose.yml`

Delete lines `358–454` (everything from `# BEGIN GENERATED MINDS` through `# END GENERATED MINDS` inclusive). In their place, add at the **top of the file** (after `version:` if present, before `services:`), or wherever Compose `include:` is allowed at the document root, an explicit include list:

```yaml
include:
  - path: minds/ada/container/compose.yaml
  - path: minds/bob/container/compose.yaml
  - path: minds/bilby/container/compose.yaml
  - path: minds/nagatha/container/compose.yaml
```

No globs — explicit list, one mind per line. The `# BEGIN GENERATED VOLUMES` / `# END GENERATED VOLUMES` block stays exactly where it is (unchanged).

### 3. Update `hivemind:generate-compose` skill

File: `/home/daniel/Storage/Dev/hivemind-claude-plugin/skills/generate-compose/SKILL.md`.

Rewrite so the skill:
- Asks the user the questions needed to construct one mind's container fragment (image, env, volumes, networks, scope/capabilities, command).
- Writes `minds/<name>/container/compose.yaml` containing the full `services:` block for that one mind.
- **Does NOT touch** `docker-compose.yml` and **does NOT manage** the `include:` list.
- Final output instructs the user to add the `- path: minds/<name>/container/compose.yaml` line to the top-level `include:` themselves.

Keep the `--standalone <mind-name>` mode if it exists — that path can stay unchanged for now (out of scope for this phase if it works on a different surface).

Update the skill `description:` frontmatter to reflect the new behaviour (no longer "generate ... between markers"; now "generate a per-mind compose fragment").

### 4. Update plugin source mirror

`/home/daniel/Storage/Dev/hivemind-claude-plugin/` is the plugin source. After editing the skill there, the user reinstalls the plugin separately — no need to reach into installed copies (`~/.claude/...`).

## Acceptance criteria

- `docker compose config` (run from `/home/daniel/Storage/Dev/hive_mind/`) parses successfully and lists exactly the same services as before this phase (gateway + voice + telegram bots + discord + scheduler + planka + the four minds + nervous system + tools, etc.).
- `docker compose up -d` brings up the same set of containers as before.
- `grep -n "BEGIN GENERATED MINDS\|END GENERATED MINDS" docker-compose.yml` returns zero hits.
- `ls minds/{ada,bob,bilby,nagatha}/container/compose.yaml` shows all four fragment files exist.
- The `include:` block in `docker-compose.yml` lists exactly four entries, one per mind.
- `MIND.md` files still exist (untouched in this phase).
- `mind_server.py` still exists (untouched in this phase).
- The `hivemind:generate-compose` skill body documents the new per-fragment behaviour and no longer mentions the `# BEGIN GENERATED MINDS` markers.

## Out of scope for this phase

- Deleting `MIND.md` (Phase 2)
- Renaming `runtime.yaml` to `mind.yaml` (the spec uses `mind.yaml`; the codebase uses `runtime.yaml`; do not rename here)
- Changing the `command:` away from `mind_server.py` (Phase 4)
- Adding `mind_id` GUID (Phase 3)

## Verification commands the agent should run before declaring done

```bash
cd /home/daniel/Storage/Dev/hive_mind
docker compose config > /tmp/compose-after.txt 2>&1 && echo "compose parse OK" || cat /tmp/compose-after.txt
grep -n "BEGIN GENERATED MINDS\|END GENERATED MINDS" docker-compose.yml || echo "markers gone"
ls minds/ada/container/compose.yaml minds/bob/container/compose.yaml minds/bilby/container/compose.yaml minds/nagatha/container/compose.yaml
```

A `docker compose up -d` test is **not required** during this phase — the agent should leave running containers untouched. The user will restart the stack explicitly if/when they want to.
