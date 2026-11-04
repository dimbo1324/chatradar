# Refactoring Opportunities

Generated: 2026-11-04 15:23:41 UTC

This report translates metrics and dependency signals into practical refactoring candidates.

## `tests\unit\gui\search\fakes.py`

Priority score: **60**

Reasons:
- central dependency imported by 8 internal file(s)
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces
- move long-running work and file-system operations behind service/worker classes

## `src\chatimport\gui\login_flow.py`

Priority score: **50**

Reasons:
- large file (396 lines)
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\shell\test_login_flow.py`

Priority score: **50**

Reasons:
- large file (415 lines)
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\shell\test_service_host.py`

Priority score: **50**

Reasons:
- large file (446 lines)
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\interfaces\test_cli_commands.py`

Priority score: **48**

Reasons:
- very large file (1100 lines)
- contains technical-debt markers

Suggested actions:
- convert repeated TODO/FIXME items into tracked tasks
- split by responsibility into smaller modules/components

## `tests\unit\service\test_app_misc.py`

Priority score: **48**

Reasons:
- very large file (531 lines)
- contains technical-debt markers

Suggested actions:
- convert repeated TODO/FIXME items into tracked tasks
- split by responsibility into smaller modules/components

## `tests\unit\service\test_control.py`

Priority score: **48**

Reasons:
- very large file (583 lines)
- contains technical-debt markers

Suggested actions:
- convert repeated TODO/FIXME items into tracked tasks
- split by responsibility into smaller modules/components

## `tests\unit\worker\rig.py`

Priority score: **43**

Reasons:
- central dependency imported by 10 internal file(s)
- contains technical-debt markers

Suggested actions:
- convert repeated TODO/FIXME items into tracked tasks
- keep public functions stable; extract volatile logic behind small interfaces

## `src\chatimport\gui\pages\log.py`

Priority score: **40**

Reasons:
- very large file (534 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `src\chatimport\gui\pages\search.py`

Priority score: **40**

Reasons:
- very large file (515 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `src\chatimport\trim.py`

Priority score: **40**

Reasons:
- very large file (538 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `src\chatimport\worker.py`

Priority score: **40**

Reasons:
- very large file (522 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\core\test_library.py`

Priority score: **40**

