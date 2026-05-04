# Phase 5 — Small follow-ups

## Goals

Two opportunistic cleanups:

1. Set `cleanupPeriodDays` in each mind's `.claude/settings.json` so Claude Code self-prunes session transcripts.
2. Remove the empty `souls/` directory if it exists (already gone in this checkout — verify).

Low blast radius. Land as one PR, or fold into Phase 4's PR.

## Current state

- `minds/ada/.claude/settings.json` exists; contains `hooks` and `enabledPlugins` blocks but no `cleanupPeriodDays`.
- `minds/{bob,bilby,nagatha}/.claude/settings.json` — same situation, presumed (verify with `ls`).
- `souls/` directory: confirmed **does not exist** in `/home/daniel/Storage/Dev/hive_mind/` as of the project kickoff. Skip the `rmdir` step unless it has reappeared.
- The original spec mentions Ada's transcript bloat: `minds/ada/.claude/projects/<sanitised>/sessions/*.jsonl` files, 5,508 of them. The `cleanupPeriodDays` setting is the harness-supported way to bound this.

## File-by-file changes

### 1. Add `cleanupPeriodDays` to each mind's settings.json

For each of the four minds, edit `minds/<name>/.claude/settings.json` to include a top-level `cleanupPeriodDays` key. Choose `30` as the value (the harness's default convention; conservative, plenty of recovery window):

```json
{
  "cleanupPeriodDays": 30,
  "hooks": { ... },
  "enabledPlugins": { ... }
}
```

Use Edit (not Write) to preserve the rest of the file exactly. Add `cleanupPeriodDays` as the first key for visibility.

After:

```bash
for name in ada bob bilby nagatha; do
  python -c "import json; d=json.load(open('minds/$name/.claude/settings.json')); print('$name', d.get('cleanupPeriodDays'))"
done
```

Expected: each prints `<name> 30`.

### 2. Verify `souls/` is gone

```bash
ls souls 2>&1
# Expected: "ls: cannot access 'souls': No such file or directory"
```

If the directory exists and is empty, `rmdir souls`. If it exists and has files, **stop and surface to the user** — do not delete contents.

### 3. Sanity-check transcript cleanup will work

Run a dry test on Ada's directory after the setting lands (no-op if Claude Code isn't running):

```bash
ls minds/ada/.claude/projects 2>&1 | head -5
find minds/ada/.claude/projects -name "*.jsonl" | wc -l
```

These commands are read-only — they tell us how big the backlog currently is. Claude Code itself will prune on its next idle cycle once the setting is in place. **No deletion in this phase** — the harness owns transcript lifecycle.

## Acceptance criteria

- Each `minds/<name>/.claude/settings.json` (n=4) has `cleanupPeriodDays: 30` at the top level.
- `souls/` directory does not exist at the repo root.
- `git diff` shows only:
  - Four `settings.json` files modified (one-line `cleanupPeriodDays` addition each)
  - Possibly one directory removal (`souls/`) if it was present
- No other files changed.

## Out of scope

Everything from Phases 1–4. This is the cleanup-pass phase only.
