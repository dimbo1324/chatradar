# ChatRadar / ChatImport — independent source audit

Audit date: 2026-11-04 (Europe/Moscow). Snapshot: chatradar_export_20261104_152340.zip, directory chatradar. The implemented Python package is named ChatImport; this report does not assume that the unrelated ChatRadar main branch is included.

## Executive assessment

The project has substantial engineering foundations: separated Telegram/storage/UI layers, dependency injection, atomic persistence, bounded live queues, extensive backend and Qt tests, and a locked dependency set. It is not ready for an unqualified standalone desktop release. Confirmed priorities are incomplete combined-export publication and attachment staging/resource limits. Installer support requires implementation and installed-artifact validation.

Three specialist reviewers inspected security, architecture/data correctness, and portability/packaging. The lead independently checked the cited source paths, ran the existing checks, and requested synthetic reproductions of the strongest findings. Findings below distinguish defects, product limitations and release work; no critical remote-code-execution exploit is claimed.

P1: fix before relying on the affected feature or distributing installers. P2: important reliability, security or validation gap. P3: maintainability improvement. An installer release blocker is not necessarily a fault in current source-mode execution.

## Scope and evidence

Source code was not edited. The supplied archive has no .git history, so commit/history checks and the Git-based language gate cannot be completed. Existing documentation was consulted for orientation only; findings derive from code. Existing .coverage and supplied reports were not used as proof of this run. No credentials, session contents or personal messages were inspected, and no real Telegram login was performed. Reproduction scripts use temporary synthetic data.

Python 3.14.3 and uv were already installed. `uv sync --locked` created an isolated .venv and installed 36 locked packages. The audit also ran pip-audit through uvx. Existing system tools were not removed. Source archives and the isolated environment are retained so findings remain reproducible; deletion was optional in the request.

Evidence is in `audit_evidence/`; source locations below are relative to `audit_source/chatradar/`. Specialist reports are incorporated below. Run details and coverage follow the findings.

# Security and OS friendliness audit

Scope: static source inspection; no live Telegram login or real account data accessed. Paths below are relative to audit_source/chatradar. Findings are source-confirmed, not claims of demonstrated exploitation.

## SEC-1 — P1: Downloaded executable is exposed before neutralization
Location: src/chatimport/telegram/client.py:254–262; src/chatimport/media.py:228–238.
Trigger: an enabled document download has an executable extension, or the process terminates after Telethon writes it and before postprocessing. The gateway writes directly into the visible archive directory using the download's original filename. Only after completion does the downloader rename unsafe extensions and attach Mark of the Web. Cancellation, network error and process crashes bypass both steps and can leave executable partial/complete files without the intended protections. This defeats the explicit safety policy in storage/media_files.py. No automatic execution is alleged; the risk is opening an apparently downloaded archive attachment and antivirus exposure.
Fix: allocate an unpredictable private staging filename with a neutral extension before downloading; pass that exact file path or opened file object to Telethon; mark it before publication; validate that the returned path remains in staging, and atomically publish only after successful completion. Remove staged files on cancellation/failure and clean stale staging files at startup. Test cancellation and an exception after bytes have been written.

## SEC-2 — P2: Configured media size cap is not enforced against current/downloaded bytes
Location: src/chatimport/media.py:142–145,228–238; src/chatimport/telegram/client.py:254–261.
Trigger: archived metadata has no size, or a message's attachment changes after metadata was recorded. `_wanted` accepts unknown sizes, and download_media fetches the current message without checking its current size. Neither a byte-limited writer nor progress cancellation nor a final length check exists. Thus max_file_bytes is a filter on historical metadata, not an actual resource bound. A large attachment can consume disk/network beyond the user's configured limit. Disk pausing does not cancel the download already in progress.
Fix: check current message metadata, reject unknown size or enforce a counting stream, abort when the byte count exceeds the configured cap, remove partial files; combine with staging in SEC-1. Test unknown size and attachment replacement after archive ingestion.

## SEC-3 — P2: Permission failures silently fail open for Telegram session
Location: src/chatimport/paths.py:50–59; src/chatimport/telegram/client.py:80–89.
Trigger: an existing/custom POSIX application directory has permissive rights and chmod fails (unsupported mount, ownership or permissions). Both hardening paths suppress every OSError, then allow normal operation. The session grants account access and there is no indication that the claimed owner-only protection was not established.
Fix: validate ownership and actual modes before creating/opening the session, fail with an actionable message for a genuinely accessible session, or require an explicit informed override for unsupported filesystems. Ignore only a missing SQLite companion file; do not silently suppress failure for the main session or its parent. Test simulated PermissionError and permissive existing directories. Windows defaults rely on inherited per-user ACLs; custom app directories should have their ACL assumptions documented/validated too.

