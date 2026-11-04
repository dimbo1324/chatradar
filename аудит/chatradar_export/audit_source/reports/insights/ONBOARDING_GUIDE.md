# Onboarding Guide: chatradar

Generated: 2026-11-04 15:23:41 UTC

A suggested reading order, ranked by the same importance signals as `16_key_files_report.md` (entrypoints, configuration, import fan-in, size, architectural location). Start at the top; each step says why it matters.

Before reading code, see `13_runbook.md` for how to set this project up and run it, and `24_architecture_map.md` for the full per-layer file map.

## Reading order

1. `src\chatimport\app.py` (importance 83)
   - entrypoint/bootstrap filename
2. `tests\fakes.py` (importance 75)
   - imported by 67 internal file(s)
3. `tests\unit\gui\pages_b\conftest.py` (importance 75)
   - imported by 7 internal file(s)
4. `tests\unit\gui\pages_c\conftest.py` (importance 75)
   - imported by 5 internal file(s)
5. `tests\unit\maintenance\helpers.py` (importance 75)
   - imported by 10 internal file(s)
6. `tests\unit\service\harness.py` (importance 75)
   - imported by 10 internal file(s)
7. `tests\unit\worker\rig.py` (importance 75)
   - imported by 10 internal file(s)
8. `tests\unit\gui\conftest.py` (importance 65)
   - imported by 14 internal file(s)
9. `tests\unit\interfaces\conftest.py` (importance 65)
   - imported by 5 internal file(s)
10. `tests\unit\service\helpers.py` (importance 65)
   - imported by 6 internal file(s)
11. `tests\unit\interfaces\test_cli_commands.py` (importance 59)
   - imported by 2 internal file(s)
12. `tests\unit\core\test_config.py` (importance 55)
   - located in an architecturally important folder
13. `tests\unit\core\test_config_edit.py` (importance 55)
   - located in an architecturally important folder
14. `tests\unit\core\test_library.py` (importance 55)
   - located in an architecturally important folder
15. `tests\unit\core\test_library_edit.py` (importance 55)
   - located in an architecturally important folder
