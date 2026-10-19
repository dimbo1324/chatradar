---
# GENERATED from .claude/skills/ci-fix/SKILL.md by just agents - do not edit.
name: ci-fix
description: Use when just check, a pre-commit hook or the GitHub Actions CI fails — reproduce locally, find the failing section, fix the cause without weakening any check.
---

# Fixing a Failing Check

1. Reproduce with `just check`; CI runs the same sections as separate jobs (see
   `.github/workflows/ci.yml`), plus gitleaks and a Docker build with a smoke test.
2. Run the failing section alone: `just lint`, `just typecheck`, `just test`,
   `just agents-check`, `just language`, `uv lock --check`.
3. Typical causes:
   - `agents-check`: `.ai/` or `.claude/agents|skills` changed without regeneration. Run
     `just agents` and commit the generated files.
   - `language`: Cyrillic in a tracked file. Translate it; only genuine data belongs in
     the allowed paths of `scripts/check_language.py`.
   - `uv lock --check`: `pyproject.toml` changed without `uv lock`.
   - pyright strict: an untyped library value leaking out — type it at the boundary.
   - Docker job: a file the build needs is missing from the `.dockerignore` allowlist.
   - Windows-only failures: see the platform notes in `.ai/project/14-command-reference.md`.
   - gitleaks: a secret reached git. Remove it **and rotate it**; deleting the line is not
     enough.
4. Never delete, skip or loosen a test or a check to get green, and never use
   `--no-verify`. If a rule itself is wrong, follow the `rules-evolution` skill.
