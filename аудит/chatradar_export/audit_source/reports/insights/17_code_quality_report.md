# Code Quality Report

Generated: 2026-11-04 15:23:41 UTC

This report highlights maintainability risks using static heuristics. Treat findings as review prompts, not absolute errors.

## Summary

- Source files analysed: 386
- Large files >= 400 lines: 37
- Long Python classes/functions >= 80 lines: 71
- Files with TODO/FIXME-like markers: 11
- Duplicate filename groups: 6

## Large files

- `tests\unit\interfaces\test_cli_commands.py` — 1100 lines
- `tests\unit\telegram\test_client.py` — 1054 lines
- `tests\unit\storage\test_search_indexer.py` — 765 lines
- `tests\unit\worker\test_live.py` — 743 lines
- `tests\unit\maintenance\test_trim.py` — 721 lines
- `tests\unit\storage\test_search_index.py` — 584 lines
- `tests\unit\service\test_control.py` — 583 lines
- `tests\unit\maintenance\test_media.py` — 569 lines
- `tests\unit\core\test_library.py` — 548 lines
- `tests\unit\telegram\test_mapper.py` — 541 lines
- `src\chatimport\trim.py` — 538 lines
- `src\chatimport\gui\pages\log.py` — 534 lines
- `tests\unit\service\test_app_misc.py` — 531 lines
- `src\chatimport\worker.py` — 522 lines
- `tests\unit\interfaces\test_sync_agents_extra.py` — 522 lines
- `src\chatimport\gui\pages\search.py` — 515 lines
- `tests\unit\core\test_records.py` — 510 lines
- `tests\unit\worker\test_backfill.py` — 507 lines
- `tests\unit\service\test_app_lifecycle.py` — 503 lines
- `tests\unit\worker\test_recheck_compute.py` — 500 lines
- `tests\unit\gui\search\test_search_page.py` — 498 lines
- `tests\unit\maintenance\test_setroot.py` — 479 lines
- `tests\unit\worker\test_worker_recovery.py` — 472 lines
- `tests\unit\core\test_library_edit.py` — 448 lines
- `tests\unit\gui\shell\test_service_host.py` — 446 lines
- `tests\unit\gui\logic\test_chats_model.py` — 443 lines
- `tests\unit\telegram\test_resolve.py` — 439 lines
- `src\chatimport\gui\locales\settings.py` — 437 lines
- `tests\unit\storage\test_writer_month.py` — 431 lines
- `tests\unit\gui\search\test_search_page_actions.py` — 430 lines
- `tests\unit\maintenance\test_offline.py` — 427 lines
- `tests\unit\maintenance\test_folder_watcher.py` — 422 lines
- `tests\unit\service\test_status.py` — 420 lines
- `tests\unit\gui\shell\test_login_flow.py` — 415 lines
- `tests\unit\storage\test_recover.py` — 409 lines
- `tests\unit\storage\test_merged_export.py` — 404 lines
- `tests\unit\storage\test_writer_append.py` — 402 lines

## Long Python classes/functions

