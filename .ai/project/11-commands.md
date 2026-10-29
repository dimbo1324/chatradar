# Project Commands and Quality Gates

All commands run from the repository root (PowerShell or Git Bash on Windows, any POSIX
shell elsewhere). Toolchain: uv (it installs Python 3.14 from `.python-version`), git,
just; `python scripts/doctor.py` checks all of them read-only.

## The one gate

```bash
just check        # lint, format, pyright strict, pytest, agents sync, language
```

CI runs the same sections as separate jobs. Without `just`, run the recipe's lines from
`justfile` one by one through `uv run`.

| Recipe | Purpose |
|---|---|
| `setup` | `uv sync` + install the pre-commit hook, once per clone |
| `fmt` / `lint` | ruff format + fix / ruff check and format check |
| `typecheck` | pyright strict over `src/`, `tests/`, `scripts/` |
| `test` / `cov` | pytest / with coverage |
| `agents` / `agents-check` | regenerate / verify `AGENTS.md` and `.codex/` |
| `language` | no Cyrillic outside the allowed data paths |
| `doctor` | read-only toolchain check |
| `hooks` | every pre-commit hook over the whole repository |

**Standing duty — keep the tooling true.** A task that changes how the project is checked,
built, run or published updates `justfile`, the CI workflow and this table in the same
task. A source whose artifact is generated (`AGENTS.md`, `.codex/agents|skills`) is
committed together with the regenerated artifact.

## Main branch (strict, owner instruction 2026-10-29)

**In this repository `chatimport` IS the main branch.** Everywhere a rule, skill, agent or
habit says `main`, read `chatimport`: branch from it, merge into it, compare against it,
push it. Never check out, modify, merge into, rebase onto or push `main` — it holds the
unrelated ChatRadar project and is off limits. If a command or document names `main`,
substitute `chatimport` and do not ask.

## Publishing

- No pull requests (owner workflow shared with the owner's other repositories).
- **This line of work lives on branch `chatimport`, not `main`.** Task branches start from
  `chatimport` (`type/short-description`) and merge back into it with
  `git merge --ff-only` after a green `just check`; then `git push origin chatimport`.
  `main` (ChatRadar) is never touched from this branch; joining the two is a separate
  owner decision.
- Agents push only when the owner asked for it in the current task. Never force-push.

## Gate policy

- `just check` is green before any merge into `chatimport`. Docs- and config-only changes
  still run it: the agents-sync and language sections cover them.
- The pre-commit hook formats and checks hygiene, secrets, pyright and generated files;
  it never replaces the full gate.
- Never skip a hook (`--no-verify`) or weaken a check to get green.
