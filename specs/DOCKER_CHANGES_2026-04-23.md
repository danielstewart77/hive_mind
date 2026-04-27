# Docker Compose & Config Changes — 2026-04-23

## Summary

Session cleanup to remove legacy/confusing path references in `docker-compose.yml`,
`mind_server.py`, and Ada's hook scripts.

---

## 1. Establish `/mnt/` convention for host bind mounts

All host directories mounted into mind containers now use `/mnt/<name>` as the
container-side path. This replaces the previous `/home/hivemind/<name>` convention,
which was confusing because `/home/hivemind` doesn't exist on the host.

| Old container path | New container path | Env var |
|---|---|---|
| `/home/hivemind/dev` | `/mnt/dev` | `HOST_DEV_DIR` |
| `/home/hivemind/.host-claude` | `/mnt/host-claude` | `HOST_CLAUDE_DIR` |
| `/home/hivemind/documents` | `/mnt/documents` | `HOST_DOCUMENTS_DIR` *(pending)* |
| `/home/hivemind/health` | `/mnt/health` | `HOST_HEALTH_DIR` *(pending)* |

Bob, Bilby, and Nagatha still use old paths — to be updated in the same session.

---

## 2. Strip harness config mounts from thin clients and server

These services are thin HTTP clients to the gateway. They don't invoke any CLI harness
directly and do not need Claude or Codex config mounts.

Removed `HOST_CLAUDE_DIR` and/or `HOST_CODEX_DIR` volume mounts from:
- `server`
- `discord-bot`
- `telegram-bot`
- `telegram-bot-2`
- `nagatha-bot`
- `scheduler`

---

## 3. Ada mind — CLAUDE_CONFIG_DIR points into the project tree

**Before:**
```yaml
- CLAUDE_CONFIG_DIR=/home/hivemind/.claude
volumes:
  - ${HOST_PROJECT_DIR:-.}/minds/ada/.claude:/home/hivemind/.claude:rw
  - ${HOST_CLAUDE_DIR:-~/.claude}:/home/hivemind/.host-claude:ro
```

**After:**
```yaml
- CLAUDE_CONFIG_DIR=/usr/src/app/minds/ada/.claude
volumes:
  - ${HOST_PROJECT_DIR:-.}:/usr/src/app:rw          # already covers minds/ada/.claude
  - ${HOST_CLAUDE_DIR:-~/.claude}:/mnt/host-claude:ro
```

This eliminates the duplicate `HOST_PROJECT_DIR` reference and the redundant bind mount.
`/mnt/host-claude` is retained for credential sync (see item 4).

---

## 4. mind_server.py — fix credential source path and fallback

- `_HOST_CREDS` updated from `/home/hivemind/.host-claude/.credentials.json`
  to `/mnt/host-claude/.credentials.json`
- `_CONFIG_DIR` fallback updated from `/home/hivemind/.claude-config`
  to `/home/hivemind/.claude`

---

## 5. Ada hooks — replace `.claude-config` with `.claude`

`plugin_skills_sync.sh` was referencing `$HOME/.claude-config/...`. Updated to read
from `$CLAUDE_CONFIG_DIR` (with `$HOME/.claude` as fallback), making it harness-agnostic.

---

## 6. Scheduler — add missing HOST_PROJECT_DIR mount

The scheduler container was running from the baked-in image copy of the code.
Added `${HOST_PROJECT_DIR:-.}:/usr/src/app` so live source changes are picked up
without a full rebuild.

---

## Files changed

- `docker-compose.yml`
- `mind_server.py` (lines 54, 57)
- `minds/ada/.claude/hooks/plugin_skills_sync.sh`
- `minds/ada/.claude/settings.json` (hook paths corrected earlier in session)
