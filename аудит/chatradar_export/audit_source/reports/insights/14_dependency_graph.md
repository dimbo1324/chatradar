# Dependency Graph

Generated: 2026-11-04 15:23:41 UTC

This report maps internal imports/references using static heuristics. It is intentionally dependency-free and may not resolve every alias.

- Files in graph: **386**
- Internal edges: **191**

## Most imported internal files

- `tests\fakes.py` — imported by 67 file(s)
- `tests\unit\storage\helpers.py` — imported by 17 file(s)
- `tests\unit\gui\conftest.py` — imported by 14 file(s)
- `tests\unit\maintenance\helpers.py` — imported by 10 file(s)
- `tests\unit\service\harness.py` — imported by 10 file(s)
- `tests\unit\worker\rig.py` — imported by 10 file(s)
- `tests\unit\gui\search\fakes.py` — imported by 8 file(s)
- `tests\unit\gui\pages_b\conftest.py` — imported by 7 file(s)
- `tests\unit\service\helpers.py` — imported by 6 file(s)
- `tests\unit\gui\pages_c\conftest.py` — imported by 5 file(s)
- `tests\unit\interfaces\conftest.py` — imported by 5 file(s)
- `scripts\__init__.py` — imported by 4 file(s)
- `tests\unit\gui\pages_a\conftest.py` — imported by 4 file(s)
- `tests\unit\gui\pages_b\archive.py` — imported by 4 file(s)
- `tests\unit\gui\logic\spy.py` — imported by 3 file(s)
- `tests\unit\storage\search_helpers.py` — imported by 3 file(s)
- `tests\unit\gui\onboarding\conftest.py` — imported by 2 file(s)
- `tests\unit\gui\search\conftest.py` — imported by 2 file(s)
- `tests\unit\interfaces\test_cli_commands.py` — imported by 2 file(s)
- `scripts\sync_agents.py` — imported by 1 file(s)
- `tests\unit\gui\pages_c\test_settings_telegram.py` — imported by 1 file(s)
- `tests\unit\gui\shell\test_main_window.py` — imported by 1 file(s)
- `tests\unit\maintenance\test_media.py` — imported by 1 file(s)
- `tests\unit\maintenance\test_trim.py` — imported by 1 file(s)
- `tests\unit\service\test_control.py` — imported by 1 file(s)
- `tests\unit\storage\test_fileio.py` — imported by 1 file(s)
- `tests\unit\worker\tzrules.py` — imported by 1 file(s)

## Internal import edges

### `tests\integration\test_end_to_end.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\core\test_records_lines.py`

- `tests\fakes.py`

### `tests\unit\gui\logic\test_chats_model.py`

- `tests\unit\gui\logic\spy.py`

### `tests\unit\gui\logic\test_data_models.py`

- `tests\unit\gui\logic\spy.py`

### `tests\unit\gui\logic\test_log_model.py`

- `tests\unit\gui\logic\spy.py`

### `tests\unit\gui\logic\test_theme_kit.py`

- `tests\unit\gui\conftest.py`

### `tests\unit\gui\onboarding\conftest.py`

- `tests\unit\gui\pages_c\conftest.py`

### `tests\unit\gui\onboarding\test_steps.py`

- `tests\unit\gui\onboarding\conftest.py`

### `tests\unit\gui\onboarding\test_wizard.py`

- `tests\unit\gui\onboarding\conftest.py`

### `tests\unit\gui\pages_a\test_chats.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_a\conftest.py`

### `tests\unit\gui\pages_a\test_chats_actions.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_a\conftest.py`

### `tests\unit\gui\pages_a\test_chats_delegate.py`

- `tests\unit\gui\pages_a\conftest.py`

### `tests\unit\gui\pages_a\test_overview.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_a\conftest.py`

### `tests\unit\gui\pages_b\archive.py`

- `tests\fakes.py`

### `tests\unit\gui\pages_b\conftest.py`

- `tests\unit\gui\pages_b\archive.py`

### `tests\unit\gui\pages_b\test_data_cleanup.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_b\archive.py`
- `tests\unit\gui\pages_b\conftest.py`

### `tests\unit\gui\pages_b\test_data_export.py`

- `tests\unit\gui\pages_b\archive.py`
- `tests\unit\gui\pages_b\conftest.py`