## SEC-4 — P2: Export package contains a private configuration file
Location: .env (1832 bytes in supplied archive; content deliberately not read).
The source delivery includes a nonempty .env, despite the project's policy excluding private configuration. Presence alone does not prove that values are live secrets. It is an actionable packaging hygiene defect requiring owner-side verification; do not reproduce values in the audit. If actual credentials exist, stop distributing this archive and rotate the relevant credentials/session according to their type. Build export artifacts from an allowlist of tracked source files, reject .env/session files and private data paths, and scan the resulting artifact before distribution.

## Positive controls observed
- No control network port: file queue limits command payloads to 64 KiB, validates JSON objects, claims commands by rename, and whitelists registered handlers (control.py).
- SQL query values are bound parameters; FTS terms are quoted (search_reader.py).
- Search links are constructed as https://t.me links by mapper.message_link, so raw QDesktopServices.openUrl is not a demonstrated arbitrary-scheme injection here.
- Autostart requests LeastPrivilege, uses a visible named task and fixed argument lists without a shell. User-facing enable/disable exists. No antivirus evasion is appropriate or needed.
- Media suffix allowlist, Mark of the Web, POSIX private session modes, rotating logs and atomic writes already exist; the defects above concern gaps in their lifecycle.

## Release guidance
Prefer a signed, reproducible per-user installer with clear publisher, version metadata, opt-in autostart and complete uninstall of binaries/tasks while keeping user data unless separately selected. Do not request antivirus exclusions or disable protection. Evaluate clean Windows installation, signature verification and false-positive submissions against actual release artifacts; source inspection cannot guarantee antivirus reputation. The current autostart command always uses `-m chatimport window --hidden` (autostart.py:26,81); a frozen application will need a dedicated executable-aware launch contract.

## Synthetic verification addendum
Executed security-repro.py using the project's Python environment; captured security-repro-results.json beside this report. The test uses existing synthetic test fixtures and inert bytes in TemporaryDirectory, never real Telegram or production archive data. SEC-1 reproduced: gateway writes inert synthetic.exe then raises ConnectionError; actual MediaDownloader leaves original extension and no Zone.Identifier. SEC-2 reproduced: unknown metadata size, configured 1 MiB limit, fake gateway returns 1 MiB + 1 byte; actual downloader records and keeps oversized attachment. Media downloads are DISABLED by default and types is empty; document downloads require explicit configuration. parse_config accepts enabled=true, types=[document], max_file_mb=1. Existing test_media_hardening.py tests successful executable neutralization but not interrupted downloads. Reproduction script exits successfully only if expected setup and saved record assertions hold; output reports measured states.
# Architecture and data-correctness audit

Scope: static code review; paths below relative to audit_source/chatradar. No source edits. Findings are source-confirmed. A1 additionally reproduced with synthetic data in audit_evidence/repro_A1.py; result recorded in audit_evidence/repro_A1_result.txt.

## A1 — P1: combined export silently publishes incomplete data and caches it as current
Location: src/chatimport/merged_export.py:104-108, 178-184, 286-311.
Trigger: a part exists but temporarily cannot be opened (permission/sharing/I/O error), while its state.json remains readable. `_safe_part` catches every OSError and returns no records. `_write` then completes and atomically replaces the previous good export; metadata records the unchanged signature derived from state.json. Subsequent non-forced builds see the same signature and skip even after the part becomes readable. This is silent persistent omission from an apparently successful archive.
Fix: propagate read errors and abort the atomic writer, preserving the previous export. If partial exports are desired, explicitly return incomplete status, list failed parts, and never save a current cache marker. Add test with injected PermissionError on one part, restore access, assert old output survives and next build retries.

## A2 — P2: newest-month backfill has no bounded-memory flush
Location: src/chatimport/worker_backfill.py:113-135; contrast tail chunking at 238-240.
`collect_newest_month` accumulates the entire latest populated month in a Python list; batch_size only triggers a pause. Busy groups can exhaust RAM before any head data is committed, and restart repeats the same download. Month merge adds further memory pressure. Fix: bound head batches and merge/checkpoint incrementally using the existing durable month mechanism; distinguish incomplete head from committed head so restart resumes correctly. Test a synthetic large month with an instrumented buffer bound and interruption/resume.