- `src\chatimport\gui\pages\log.py`:67 `LogPage` — 468 lines
- `src\chatimport\worker.py`:77 `ChatWorker` — 446 lines
- `src\chatimport\gui\pages\search.py`:84 `SearchPage` — 432 lines
- `src\chatimport\app.py`:60 `ChatImportApp` — 308 lines
- `src\chatimport\gui\main_window.py`:78 `MainWindow` — 291 lines
- `src\chatimport\gui\pages\chats.py`:66 `ChatsPage` — 287 lines
- `src\chatimport\gui\pages\overview.py`:75 `OverviewPage` — 276 lines
- `src\chatimport\gui\pages\settings_telegram.py`:54 `TelegramCard` — 266 lines
- `src\chatimport\trim.py`:219 `Trimmer` — 264 lines
- `src\chatimport\gui\pages\data_merged.py`:45 `MergedCard` — 245 lines
- `src\chatimport\gui\service_host.py`:61 `ServiceHost` — 236 lines
- `src\chatimport\gui\login_flow.py`:179 `LoginDialog` — 218 lines
- `src\chatimport\gui\widgets\sidebar.py`:47 `Sidebar` — 202 lines
- `tests\unit\telegram\test_client.py`:723 `TestEvents` — 196 lines
- `src\chatimport\gui\pages\settings.py`:57 `SettingsPage` — 186 lines
- `src\chatimport\search_indexer.py`:143 `IndexBuilder` — 185 lines
- `src\chatimport\telegram\client.py`:155 `TelethonGateway` — 178 lines
- `src\chatimport\gui\pages\search_context.py`:35 `ContextPanel` — 169 lines
- `src\chatimport\media.py`:87 `MediaDownloader` — 167 lines
- `src\chatimport\gui\pages\search_delegate.py`:101 `SearchDelegate` — 166 lines
- `src\chatimport\gui\models\chats_model.py`:76 `ChatsTableModel` — 165 lines
- `src\chatimport\gui\pages\data_cleanup.py`:41 `CleanupCard` — 165 lines
- `src\chatimport\gui\pages\chats_delegate.py`:41 `ChatsDelegate` — 162 lines
- `src\chatimport\gui\widgets\nav_item.py`:23 `NavItem` — 162 lines
- `src\chatimport\service_runtime.py`:78 `ServiceRuntime` — 152 lines
- `src\chatimport\gui\pages\log_delegate.py`:45 `LogDelegate` — 150 lines
- `src\chatimport\commands.py`:207 `ServiceCommands` — 145 lines
- `src\chatimport\gui\models\log_tail.py`:93 `LogTail` — 142 lines
- `src\chatimport\gui\setup_wizard.py`:39 `SetupWizard` — 139 lines
- `src\chatimport\search_index.py`:83 `SearchIndex` — 138 lines
- `src\chatimport\gui\pages\data_export.py`:34 `ExportCard` — 136 lines
- `src\chatimport\gui\pages\chats_actions.py`:38 `ChatActions` — 135 lines
- `src\chatimport\gui\pages\settings_appearance.py`:79 `AppearanceCard` — 133 lines
- `src\chatimport\search_reader.py`:75 `SearchReader` — 132 lines
- `src\chatimport\gui\pages\data_integrity.py`:42 `IntegrityCard` — 125 lines
- `src\chatimport\gui\pages\data_storage.py`:52 `StorageCard` — 125 lines
- `src\chatimport\worker_backfill.py`:165 `TailBackfill` — 121 lines
- `src\chatimport\gui\setup_steps.py`:84 `KeysStep` — 120 lines
- `src\chatimport\status.py`:32 `StatusWriter` — 117 lines
- `src\chatimport\gui\pages\chats.py`:70 `__init__` — 117 lines
- `src\chatimport\gui\widgets\segmented.py`:61 `Segmented` — 115 lines
- `src\chatimport\storage\writer.py`:89 `ChunkWriter` — 113 lines
- `src\chatimport\gui\models\log_model.py`:47 `LogModel` — 112 lines
- `src\chatimport\gui\pages\data_folder_dialog.py`:32 `FolderDialog` — 112 lines
- `src\chatimport\guards\folders.py`:32 `FolderWatcher` — 111 lines
- `src\chatimport\gui\pages\settings_config.py`:128 `ConfigCard` — 110 lines
- `tests\unit\telegram\test_client.py`:38 `FakeTelegramClient` — 110 lines
- `src\chatimport\gui\pages\library_dialog.py`:79 `LibraryDialog` — 108 lines
- `tests\fakes.py`:109 `FakeGateway` — 106 lines
- `src\chatimport\gui\widgets\progress.py`:28 `ProgressBar` — 104 lines
- `src\chatimport\gui\pages\settings_system.py`:36 `StartupCard` — 103 lines
- `src\chatimport\worker_live.py`:27 `LiveIntake` — 100 lines
- `src\chatimport\control.py`:112 `ControlServer` — 97 lines
- `src\chatimport\gui\models\log_source.py`:29 `LogSource` — 97 lines
- `src\chatimport\gui\pages\data_folder.py`:34 `FolderCard` — 97 lines
- `src\chatimport\gui\pages\log.py`:71 `__init__` — 97 lines
- `tests\unit\telegram\test_client.py`:371 `TestResolveThroughTelethon` — 97 lines
- `src\chatimport\gui\pages\search_filters.py`:30 `ChatFilter` — 94 lines
- `src\chatimport\gui\setup_steps_data.py`:57 `ChatsStep` — 91 lines
- `src\chatimport\gui\widgets\toast.py`:38 `Toast` — 91 lines
- `tests\unit\service\harness.py`:78 `Env` — 91 lines
- `tests\unit\telegram\test_client.py`:965 `TestLogin` — 90 lines
- `src\chatimport\guards\disk.py`:47 `DiskGuard` — 89 lines
- `src\chatimport\gui\models\search_model.py`:30 `SearchResultsModel` — 89 lines
- `src\chatimport\gui\setup_steps_data.py`:148 `FolderStep` — 88 lines
- `src\chatimport\merged_service.py`:33 `MergedExporter` — 86 lines
- `src\chatimport\gui\shell_widgets.py`:74 `DownloadIndicator` — 84 lines
- `src\chatimport\search_service.py`:37 `SearchIndexer` — 83 lines
- `src\chatimport\worker_signals.py`:24 `WorkerSignals` — 83 lines
- `src\chatimport\gui\login_flow.py`:97 `LoginSession` — 82 lines
- `tests\unit\worker\rig.py`:47 `Rig` — 81 lines

