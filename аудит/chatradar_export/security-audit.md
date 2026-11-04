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
