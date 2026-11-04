---
name: project-maintenance
description: Use for routine ChatImport upkeep — the quality gate, generated assistant files, state documents, versions, dependency updates, toolchain checks and explicitly requested publishing.
---

# Repository Maintenance

## Fast paths

```bash
just check          # the gate (CI runs the same sections)
just agents         # AGENTS.md + .codex mirror from .ai/ and .claude/
just doctor         # read-only toolchain check
just hooks          # every pre-commit hook over the repository
```

## Rules

- Generated, never hand-edited: `AGENTS.md`, `.codex/agents/*`, `.codex/skills/*`. Edit the
  source, regenerate, commit both together.
- The `AGENTS.md` budget is 30 KiB: tighten a module, or mark a situational one
  `<!-- tier: extended -->` with an `> **Essence.**` line (moving tiers needs owner approval).
- Rule changes follow the `rules-evolution` skill, including `.ai/CHANGELOG.md`.
- `.claude/settings.json`: extending the allowlist is fine; removing a deny entry needs
  explicit owner approval.
- Version lives in `pyproject.toml` (SemVer); a release is a `vX.Y.Z` tag plus a
  `CHANGELOG.md` section.
- Dependencies through `uv add`; a new production dependency is justified and named in the
  final report. Dependabot reads only `main`; update this branch by hand with `uv lock --upgrade-package`.

## State documents

Step done → `docs/ROADMAP.md` `**Status.**` line. Shape changed → project map and
`docs/architecture.md`. Owner decision → `docs/decisions.md`. Architecture decision →
`docs/adr/`. Task closed → `task-checklist.md` with honest `+`/`-` marks.

## Publishing

No pull requests. Merge the task branch into `chatimport` with `git merge --ff-only` after
a green gate and push `chatimport` — only when the owner asked in the current task. `main`
(ChatRadar) is not touched from this line of work.
