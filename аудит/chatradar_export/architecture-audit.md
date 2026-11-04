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

