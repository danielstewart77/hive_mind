# Phase 4 — Eliminate `mind_server.py`; per-mind `implementation.py` becomes the in-container service

## Goal

Delete `mind_server.py` (424 lines today). Each `minds/<name>/implementation.py` absorbs the responsibilities `mind_server.py` provides today — FastAPI app, routes, in-memory session table, secret loading, identity prompt assembly — so each mind container runs exactly one Python process: the mind's own implementation file.

In parallel, strip per-mind code from `core/sessions.py` and `server.py`. The gateway loses `_load_implementation`, `_build_base_prompt`, `_fetch_soul_sync`, `parse_mind_file` calls in the spawn path, and the `importlib.import_module(f"minds.{mind_id}.implementation")` mechanism. The gateway becomes a pure router: it takes a request for `mind_id=X`, looks up `X`'s `gateway_url` in the registry, and forwards an HTTP request.

This phase **depends on Phase 3** — the gateway routes by short name (the registry key); persistence still uses the UUID. The new `implementation.py` reads its own `runtime.yaml` to know its own `name` and `mind_id`.

## Current state

- `mind_server.py:424 lines`. Imports `minds.{MIND_ID}.implementation`, runs FastAPI, manages an in-memory `_sessions` dict, wires `_build_base_prompt` from `core.sessions`, calls `implementation.spawn(...)` with a giant kwargs blob.
- `minds/ada/implementation.py:153 lines`, `bob/170`, `bilby/187`, `nagatha/204`. All export `spawn(session_id, ..., build_base_prompt=..., registry=..., config_obj=..., ...) -> Process`. They're not FastAPI apps — they're spawn-helper modules called by `mind_server.py`.
- `core/sessions.py`:
  - `_fetch_soul_sync` (lines 92–115) — calls `tools/stateful/knowledge_graph.py:graph_query`.
  - `_build_base_prompt` (lines 119–160) — assembles soul + prompt files.
  - `_load_implementation` (lines 168–183) — `importlib.import_module(f"minds.{mind_id}.implementation")` with Ada fallback.
  - The `_spawn` path uses `_load_implementation(mind_id).spawn(...)` to produce the subprocess.
- `server.py` — exposes 38 HTTP endpoints. Most are surface routes that touch SessionManager.

## Design

### New responsibility split

**Gateway (`server.py` + `core/sessions.py`):**
- HTTP API surface (the 38 endpoints stay)
- Sessions DB (persistence; row-level lifecycle)
- Idle reaper, autopilot guard
- Multi-client multiplexing (one session, many surfaces)
- Group-session orchestration
- **Routing**: when a session is for `mind_id=X`, forward to `http://<X.gateway_url>/...`
- Mind registry (read-only metadata)

What the gateway no longer does:
- Spawn subprocesses for harnesses
- Build identity prompts
- Fetch souls from the KG
- Load per-mind Python modules

**Per-mind `implementation.py`:**
- FastAPI app with these in-container routes:
  - `GET /health` → `{"name": ..., "mind_id": ..., "ok": true, "sessions": <count>}`
  - `POST /sessions` body `{session_id, model, surface_prompt, allowed_directories, autopilot, resume_sid, prompt_files}` → spawns the harness subprocess for this session, stores it in an in-memory dict, returns `{session_id, mind_id}`
  - `POST /sessions/{sid}/message` SSE/streaming body `{content}` → writes content to the subprocess stdin, streams stream-json events back
  - `POST /sessions/{sid}/interrupt` → sends interrupt signal without killing
  - `DELETE /sessions/{sid}` → kills the subprocess, removes from dict
- In-memory session table (`session_id -> handle`)
- Soul fetch, identity prompt assembly (everything the old `_build_base_prompt` did)
- Mind config loading (its own `runtime.yaml`)
- Secret fetch from gateway (`/secrets/scopes/{name}` then `/secrets/{key}` — same protocol as today)
- Read-only sync of mind config dir, host credentials (the existing `mind_server._setup_config_dir` work)
- `uvicorn.run(...)` at the bottom

Estimated 250–350 lines per mind file. Self-contained: a cloner reads one file and understands the entire mind container.

### Routing change in the gateway

`core/sessions.py:create_session(...)` and `_spawn(...)` today call `_load_implementation(mind_id).spawn(...)`. After this phase, the spawn path becomes an HTTP POST:

```python
# core/sessions.py — new _spawn (sketch)
async def _spawn(self, session_id, model, *, mind_id, surface_prompt, allowed_directories, autopilot, resume_sid, ...):
    info = self.mind_registry.get(mind_id)
    if info is None:
        raise ValueError(f"unknown mind_id {mind_id!r}")
    body = {
        "session_id": session_id,
        "model": model,
        "surface_prompt": surface_prompt,
        "allowed_directories": allowed_directories or [],
        "autopilot": autopilot,
        "resume_sid": resume_sid,
        "prompt_files": info.prompt_files,
    }
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{info.gateway_url}/sessions", json=body) as resp:
            resp.raise_for_status()
            data = await resp.json()
    # Track that this session belongs to this mind container — the gateway
    # holds no subprocess handle anymore. Subsequent message/kill calls also
    # forward to info.gateway_url.
    self._mind_ids[session_id] = mind_id
```

Then `send_message` and `kill_session` similarly forward to `f"{info.gateway_url}/sessions/{session_id}/message"` and `DELETE /sessions/{session_id}`.

For SSE/stream-json forwarding, use an `aiohttp` streaming response and pipe events to the gateway's existing SSE response. (See `server.py`'s existing SSE handler for the response shape; the gateway's job is now "proxy with the session DB on the side.")

## File-by-file changes

### 1. New skeleton for `minds/<name>/implementation.py`

Below is the **template**. Apply per-mind specifics for the harness command. Use Ada as the worked example; follow the same structure for Bob/Bilby/Nagatha with their existing `spawn`/`kill`/`send` logic moved into the file body.