## A3 — P2: overflow recovery cannot restore edits/deletes outside the recheck window
Location: src/chatimport/worker_live.py:49-54; worker_buffer.py:131-137; worker.py:402-408, 427-442; recheck.py:70-82, 125.
When live queues overflow, events of every kind are dropped. Recovery requests catch-up (new IDs only) plus a configured recent-days recheck. A deleted/edited older message is outside that window, so its dropped change is permanently absent. The log wording suggests catching up repairs the loss, but this only covers some events. Fix: retain compact affected ID sets for edits/deletions, or durably spool events before dropping; reconcile affected IDs directly and expose an explicit completeness warning if recovery is impossible. Test overflow with a deletion older than configured days and with backfill still running.

## A4 — P2 improvement / intentional conservative limitation: empty windows never produce deletion records during recheck
Location: src/chatimport/recheck.py:146-150.
This is explicitly implemented as a conservative policy, not an accidental branch or proven violation of a specified contract. If all known window messages were genuinely deleted while the service was offline, `known` is nonempty and `seen` empty. The guard skips all deletion records indefinitely. It avoids false deletion on a suspicious empty response, but also prevents legitimate reconciliation. Fix: treat empty window as a verification-required result, confirm with a separate authenticated lookup of known IDs/access check, then emit deletes only for confirmed missing IDs. Keep the current guard for unverified/transient emptiness. Test both genuine complete deletion and partial/failed Telegram access.

## A5 — P3: decompose orchestration by responsibilities, not by arbitrary inheritance
Measured source sizes: trim.py 538 lines; gui/pages/log.py 534; worker.py 522; gui/pages/search.py 515. Most modules are already small and the code has protocols, injected collaborators, storage boundaries, and dedicated worker components. These four exceed the project's approximate 500-line guideline but size alone is not a runtime bug. ChatWorker still combines supervision, lifecycle, recovery, head/catch-up, live intake, status and recheck. Extract a recheck coordinator and a catch-up component behind existing WorkerStore/TelegramGateway protocols; keep worker lifecycle as facade. Separate GUI controllers from widget construction and trim planning from execution. Preserve existing behavior tests before moving code; composition is preferable to forced inheritance.

## Duplication assessment
There is already useful consolidation: shared atomic file helpers, worker store, protocol-based gateway, and common export_dict used by combined export. Head and tail backfill repeat download/batch/pause/persistence orchestration, but have different traversal and checkpoint semantics; blindly merging them risks corrupting progress. Extract a bounded history-batch iterator with explicit direction/checkpoint policy, then keep head/tail coordinators separate. The head/tail memory-policy divergence in A2 is the concrete motivation. No claim of a complete clone-detector scan is made.

# Portability and distribution audit

Scope: source review only; no macOS/Linux native runtime was available to this reviewer. Paths below are relative to `audit_source/chatradar`. P1 = release-blocking for requested distribution, P2 = important functional/coverage gap.

## Findings

### PORT-01 — P1: frozen executable autostart uses Python interpreter arguments
- Location: `src/chatimport/autostart.py:27,72-82`.
- Evidence: `task_command()` unconditionally returns the launcher plus `-m chatimport window --hidden`. `launcher()` assumes `sys.executable` is Python and searches for a sibling pythonw.exe. There is no frozen-build branch.
- Trigger: package the current CLI with PyInstaller and enable autostart. In a frozen process sys.executable points to the product executable; the task passes `-m` to Typer rather than a Python interpreter. It cannot launch the requested window. A coincidental pythonw.exe sibling also selects an unintended launcher.
- Consequence: installer may appear successful but background archive never starts after login.
- Fix: introduce a launch-command abstraction that explicitly distinguishes source/interpreter execution from packaged execution; packaged CLI receives `window --hidden` directly. A GUI-specific launcher may instead take only `--hidden`. Test both modes and execute the installed scheduled task on a clean Windows account.

