# Phase 2 — `MIND.md` deletion

## Goal

Delete every `MIND.md` file from the repo. Move any prose that's worth keeping into the `description` field of the corresponding `runtime.yaml`. Sweep all production-code references to `MIND.md` (none should remain in `core/`, `server.py`, or `mind_server.py`).

The `MIND.md` files today are prose-only stubs that point at the KG soul or list legacy frontmatter; they're no longer parsed. This phase removes them and updates documentation references.

## Current state

- `minds/{ada,bob,bilby,nagatha}/MIND.md` exist and are mostly prose pointing at the runtime.yaml + KG soul.
- `core/sessions.py:336` has a comment referencing `MIND.md soul_seed`.
- `core/mind_registry.py:5,59` has docstrings/messages saying "MIND.md is prose-only".
- `stories/phase2*` directories contain historical story docs that mention `MIND.md` — leave those alone (historical record).
- The plugin source directory `/home/daniel/Storage/Dev/hivemind-claude-plugin/` may have skills referencing `MIND.md` — those need updating.

## File-by-file changes

### 1. Capture identity prose into `runtime.yaml.description`

For each mind, read `minds/<name>/MIND.md`. The existing `description:` field in `runtime.yaml` is a one-liner. If the `MIND.md` contains identity prose **not already covered by the KG soul or the existing `description:`**, do NOT try to fold a long soul into the YAML. Keep `description:` to one or two sentences max. The KG node is authoritative for soul; `description:` is only the operational one-liner.

Practical rule: if the MIND.md says something like "Ada — orchestrator mind, Claude CLI, Anthropic-backed" and the runtime.yaml already has the same in `description:`, leave `description:` as-is.

### 2. Delete the `MIND.md` files

```bash
rm minds/ada/MIND.md minds/bob/MIND.md minds/bilby/MIND.md minds/nagatha/MIND.md
```

### 3. Sweep production-code references

Grep first:

```bash
grep -rn "MIND.md\|MIND\\.md" core/ server.py mind_server.py clients/ 2>&1
```

Update each hit:

- `core/sessions.py:336` — comment `# Graph is authoritative; MIND.md soul_seed is one-time bootstrap only` — rewrite to `# Graph is authoritative for soul; runtime.yaml has no soul field` (or just delete the comment).
- `core/mind_registry.py:5` — docstring line `available minds.  MIND.md is prose-only documentation and is no longer parsed.` — rewrite to `available minds. runtime.yaml is the only file the registry reads from each mind folder.`
- `core/mind_registry.py:59` — error message `"MIND.md is prose-only after Phase 1 of the runtime-config refactor"` — rewrite to `"runtime.yaml is the only mind config file (Phase 1 of runtime-config refactor)"`.

After edits:

```bash
grep -rn "MIND.md\|MIND\\.md" core/ server.py mind_server.py clients/ 2>&1
# Expected: no hits
```

### 4. Sweep skill / plugin references

```bash
grep -rn "MIND.md" /home/daniel/Storage/Dev/hivemind-claude-plugin/ 2>&1
```

For each hit in **active skills** (not historical stories), update the wording. If a skill is genuinely about parsing `MIND.md`, replace with `runtime.yaml`. Skills to scan in particular:

- `skills/generate-compose/SKILL.md` — Phase 1 already updated this; double-check it has no remaining `MIND.md` references after Phase 1.
- `skills/create-mind/`, `skills/add-mind/`, `skills/update-mind/` — if these still reference `MIND.md`, update them to reference `runtime.yaml`.

### 5. Leave historical material alone

Do **not** edit:
- `stories/phase2*/STORY-DESCRIPTION.md`
- `stories/phase2*/IMPLEMENTATION.md`
- Any file under `docs/` that's a dated changelog or design archive

These are point-in-time records. Modifying them rewrites history.

### 6. CLAUDE.md / README

If `CLAUDE.md` or top-level `README.md` mentions `MIND.md` as a current mechanism, update those references to `runtime.yaml`. Keep the wording terse.

## Acceptance criteria

- `ls minds/*/MIND.md 2>&1` shows no files (`No such file or directory` for every glob hit).
- `grep -rn "MIND.md\|MIND\\.md" core/ server.py mind_server.py clients/ minds/ docker-compose.yml docker-compose.example.yml` returns zero hits.
- Active skills under `/home/daniel/Storage/Dev/hivemind-claude-plugin/skills/` have no `MIND.md` references in their bodies (story directories excluded).
- Each mind's `runtime.yaml` still has a one-line `description:` field (do not bloat).
- `python -c "from core.mind_registry import MindRegistry; from pathlib import Path; r = MindRegistry(Path('minds')); r.scan(); print([m.name for m in r.list_all()])"` (run from repo root) prints `['ada', 'bilby', 'bob', 'nagatha']` (or similar ordering) without errors.

## Out of scope

- mind_id GUID (Phase 3)
- `mind_server.py` removal (Phase 4)
- Renaming `runtime.yaml` to `mind.yaml` (not in this project at all)