```python
"""Ada — in-container FastAPI service.

Runs as the sole process inside the ada container.
Reads minds/ada/runtime.yaml. Owns the harness subprocess(es).
"""

import asyncio
import logging
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ada")

HERE = Path(__file__).parent
RUNTIME = yaml.safe_load((HERE / "runtime.yaml").read_text())
NAME = RUNTIME["name"]
MIND_ID = RUNTIME["mind_id"]  # UUID
DEFAULT_MODEL = RUNTIME["default_model"]
PROVIDER = RUNTIME["provider"]
PROMPT_FILES = RUNTIME.get("prompt_files", [])
RUNTIME_ENV = RUNTIME.get("env", {}) or {}

PROJECT_DIR = Path("/usr/src/app")
NS_URL = os.environ.get("HIVE_MIND_SERVER_URL", "http://server:8420")
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "/home/hivemind/.claude"))
HOST_CREDS = Path("/mnt/host-claude/.credentials.json")
SKIP_HOST_CREDENTIALS = os.environ.get("SKIP_HOST_CREDENTIALS", "").lower() in {"1","true","yes","on"}

app = FastAPI(title=f"Mind: {NAME}")

# session_id -> dict({"proc": Process, "model": str, ...})
SESSIONS: dict[str, dict] = {}


# --- Setup -----------------------------------------------------------------

def _sync_mind_config_assets():
    """Copy safe mind-local Claude config assets into CONFIG_DIR.
    Verbatim port of mind_server._sync_mind_config_assets — see git history.
    """
    src = PROJECT_DIR / "minds" / NAME / ".claude"
    if not src.exists():
        return
    try:
        if CONFIG_DIR.resolve() == src.resolve():
            log.info("Skipping config sync: CLAUDE_CONFIG_DIR is the source")
            return
    except (OSError, RuntimeError):
        pass
    allowed = {".claude.json", "agents", "hooks", "projects", "settings.json", "skills"}
    for child in src.iterdir():
        if child.name not in allowed:
            continue
        target = CONFIG_DIR / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True, ignore_dangling_symlinks=True)
        else:
            shutil.copy2(child, target)


def _setup_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = str(CONFIG_DIR)
    _sync_mind_config_assets()
    target_creds = CONFIG_DIR / ".credentials.json"
    if SKIP_HOST_CREDENTIALS:
        log.info("Skipping host credential sync")
    elif HOST_CREDS.exists():
        if not target_creds.exists() or HOST_CREDS.stat().st_mtime > target_creds.stat().st_mtime:
            shutil.copy2(str(HOST_CREDS), str(target_creds))
            target_creds.chmod(0o600)


_setup_config_dir()


async def _fetch_secrets_on_startup():
    """Same protocol as mind_server today — see git history for the verbatim copy."""
    _ENV_MAP = {"gh_oauth_token": "GH_TOKEN", "mcp_auth_token": "MCP_AUTH_TOKEN"}
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"{NS_URL}/secrets/scopes/{NAME}",
                                timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return
                scopes = await resp.json()
                keys = scopes.get("secret_keys", [])
            for key in keys:
                async with http.get(f"{NS_URL}/secrets/{key}",
                                    timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        v = (await resp.json()).get("value")
                        if v:
                            env_name = _ENV_MAP.get(key, key.upper())
                            os.environ[env_name] = v
    except Exception:
        log.debug("Could not fetch secrets")


# --- Identity prompt (moved from gateway) ----------------------------------

def _fetch_soul() -> str | None:
    """Call lucent KG via NS_URL to fetch this mind's soul."""
    try:
        import requests
        r = requests.post(
            f"{NS_URL}/kg/query",  # OR direct call to lucent — match the existing approach
            json={"entity_name": NAME.capitalize(), "mind_id": MIND_ID, "depth": 1},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        nodes = data.get("nodes", [])
        if not nodes:
            return None
        return nodes[0].get("properties", {}).get("soul_values") or None
    except Exception:
        log.exception("soul fetch failed")
        return None


def _load_prompt_files() -> str:
    parts = []
    for rel in PROMPT_FILES:
        p = HERE / rel
        if p.exists():
            parts.append(p.read_text())
    return "\n\n".join(parts)


def build_identity_prompt(surface_prompt: str | None,
                          allowed_directories: list[str] | None) -> str:
    soul = _fetch_soul()
    base_parts = []
    if soul:
        base_parts.append(soul)
        base_parts.append(
            f"Your soul is loaded above from the knowledge graph. When something meaningfully "
            f"shapes your identity, update it via graph_upsert on the {NAME.capitalize()} node "
            f"(soul_values field). Keep it extremely short — it is a soul, not a manifesto."
        )
    base_parts.append(_load_prompt_files())
    if allowed_directories:
        base_parts.append("Allowed directories: " + ", ".join(allowed_directories))
    base = "\n\n".join(p for p in base_parts if p)
    return f"{base}\n\n{surface_prompt}" if surface_prompt else base


# --- Harness spawn/send/kill (mind-specific; below is Ada CLI) -------------

async def _spawn(session_id: str, *, model: str, autopilot: bool,
                 resume_sid: str | None, surface_prompt: str | None,
                 allowed_directories: list[str] | None) -> asyncio.subprocess.Process:
    full_prompt = build_identity_prompt(surface_prompt, allowed_directories)
    cmd = [
        "claude", "-p",
        "--verbose",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--permission-mode", "bypassPermissions",
        "--dangerously-skip-permissions",
        "--model", model,
        "--mcp-config", os.environ.get("MCP_CONFIG", ""),
        "--append-system-prompt", full_prompt,
    ]
    for d in allowed_directories or []:
        cmd.extend(["--allowedDirectory", d])
    if resume_sid:
        cmd.extend(["--resume", resume_sid])
    env = os.environ.copy()
    env.update({k: str(v) for k, v in RUNTIME_ENV.items()})
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,
        env=env,
        cwd=str(PROJECT_DIR),
    )
    log.info("Spawned session=%s pid=%d model=%s", session_id, proc.pid, model)
    return proc


async def _kill(proc: asyncio.subprocess.Process):
    if proc.returncode is None:
        try:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass


# --- Routes ----------------------------------------------------------------

@app.on_event("startup")
async def _startup():
    await _fetch_secrets_on_startup()


@app.get("/health")
async def health():
    return {"name": NAME, "mind_id": MIND_ID, "ok": True, "sessions": len(SESSIONS)}


@app.post("/sessions")
async def create_session(req: Request):
    body = await req.json()
    sid = body.get("session_id") or str(uuid4())
    model = body.get("model") or DEFAULT_MODEL
    proc = await _spawn(
        sid,
        model=model,
        autopilot=bool(body.get("autopilot", False)),
        resume_sid=body.get("resume_sid"),
        surface_prompt=body.get("surface_prompt"),
        allowed_directories=body.get("allowed_directories"),
    )
    SESSIONS[sid] = {"proc": proc, "model": model}
    return {"session_id": sid, "mind_id": MIND_ID, "name": NAME}


@app.post("/sessions/{sid}/message")
async def send_message(sid: str, req: Request):
    sess = SESSIONS.get(sid)
    if not sess:
        return JSONResponse({"error": "unknown session"}, status_code=404)
    body = await req.json()
    content = body.get("content", "")
    proc = sess["proc"]
    # Write a stream-json line. Use whatever wire format the existing
    # implementation used (see old mind_server send path for reference).
    proc.stdin.write((content + "\n").encode())
    await proc.stdin.drain()

    async def event_stream():
        async for line in proc.stdout:
            if line:
                yield f"data: {line.decode().rstrip()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/sessions/{sid}")
async def kill_session(sid: str):
    sess = SESSIONS.pop(sid, None)
    if sess:
        await _kill(sess["proc"])
    return {"ok": True}


@app.post("/sessions/{sid}/interrupt")
async def interrupt(sid: str):
    sess = SESSIONS.get(sid)
    if sess:
        try:
            sess["proc"].send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8420)
```