### `tests\unit\gui\pages_b\test_data_folder.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_b\conftest.py`

### `tests\unit\gui\pages_b\test_data_integrity.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_b\conftest.py`

### `tests\unit\gui\pages_b\test_data_merged.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_b\conftest.py`

### `tests\unit\gui\pages_b\test_data_page.py`

- `tests\unit\gui\pages_b\archive.py`
- `tests\unit\gui\pages_b\conftest.py`

### `tests\unit\gui\pages_b\test_log_page.py`

- `tests\unit\gui\pages_b\conftest.py`

### `tests\unit\gui\pages_c\conftest.py`

- `tests\unit\gui\conftest.py`

### `tests\unit\gui\pages_c\test_settings_page.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_c\conftest.py`

### `tests\unit\gui\pages_c\test_settings_support.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\pages_c\conftest.py`

### `tests\unit\gui\pages_c\test_settings_system.py`

- `tests\unit\gui\pages_c\conftest.py`

### `tests\unit\gui\pages_c\test_settings_telegram.py`

- `tests\unit\gui\pages_c\conftest.py`

### `tests\unit\gui\pages_c\test_settings_telegram_validation.py`

- `tests\unit\gui\pages_c\test_settings_telegram.py`

### `tests\unit\gui\search\conftest.py`

- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\search\test_search_context.py`

- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\search\test_search_delegate.py`

- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\search\test_search_filters.py`

- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\search\test_search_model.py`

- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\search\test_search_page.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\search\conftest.py`
- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\search\test_search_page_actions.py`

- `tests\unit\gui\search\conftest.py`
- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\search\test_search_worker.py`

- `tests\unit\gui\search\fakes.py`

### `tests\unit\gui\shell\test_main_window.py`

- `tests\unit\gui\conftest.py`

### `tests\unit\gui\shell\test_main_window_wizard.py`

- `tests\unit\gui\conftest.py`
- `tests\unit\gui\shell\test_main_window.py`

### `tests\unit\interfaces\conftest.py`

- `tests\fakes.py`

### `tests\unit\interfaces\test_check_language_extra.py`

- `scripts\__init__.py`

### `tests\unit\interfaces\test_cli_commands.py`

- `tests\fakes.py`
- `tests\unit\interfaces\conftest.py`

### `tests\unit\interfaces\test_cli_export_all.py`

- `tests\fakes.py`
- `tests\unit\interfaces\conftest.py`
- `tests\unit\interfaces\test_cli_commands.py`

### `tests\unit\interfaces\test_cli_hardening.py`

- `tests\fakes.py`
- `tests\unit\interfaces\conftest.py`

### `tests\unit\interfaces\test_cli_search.py`

- `tests\fakes.py`
- `tests\unit\interfaces\conftest.py`
- `tests\unit\interfaces\test_cli_commands.py`
- `tests\unit\storage\helpers.py`
- `tests\unit\storage\search_helpers.py`

### `tests\unit\interfaces\test_cli_window.py`

- `tests\unit\interfaces\conftest.py`

### `tests\unit\interfaces\test_doctor.py`

- `scripts\__init__.py`

### `tests\unit\interfaces\test_status_snapshot.py`

- `tests\fakes.py`
- `tests\unit\service\helpers.py`

### `tests\unit\interfaces\test_sync_agents_extra.py`

- `scripts\__init__.py`
- `scripts\sync_agents.py`

### `tests\unit\maintenance\helpers.py`

- `tests\fakes.py`

### `tests\unit\maintenance\test_disk_guard.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`

### `tests\unit\maintenance\test_folder_watcher.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`

### `tests\unit\maintenance\test_guards_hardening.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`

### `tests\unit\maintenance\test_media.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`

### `tests\unit\maintenance\test_media_hardening.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`
- `tests\unit\maintenance\test_media.py`

### `tests\unit\maintenance\test_offline.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`

### `tests\unit\maintenance\test_router_cap.py`

- `tests\fakes.py`

### `tests\unit\maintenance\test_setroot_hardening.py`

- `tests\unit\storage\test_fileio.py`

### `tests\unit\maintenance\test_trim.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`

### `tests\unit\maintenance\test_trim_hardening.py`

- `tests\fakes.py`
- `tests\unit\maintenance\helpers.py`

### `tests\unit\maintenance\test_trim_preview.py`

- `tests\unit\maintenance\helpers.py`
- `tests\unit\maintenance\test_trim.py`

### `tests\unit\maintenance\test_usage.py`

- `tests\unit\maintenance\helpers.py`

### `tests\unit\service\harness.py`

- `tests\fakes.py`

### `tests\unit\service\test_app_commands.py`

- `tests\unit\service\harness.py`

### `tests\unit\service\test_app_edges.py`

- `tests\fakes.py`
- `tests\unit\service\harness.py`
- `tests\unit\service\helpers.py`

### `tests\unit\service\test_app_lifecycle.py`

- `tests\fakes.py`
- `tests\unit\service\harness.py`

### `tests\unit\service\test_app_misc.py`

- `tests\fakes.py`
- `tests\unit\service\harness.py`

### `tests\unit\service\test_app_service.py`

- `tests\fakes.py`
- `tests\unit\service\harness.py`
- `tests\unit\service\helpers.py`

### `tests\unit\service\test_app_setroot.py`

- `tests\unit\service\harness.py`

### `tests\unit\service\test_commands.py`

- `tests\unit\service\harness.py`

### `tests\unit\service\test_control.py`

- `tests\fakes.py`

### `tests\unit\service\test_control_claims.py`

- `tests\unit\service\test_control.py`

### `tests\unit\service\test_integration_glue.py`

- `tests\fakes.py`

### `tests\unit\service\test_merged_service.py`

- `tests\fakes.py`
- `tests\unit\service\harness.py`

### `tests\unit\service\test_resolution.py`

- `tests\unit\service\harness.py`

### `tests\unit\service\test_router.py`

- `tests\fakes.py`
- `tests\unit\service\helpers.py`

### `tests\unit\service\test_search_service.py`

- `tests\fakes.py`
- `tests\unit\service\harness.py`

### `tests\unit\service\test_status.py`

- `tests\fakes.py`
- `tests\unit\service\helpers.py`

### `tests\unit\service\test_status_fields.py`

- `tests\fakes.py`
- `tests\unit\service\helpers.py`

### `tests\unit\service\test_supervisor.py`

- `tests\fakes.py`

### `tests\unit\storage\helpers.py`

- `tests\fakes.py`

### `tests\unit\storage\search_helpers.py`

- `tests\fakes.py`

### `tests\unit\storage\test_chat_store.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_export.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_export_integrity_hardening.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_integrity.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_layout.py`

- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_merged_export.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_month_commit.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_reader.py`

