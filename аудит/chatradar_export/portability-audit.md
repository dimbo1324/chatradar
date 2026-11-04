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

## TEST-LOCALE — P2: GUI test fixtures depend on the workstation locale

- Location: `tests/unit/gui/conftest.py:65-75` (empty store and kit fixture), `src/chatimport/gui/settings.py:39-46` (correctly locale-sensitive product default); examples `tests/unit/gui/pages_c/test_settings_telegram.py:293-298` and `tests/unit/gui/search/test_search_page.py` English literal expectations.
- Confirmed dynamically on this Russian Windows host: Telegram module 21 passed/1 failed; appearance/config/page modules 31 passed/3 failed; search-page module 18 passed/13 failed. Every failure in those isolated runs compares Russian UI text with an expected English initial state, or switches to Russian when already Russian. Evidence: `audit_evidence/telegram-target-clean.log`, `settings-extra.log`, `search-page-target.log`.
- Consequence: cross-platform/localized developer runs fail for environmental reasons, obscuring real defects. This is a test determinism defect, not proof that localization itself is broken.
- Fix: explicitly create English GuiSettings in shared ordinary-test fixtures before constructing UiKit. Keep separate parametrized tests mocking locale detection for en/ru/unknown; translation-switch tests should set and assert initial locale before switching, and restore global language state in teardown.
- Execution note: unique pytest `--basetemp` directories avoided a separate Windows PermissionError when pytest cleaned the shared `pytest-current` junction. Do not confuse that test-runner cleanup issue with a product error. No hang reproduced in these isolated modules and no test source was changed.
