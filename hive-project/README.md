# Hive Mind — Post-Phase 1 Consolidation Project

Source spec: `/home/daniel/Storage/Dev/spark_to_bloom/src/backlog/mind-self-contained-runtime-config.md`.

Phase 1 already shipped (2026-05-01) and introduced **`runtime.yaml`** (the spec calls it `mind.yaml`; the codebase uses `runtime.yaml` — these phase docs use the codebase name throughout).

## Phase order

1. **`phase-1-compose-consolidation.md`** — Per-mind `container/compose.yaml` fragments + explicit `include:` list. Update `generate-compose` skill.
2. **`phase-2-mindmd-deletion.md`** — Move identity prose into `runtime.yaml.description`, sweep references, delete `MIND.md` files.
3. **`phase-3-mind-id-guid.md`** — Add `mind_id: <uuid>` field to `runtime.yaml`. Migration script for sessions DB, KG, broker.
4. **`phase-4-mind-server-elimination.md`** — Each `minds/<name>/implementation.py` becomes the in-container FastAPI service. Delete `mind_server.py`. Strip per-mind code from `core/sessions.py` and `server.py`.
5. **`phase-5-small-followups.md`** — `cleanupPeriodDays` in each mind's `.claude/settings.json`; `rmdir souls/`.

Each phase is its own document with: goals, file-by-file changes, exact code snippets where ambiguous, and acceptance criteria.

## Working repo

`/home/daniel/Storage/Dev/hive_mind/`. Implementation agents operate on this tree directly (no worktree isolation — scope spans many shared files).

## Discipline

Phase 1's "no fallback paths, rip-the-bandaid" approach applies to every phase. No transitional shims.