### PORT-02 — P2: autostart is explicitly unsupported on macOS and Linux
- Location: `src/chatimport/autostart.py:68-69,174-175,199-200,215-216`; GUI system settings also branches on Windows.
- Evidence: `supported()` checks only win32; other platforms return UNSUPPORTED or raise.
- Trigger/impact: user installs on macOS/Linux and expects automatic continuous background archiving across login. This feature is unavailable. This is a product parity gap, not evidence that the whole application fails to run there.
- Fix: define an AutostartBackend protocol with status/enable/disable; retain Windows backend; implement per-user LaunchAgent on macOS and XDG desktop autostart for Linux desktop sessions. Avoid system-wide services and preserve explicit opt-in. Validate absolute packaged executable paths, upgrade cleanup, disable and uninstall.

### PORT-03 — P2: claimed cross-platform desktop support is not validated by CI
- Location: `.github/workflows/ci.yml:56` and `tests/unit/gui/conftest.py:7`.
- Evidence: matrix includes only ubuntu-latest/windows-latest; GUI tests default to offscreen. Native macOS, real tray, Wayland/X11 interactions and installer lifecycle are not exercised by this gate.
- Consequence: platform-specific Qt plugin loading, native dialogs, menu/tray and lifecycle regressions can ship while all current checks pass.
- Fix: add a macOS runner and define supported CPU/OS combinations; keep fast offscreen unit tests but add native desktop smoke checks for launch, close/reopen, missing tray fallback, shutdown, paths with spaces/Cyrillic, Unicode data, and autostart. Add clean-VM installed-artifact smoke testing. Do not describe an offscreen test pass as proof of desktop integration.

### PORT-04 — P1 for installer delivery: no executable/installer release pipeline
- Location: `pyproject.toml` ([build-system], [project.scripts]); `.github/workflows/ci.yml`; `src/chatimport/cli.py:61-64`; `src/chatimport/assets.py:9`.
- Evidence: project builds a Python distribution with uv_build and a console command; source archive has no bundler spec, installer recipe, signing/release job or dedicated double-click GUI entry. Existing CLI calls Typer with no automatic window command.
- Trigger/impact: building a wheel does not produce a standalone Windows installer. Naively freezing CLI then double-clicking it does not establish GUI startup; missing PNG/ICO assets or Qt plugins also remain unverified packaging risks (not observed failures).
- Fix: implement a dedicated GUI launcher, preserve a separate diagnostic CLI, add a reproducible bundler spec collecting assets and required Qt platform/image plugins, then wrap the tested bundle in a per-user installer. Validate resources from the installed bundle, not the source checkout.

### PORT-05 — P2: localized scheduler errors are misclassified as task absence
- Location: `src/chatimport/autostart.py:146-165,174-180,217-218`.
- Evidence: `_failure()` recognizes only English `access is denied`; `_is_absent()` treats every return code 1 without English `denied` as absence; `_text()` falls back to cp1252 after UTF-8/UTF-16. Russian or other localized OEM output does not satisfy English markers.
- Trigger: schtasks /Query reports localized access-denied/failure with return code 1. Code reports ABSENT, and disable then returns success without deleting the existing task.
- Consequence: misleading settings and an enabled startup task that user believes disabled.
- Fix: use Task Scheduler API/COM structured errors or a robust structured status result, distinguishing not-found HRESULT from access denied and other failure; decode output using actual Windows encoding only for display. Add non-English and generic-failure fixtures, and verify actual postcondition after disable.

## Concrete packaging roadmap

