# Backlog

Work consciously deferred, with the reason, to come back to. Shipped items move to
`CHANGELOG.md`.

- Dependabot does not watch branch `chatimport` (it reads only the default branch); update
  dependencies by hand with `uv lock --upgrade-package <name>` until the branches merge.
- `.claude/settings.json` still allows ChatRadar-only commands (`chatradar --help`, Docker
  Compose reads). Harmless; tidy up with the owner's approval.
