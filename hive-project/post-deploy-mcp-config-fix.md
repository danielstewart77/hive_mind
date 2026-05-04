# Post-deploy fix: skip `--mcp-config` when MCP config file is missing

## Problem

After Phase 4 force-recreated the four mind containers, messaging Ada returned an immediate "(no response)". Container logs showed:

```
Error: Invalid MCP configuration:
MCP config file not found: /usr/src/app/.mcp.json
```

`.mcp.container.json` and `.mcp.json` are gitignored (they're deployment-local). On this deployment neither file is present, so the new per-mind `implementation.py` resolves `MCP_CONFIG` to a non-existent path and the claude CLI rejects it.

The old `mind_server.py` handled this case by setting `mcp_config` to `""` when the file was missing; the regression came from porting the logic into `implementation.py` without the empty-string fallback.

## Fix

Two-step:

1. **Deployment-local files** (`minds/{ada,bob,bilby}/implementation.py` — gitignored, NOT in feature branch):
   - Resolve `MCP_CONFIG` to `""` when neither `.mcp.container.json` nor `.mcp.json` exists.
   - Only append `--mcp-config <path>` to the spawn command when `MCP_CONFIG` is truthy.
   - For Bilby (SDK path): `mcp_servers=state["mcp_config"] or {}` already handles the empty case.

2. **Templates** (`mind_templates/claude_cli_*.py` — tracked):
   - Same pattern: only extend `cmd` with `--mcp-config` when the kwarg is non-empty.
   - Captures the fix in git so future deployments scaffolded from these templates inherit the corrected behaviour.

## Verification

```bash
docker compose up -d --force-recreate ada bob bilby

docker exec hive-mind-server bash -c '
  SID=$(curl -s -X POST http://localhost:8420/sessions -H "content-type: application/json" \
    -d "{\"owner_type\":\"telegram\",\"owner_ref\":\"smoke\",\"client_ref\":\"smoke\",\"mind_id\":\"ada\",\"model\":\"sonnet\",\"surface_prompt\":\"Reply with PHASE4OK and nothing else.\"}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)[\"id\"])")
  curl -s -X POST "http://localhost:8420/sessions/$SID/message" \
    -H "content-type: application/json" \
    -d "{\"content\":\"Reply with PHASE4OK and nothing else.\"}" --max-time 30
  curl -s -X DELETE "http://localhost:8420/sessions/$SID"
'
```

Round-trip succeeded with a `result` event and no MCP errors in `docker logs hive-mind-ada`.

## Notes

- Container rebuild was NOT required — the project is bind-mounted into the mind containers (`${HOST_PROJECT_DIR:-.}:/usr/src/app:rw`), so editing `minds/<name>/implementation.py` and `docker compose up -d --force-recreate <mind>` is enough.
- The templates under `mind_templates/` still target the pre-Phase-4 `spawn`-helper architecture (callable from a generic `mind_server.py`). They predate the in-container FastAPI service pattern. Updating them to the new architecture is a follow-up, not part of this fix.