1. Establish support matrix first: Windows 11 x64, selected macOS versions/architectures and selected Linux distributions; derive minimums from the actual locked Python/Qt wheels. Do not promise every Linux distribution or architecture from a Python-only test pass.
2. Separate GUI and CLI entry points; fix PORT-01. Package only runtime files from an allowlist. Never include the archive `.env`, session/database data, developer caches or tests in a distributable.
3. Start with an onedir PyInstaller build, collecting `chatimport/assets` and verifying Qt platform plugins; alternatively evaluate official pyside6-deploy/Nuitka in a separate proof of concept. Pin bundler dependencies in a build environment separate from runtime. Build each OS/architecture natively: PyInstaller output is OS/Python-specific. Source: [PyInstaller operating mode](https://www.pyinstaller.org/en/stable/operating-mode.html). Qt offers [pyside6-deploy](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html).
4. Windows: wrap the verified directory bundle with a per-user installer (e.g. Inno Setup or WiX after selecting upgrade requirements). Include stable app identity/version, icon, shortcuts, uninstaller and optional autostart. Keep mutable files in platformdirs locations. Add Authenticode signing with timestamp through release credentials, verify signatures before publishing. This improves provenance; it does not guarantee antivirus/SmartScreen acceptance. Avoid packers/obfuscation and unnecessary elevation; submit actual false positives through vendors rather than advising exclusions.
5. macOS: build app bundle per supported architecture, sign using Developer ID, enable required hardened-runtime configuration and notarize/staple; test downloaded artifact with Gatekeeper. Apple procedure: [Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
6. Linux: select a support baseline and test its glibc/Qt dependencies; produce a tested distribution package or AppImage plus desktop entry/icon. Test GNOME/KDE, Wayland/X11 and no-tray behavior; bundle format alone is not universal compatibility.
7. Release acceptance: on clean machines with no Python installed, install as ordinary user, launch GUI, complete fake/offline startup, exercise import/search/export, enable/disable autostart, upgrade with retained settings, roll back when supported, uninstall without deleting archives by default. Explicitly test paths with spaces, Cyrillic, long names, read-only install directory and transient sharing violations.
8. Publish artifact hashes, dependency/license notices and reproducible build metadata. Verify PySide/Qt redistribution obligations for chosen licensing model before distribution. Keep signing credentials outside source and normal pull-request jobs.

## Positive evidence

platformdirs is used for platform-specific app/desktop folders; storage filenames use bounded ASCII slugs with IDs; Windows file sharing retries exist; startup task uses LeastPrivilege; Qt checks tray availability and run_gui displays the window when hidden startup has no tray. These are useful foundations. None substitutes for installed-artifact testing.

## Testing findings and acceptance plan

### TEST-01 — P2: GUI tests depend on the host language

Location: tests/unit/gui/conftest.py:66-78; src/chatimport/gui/settings.py:39-46; tests/unit/gui/pages_c/test_settings_telegram.py:294-298 (and appearance/config/page translation tests).

On this Russian Windows host, an empty GuiSettingsStore chooses Russian. Tests capture a button label as if it were English, then set Russian and require a change. The isolated Telegram suite reproduces 21 passes and 1 failure: both labels are already Russian. This is a test-isolation defect, not evidence that runtime language switching is broken. Fix the shared fixture to explicitly select English before building UiKit, with separately parametrized tests for OS-language detection and switching in both directions. Verify on English and Russian hosts; do not remove translation assertions.

### TEST-02 — P2: coverage is reported but not enforced

Location: pyproject.toml:109-122; .github/workflows/ci.yml:73-86; justfile cov/check recipes.

Coverage collects branches and publishes XML, but no fail_under or changed-code coverage policy exists. A feature can lose tests without failing the gate. Add a realistic initial branch/line baseline based on a clean complete run, increase it progressively, and require tests for changed critical paths. Measure backend and GUI separately to avoid a large well-covered subsystem hiding gaps elsewhere. A 100% number alone does not verify correctness: the combined-export failure reproduced despite the extensive suite.

### Additional required regression scenarios

- Export: unreadable part preserves previous good output; restore access and retry; cancellation and disk-full during publish.
- Media: neutral staged names, failures after partial writes, changed/unknown sizes, byte limits and cleanup; mark files before exposing them.
- Worker: overflow containing old edits/deletes; bounded-memory head history; crash/restart with incomplete head.
- Session: permission hardening failure on supported POSIX filesystem and deliberately unsupported mount; no silent downgrade.
- Desktop: actual native display, tray, shutdown with pending commands, keyboard navigation, locale, DPI and screen geometry. Existing QTest/offscreen tests are useful and should remain.
- Packaging: installed application without Python, native autostart execution and disable, upgrades, retained archives, uninstall, signed artifacts and bundled resources.

Integration tests currently use scripted Telegram gateways. This is appropriate for deterministic CI, but is not verification against a real Telegram account or network. Add a separately authorized opt-in contract smoke suite against a dedicated test account; never make production credentials a CI dependency. No claim of complete or exhaustive test coverage is justified by source inspection alone.

## Suggested implementation order

1. Fix A1 and add its regression test; preserve existing exports on every failed build.
2. Fix SEC-1/SEC-2 together with bounded staged downloads, and resolve SEC-3. Sanitize source delivery per SEC-4 without printing private values.
3. Restore a deterministic passing test gate, diagnose remaining GUI/search failures, and add missing branch assertions.
4. Bound head-backfill memory and make overflow completeness explicit; decide the empty-recheck verification policy.
5. Refactor only after behavior is protected. Prefer composition and existing protocols; inheritance is useful only for a real substitutable relationship. Do not split files solely to meet a line count.
6. Implement executable-aware launch and per-platform autostart, then native builds, signing, installers and clean-machine checks.

## Validation boundaries

No real-account acceptance test, antivirus scan of a final installer, native macOS/Linux run, notarization/signing, or installer upgrade/uninstall trial was performed. These need actual target artifacts/environments. Dependency-advisory scanning is not a guarantee that a dependency is safe. Static POSIX findings are not described as Windows reproductions. No application fixes or installer implementation were requested or made.

## Executed checks and measured results

| Check | Result |
|---|---|
| uv sync --locked | Successful; unchanged lockfile, Python 3.14.3, 36 installed packages |
| Ruff check | Passed |
| Ruff format --check | Passed; 433 files already formatted |
| Pyright strict | 0 errors, 430 warnings; warnings are recorded in pyright.log, many are test private-member accesses |
| Full pytest with fresh coverage | 4513 collected: 4454 passed, 56 failed, 3 skipped; JUnit duration 298.067 seconds |
| Repeat the 56 failures with locale LC_ALL=C | 56 passed in 9.45 seconds; no source changes |
| Coverage statements | 17866 / 17876 = 99.9441%; 10 missing lines |
| Coverage branches | 3339 / 3350 = 99.6716%; 11 missing branches |
| Coverage combined metric | 99.9011%; 1156 excluded lines configured by project |
| uv build | Wheel and source distribution built successfully; this is not an executable installer |
| chatimport --help | Passed |
| Assistant generated-file sync | Passed |
| Git-based language gate | Not runnable: snapshot lacks .git, git ls-files returns 128 |
| pip-audit runtime lock export | 16 dependency versions checked; no known vulnerabilities reported by the service at execution time |

The full run reached all 4513 tests, but pytest's final temporary-directory cleanup raised WinError 5 on the shared `pytest-current` link and suppressed its terminal summary. Counts above come from the saved JUnit XML, not from guessing progress dots. Coverage JSON was saved successfully. A subsequent run used a dedicated new --basetemp, avoiding that shared cleanup path. This cleanup issue is an audit-host/tooling limitation, not established application failure. Exact rerun script is audit_evidence/recheck_locale.py; it changes process locale only and runs --lf against this run's cached failures. The repeat confirms the locale-dependent failures; it is not a new full green run.

Remaining measured coverage gaps: gui/pages/data_merged.py:246; search.py:351-353 and branch at408; search_delegate.py:242-246; settings_appearance.py:150; additional branches in search_context.py:192,198, search_filters.py:86 and search_parts.py:145. Extend assertions around these paths only where they exercise meaningful behavior; do not add tests merely to execute a line. Failure details and all skipped tests are preserved in tests.xml. A high execution percentage is valuable but does not establish semantic completeness, thread-race safety or installed-desktop behavior.

### Reproduction evidence

- A1: audit_evidence/repro_A1.py and repro_A1_result.txt. Good export 1 record -> injected read failure publishes 0 -> restored read still skips with 0. Original part remains intact.
- SEC-1/2: security-repro.py and security-repro-results.json. Inert .exe-shaped attachment remains after simulated interrupted download without MOTW; 1,048,577 bytes saved against a 1,048,576-byte configured limit. Requires enabled document downloads; defaults disable media.
- PORT-01/05: audit_evidence/repro_portability.py and .log. A localized access-denied error is classified absent; explicit product executable is assigned Python -m arguments. This mocks scheduler output and inspects generated commands; no actual scheduled task was created.
- TEST-01: tests.xml, failures.txt, locale-check.xml and locale-check.log. All 56 failures disappear under explicit neutral locale.

The combined-export and media reproduction scripts were produced by the specialist reviewers and their outcomes reviewed alongside the source. The scheduler reproduction and primary checks were run by the lead reviewer. A2/A3 and POSIX hardening remain source-confirmed scenarios, not stress-tested production failures. A4 is deliberately classified as a conservative policy limitation rather than an accidental bug.

### Reproducibility and retained files

Main deliverable: AUDIT_REPORT.md. Supporting specialist notes: security-audit.md, architecture-audit.md, portability-audit.md. Audit logs and synthetic scripts are retained for verification. Build artifacts in audit_evidence/dist are Python packages only and are not approved desktop releases. The originally supplied archives, extracted source and .venv are retained; no pre-existing Python installation was removed. Real accounts were never accessed, autostart was not enabled, and no background ChatImport service was left running.