The file is long — that's the point. It's complete and self-contained.

### Per-mind variants

- **Bob**: same shape, but `spawn` uses Ollama env (`ANTHROPIC_BASE_URL`, etc. from `runtime.yaml`'s `env` block — already loaded into `RUNTIME_ENV`).
- **Bilby**: SDK-based — instead of an `asyncio.subprocess`, the session table holds an SDK handle. Port the existing send/kill semantics from `minds/bilby/implementation.py` today.
- **Nagatha**: codex CLI, **one subprocess per turn**. The `SESSIONS[sid]` value is metadata only; `send_message` spawns a new codex subprocess each call with `--resume <claude_sid>`.

For each mind, port the existing `spawn`/`kill`/`send` logic from today's implementation.py into the new file. No behaviour change — only relocation.

### 2. Rip code out of `core/sessions.py`

Delete:
- `_fetch_soul_sync` (lines 92–115)
- `_build_base_prompt` (lines 119–160)
- `_load_implementation` and `_implementation_cache` (lines 165–183)
- `import importlib` if no other call site uses it (search first)
- `import types` if unused after the cache is gone

Rewrite `_spawn` and `_send` to forward over HTTP via the registry (sketch above).

The session DB schema stays. The `_mind_ids: dict[str, str]` lookup table stays — it's how the gateway knows which mind container to forward to for a given session.

### 3. Rip code out of `server.py`

Search for any direct call to `_build_base_prompt`, `_fetch_soul_sync`, `_load_implementation`, or `parse_mind_file` in `server.py`. Each of these is now a per-mind concern. Delete the call site or replace it with an HTTP forward through `mind_registry.get(mind_id).gateway_url`.

After the cleanup:

```bash
grep -rn "importlib\|parse_mind_file\|_build_base_prompt\|_fetch_soul_sync\|_load_implementation" core/ server.py 2>&1
# Expected: empty
```

```bash
grep -rn "minds/[a-z]" core/ server.py 2>&1
# Expected: empty (nothing in core/ or server.py addresses per-mind paths)
```

### 4. Update `docker-compose.yml` per-mind fragments

In each `minds/<name>/container/compose.yaml` (created in Phase 1), change the command:

```yaml
    command: ["/opt/venv/bin/python3", "-m", "minds.<name>.implementation"]
```

(Replace `<name>` with `ada`, `bob`, `bilby`, `nagatha` per file.)

Drop the `MIND_ID=<name>` env var — the implementation reads its own `runtime.yaml` to know its name. (Keep it if anything still expects it; grep first: `grep -rn "MIND_ID" minds/ core/ server.py`.)

### 5. Delete `mind_server.py`

```bash
rm mind_server.py
```

Verify nothing imports it:

```bash
grep -rn "mind_server" core/ server.py minds/ tests/ 2>&1
# Expected: empty (or only test files that need to be deleted/updated)
```

### 6. Test the change manually before committing

Restart one mind container (Bob is lowest blast radius — he's offline-friendly Ollama):

```bash
docker compose up -d --force-recreate bob
docker logs hive-mind-bob --tail 50
curl http://localhost:<bob_port>/health 2>&1  # via gateway proxy if no exposed port
```

Then end-to-end: send a message via the gateway and confirm Bob's logs show the spawn happening inside the bob container, not in the gateway. Repeat for Ada, Bilby, Nagatha.

## Acceptance criteria

- `mind_server.py` does not exist (`ls mind_server.py 2>&1` prints `No such file or directory`).
- Each `minds/<name>/implementation.py` ends with `if __name__ == "__main__": uvicorn.run(...)` and is runnable as `python -m minds.<name>.implementation`.
- Each `minds/<name>/container/compose.yaml` `command:` runs the implementation directly.
- `grep -rn "importlib\|parse_mind_file\|_build_base_prompt\|_fetch_soul_sync\|_load_implementation" core/ server.py 2>&1` returns zero hits.
- `grep -rn "minds/[a-z]" core/ server.py 2>&1` returns zero hits in production code (test fixtures excluded).
- `grep -rn "mind_server" core/ server.py minds/ 2>&1` returns zero hits.
- All four mind containers start (`docker compose up -d --force-recreate ada bob bilby nagatha`) and report healthy via `GET /health` directly on the container.
- A round-trip message (`POST /sessions/{sid}/message` against the gateway → forwarded to the mind container → response streamed back) succeeds end-to-end for each mind. The user verifies this manually after the agent's automated checks pass.

## Out of scope

- Removing or rewriting any of the 38 gateway HTTP endpoints' shapes (URL / body / response). Internal implementation changes; external contract preserved.
- Phase 5 follow-ups (transcript cleanup, `souls/` directory)
