# Architecture Report: chatradar

Generated: 2026-11-04 15:23:41 UTC

This report is a static architecture map based on file/folder conventions and detected tooling.

## Detected technology groups

- **frontend**: not detected
- **backend**: Python
- **tools**: not detected
- **testing**: not detected
- **styling**: not detected
- **infrastructure**: GitHub Actions
- **package_managers**: not detected

## Top-level structure

- `.ai`
- `.claude`
- `.codex`
- `.github`
- `.vscode`
- `data`
- `design`
- `docs`
- `scripts`
- `src`
- `tests`

## Layer map

### UI / presentation

- `src\chatimport\gui\pages`
- `src\chatimport\gui\widgets`

### Application / orchestration

- not detected

### Domain / business logic

- `src\chatimport\gui\models`
- `tests\unit\core`

### Data access / persistence

- `src\chatimport\storage`
- `tests\unit\storage`

### API / transport

- not detected

### Configuration

- not detected

### Tests

- `tests`
- `tests\integration`
- `tests\unit`
- `tests\unit\gui`
- `tests\unit\gui\logic`
- `tests\unit\gui\onboarding`
- `tests\unit\gui\pages_a`
- `tests\unit\gui\pages_b`
- `tests\unit\gui\pages_c`
- `tests\unit\gui\search`
- `tests\unit\gui\shell`
- `tests\unit\interfaces`
- `tests\unit\maintenance`
- `tests\unit\service`
- `tests\unit\telegram`
- `tests\unit\worker`

### Utilities

- not detected

## Entrypoints and bootstrap/config files

- `src\chatimport\__main__.py`
- `src\chatimport\app.py`

## Extension points

- Add new report jobs under `codepack-reports/src/reports/` and register them in the report catalog.
- Add new copy/exclusion rules in `codepack-scanner`'s ignore-rule and stack-detection modules.
- Add new UI surfaces under `apps/desktop/ui`; keep long-running work behind the engine's cancellation-aware pipeline.
- Keep report writers pure: a `ReportContext` in, one report file out.

## Potential architectural risks

- Validate this report manually before making structural refactors; it is heuristic.