- `tests\fakes.py`

### `tests\unit\storage\test_reader_tail.py`

- `tests\fakes.py`

### `tests\unit\storage\test_recover.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_recover_fast.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_search_fold.py`

- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_search_index.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`
- `tests\unit\storage\search_helpers.py`

### `tests\unit\storage\test_search_indexer.py`

- `tests\fakes.py`
- `tests\unit\storage\search_helpers.py`

### `tests\unit\storage\test_state.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_state_hardening.py`

- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_writer_append.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_writer_hardening.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\storage\test_writer_month.py`

- `tests\fakes.py`
- `tests\unit\storage\helpers.py`

### `tests\unit\telegram\test_client.py`

- `tests\fakes.py`

### `tests\unit\telegram\test_mapper.py`

- `tests\fakes.py`

### `tests\unit\telegram\test_privacy.py`

- `tests\fakes.py`

### `tests\unit\test_scripts.py`

- `scripts\__init__.py`

### `tests\unit\worker\rig.py`

- `tests\fakes.py`

### `tests\unit\worker\test_backfill.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_backfill_slots.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_buffer.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_errors.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_live.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_recheck_compute.py`

- `tests\fakes.py`

### `tests\unit\worker\test_recheck_requests.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_recheck_schedule.py`

- `tests\fakes.py`
- `tests\unit\worker\tzrules.py`

### `tests\unit\worker\test_sync_once.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_worker_edges.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_worker_recovery.py`

- `tests\fakes.py`
- `tests\unit\worker\rig.py`

### `tests\unit\worker\test_worker_status.py`

- `tests\fakes.py`

### `tests\unit\worker\test_worker_store.py`

- `tests\fakes.py`