## Possible mixed-responsibility files

- `src\chatimport\gui\locales\chats.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `src\chatimport\gui\locales\overview.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `src\chatimport\gui\locales\shell.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `src\chatimport\gui\login_flow.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `src\chatimport\gui\models\log_tail.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `src\chatimport\gui\service_host.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `tests\unit\gui\search\fakes.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `tests\unit\gui\search\test_search_worker.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `tests\unit\gui\shell\test_login_flow.py`
  - UI file appears to contain infrastructure/threading/file-system logic
- `tests\unit\gui\shell\test_service_host.py`
  - UI file appears to contain infrastructure/threading/file-system logic

## Repeated filenames

### `skill.md` (12 files)
- `.claude\skills\ci-fix\SKILL.md`
- `.claude\skills\code-review\SKILL.md`
- `.claude\skills\format-change\SKILL.md`
- `.claude\skills\project-maintenance\SKILL.md`
- `.claude\skills\rules-evolution\SKILL.md`
- `.claude\skills\step-episode\SKILL.md`
- `.codex\skills\ci-fix\SKILL.md`
- `.codex\skills\code-review\SKILL.md`
- `.codex\skills\format-change\SKILL.md`
- `.codex\skills\project-maintenance\SKILL.md`
- `.codex\skills\rules-evolution\SKILL.md`
- `.codex\skills\step-episode\SKILL.md`

### `conftest.py` (9 files)
- `tests\conftest.py`
- `tests\unit\gui\conftest.py`
- `tests\unit\gui\onboarding\conftest.py`
- `tests\unit\gui\pages_a\conftest.py`
- `tests\unit\gui\pages_b\conftest.py`
- `tests\unit\gui\pages_c\conftest.py`
- `tests\unit\gui\search\conftest.py`
- `tests\unit\gui\shell\conftest.py`
- `tests\unit\interfaces\conftest.py`

### `readme.md` (5 files)
- `.ai\README.md`
- `.claude\README.md`
- `.codex\README.md`
- `docs\adr\README.md`
- `README.md`

### `chat.json` (4 files)
- `data\raw\telegram\-1001800000001\chat.json`
- `data\raw\telegram\-1001800000002\chat.json`
- `data\raw\telegram\-1001800000003\chat.json`
- `data\raw\telegram\-1001800000004\chat.json`

### `helpers.py` (3 files)
- `tests\unit\maintenance\helpers.py`
- `tests\unit\service\helpers.py`
- `tests\unit\storage\helpers.py`

### `settings.py` (3 files)
- `src\chatimport\gui\locales\settings.py`
- `src\chatimport\gui\pages\settings.py`
- `src\chatimport\gui\settings.py`