Reasons:
- very large file (548 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\core\test_records.py`

Priority score: **40**

Reasons:
- very large file (510 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\interfaces\test_sync_agents_extra.py`

Priority score: **40**

Reasons:
- very large file (522 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\maintenance\test_media.py`

Priority score: **40**

Reasons:
- very large file (569 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\maintenance\test_trim.py`

Priority score: **40**

Reasons:
- very large file (721 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\service\test_app_lifecycle.py`

Priority score: **40**

Reasons:
- very large file (503 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\storage\test_search_index.py`

Priority score: **40**

Reasons:
- very large file (584 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\storage\test_search_indexer.py`

Priority score: **40**

Reasons:
- very large file (765 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\telegram\test_client.py`

Priority score: **40**

Reasons:
- very large file (1054 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\telegram\test_mapper.py`

Priority score: **40**

Reasons:
- very large file (541 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\worker\test_backfill.py`

Priority score: **40**

Reasons:
- very large file (507 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\worker\test_live.py`

Priority score: **40**

Reasons:
- very large file (743 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\unit\worker\test_recheck_compute.py`

Priority score: **40**

Reasons:
- very large file (500 lines)

Suggested actions:
- split by responsibility into smaller modules/components

## `tests\fakes.py`

Priority score: **35**

Reasons:
- central dependency imported by 67 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `tests\unit\gui\conftest.py`

Priority score: **35**

Reasons:
- central dependency imported by 14 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `tests\unit\gui\pages_b\conftest.py`

Priority score: **35**

Reasons:
- central dependency imported by 7 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `tests\unit\maintenance\helpers.py`

Priority score: **35**

Reasons:
- central dependency imported by 10 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `tests\unit\service\harness.py`

Priority score: **35**

Reasons:
- central dependency imported by 10 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `tests\unit\storage\helpers.py`

Priority score: **35**

Reasons:
- central dependency imported by 17 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `src\chatimport\search_indexer.py`

Priority score: **33**

Reasons:
- large file (327 lines)
- contains technical-debt markers

Suggested actions:
- convert repeated TODO/FIXME items into tracked tasks
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\service\test_control_claims.py`

Priority score: **33**

Reasons:
- large file (311 lines)
- contains technical-debt markers

Suggested actions:
- convert repeated TODO/FIXME items into tracked tasks
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\storage\test_integrity.py`

Priority score: **33**

Reasons:
- large file (377 lines)
- contains technical-debt markers

Suggested actions:
- convert repeated TODO/FIXME items into tracked tasks
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\service\helpers.py`

Priority score: **30**

Reasons:
- central dependency imported by 6 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `src\chatimport\app.py`

Priority score: **25**

Reasons:
- large file (367 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\cli_data.py`

Priority score: **25**

Reasons:
- large file (304 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\commands.py`

Priority score: **25**

Reasons:
- large file (353 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\gui\locales\chats.py`

Priority score: **25**

Reasons:
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes

## `src\chatimport\gui\locales\overview.py`

Priority score: **25**

Reasons:
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes

## `src\chatimport\gui\locales\settings.py`

Priority score: **25**

Reasons:
- large file (437 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\gui\locales\shell.py`

Priority score: **25**

Reasons:
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes

## `src\chatimport\gui\main_window.py`

Priority score: **25**

Reasons:
- large file (368 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\gui\models\chats_model.py`

Priority score: **25**

Reasons:
- large file (320 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\gui\models\log_tail.py`

Priority score: **25**

Reasons:
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes

## `src\chatimport\gui\pages\chats.py`

Priority score: **25**

Reasons:
- large file (352 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\gui\pages\overview.py`

Priority score: **25**

Reasons:
- large file (350 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\gui\pages\settings_telegram.py`

Priority score: **25**

Reasons:
- large file (319 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\gui\service_host.py`

Priority score: **25**

Reasons:
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes

## `src\chatimport\gui\stylesheet.py`

Priority score: **25**

Reasons:
- large file (341 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\merged_export.py`

Priority score: **25**

Reasons:
- large file (311 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\records.py`

Priority score: **25**

Reasons:
- large file (327 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\search_index.py`

Priority score: **25**

Reasons:
- large file (325 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\telegram\client.py`

Priority score: **25**

Reasons:
- large file (356 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `src\chatimport\worker_backfill.py`

Priority score: **25**

Reasons:
- large file (362 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\integration\test_end_to_end.py`

Priority score: **25**

Reasons:
- large file (325 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\core\test_config.py`

Priority score: **25**

Reasons:
- large file (332 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\core\test_config_edit.py`

Priority score: **25**

Reasons:
- large file (343 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\core\test_library_edit.py`

Priority score: **25**

Reasons:
- large file (448 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\core\test_runtime_ports.py`

Priority score: **25**

Reasons:
- large file (300 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\logic\test_chats_model.py`

Priority score: **25**

Reasons:
- large file (443 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\logic\test_log_tail.py`

Priority score: **25**

Reasons:
- large file (381 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\logic\test_settings_zoom.py`

Priority score: **25**

Reasons:
- large file (320 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\onboarding\test_steps.py`

Priority score: **25**

Reasons:
- large file (361 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\pages_c\conftest.py`

Priority score: **25**

Reasons:
- central dependency imported by 5 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `tests\unit\gui\search\test_search_page.py`

Priority score: **25**

Reasons:
- large file (498 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\search\test_search_page_actions.py`

Priority score: **25**

Reasons:
- large file (430 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\search\test_search_worker.py`

Priority score: **25**

Reasons:
- UI code contains infrastructure or worker orchestration concerns

Suggested actions:
- move long-running work and file-system operations behind service/worker classes

## `tests\unit\gui\shell\test_main_window.py`

Priority score: **25**

Reasons:
- large file (322 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\gui\shell\test_widgets_interactive.py`

Priority score: **25**

Reasons:
- large file (383 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\interfaces\conftest.py`

Priority score: **25**

Reasons:
- central dependency imported by 5 internal file(s)

Suggested actions:
- keep public functions stable; extract volatile logic behind small interfaces

## `tests\unit\interfaces\test_autostart.py`

Priority score: **25**

Reasons:
- large file (325 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\maintenance\test_disk_guard.py`

Priority score: **25**

Reasons:
- large file (352 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\maintenance\test_folder_watcher.py`

Priority score: **25**

Reasons:
- large file (422 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\maintenance\test_offline.py`

Priority score: **25**

Reasons:
- large file (427 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\maintenance\test_setroot.py`

Priority score: **25**

Reasons:
- large file (479 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\service\test_app_commands.py`

Priority score: **25**

Reasons:
- large file (378 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\service\test_app_service.py`

Priority score: **25**

Reasons:
- large file (312 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\service\test_search_service.py`

Priority score: **25**

Reasons:
- large file (356 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated

## `tests\unit\service\test_status.py`

Priority score: **25**

Reasons:
- large file (420 lines)

Suggested actions:
- review whether UI, orchestration, and pure helpers can be separated
