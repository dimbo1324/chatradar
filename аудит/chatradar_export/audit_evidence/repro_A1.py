import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from chatimport import merged_export as m
from chatimport.records import MessageRecord, json_line_bytes
from chatimport.storage.state import ChunkInfo, new_state, save_state

now = datetime(2026, 11, 4, tzinfo=UTC)
with TemporaryDirectory(prefix="chatradar-audit-A1-") as tmp:
    root = Path(tmp)
    folder = root / "synthetic_123"
    folder.mkdir()
    part = folder / "2026-11_001.jsonl"
    data = json_line_bytes(
        MessageRecord(chat_id=123, msg_id=1, date=now, fetched_at=now, text="synthetic").to_dict()
    )
    part.write_bytes(data)
    state = replace(
        new_state(123, "synthetic", None, now),
        last_id=1,
        chunks={"2026-11_001": ChunkInfo(1, 1, 1, len(data))},
    )
    save_state(folder, state)
    good = m.build_merged(root, now=now)
    assert good.records == 1
    with patch.object(
        m, "iter_part_records", side_effect=PermissionError("synthetic temporary sharing failure")
    ):
        bad = m.build_merged(root, now=now, force=True)
    restored = m.build_merged(root, now=now)
    result = {
        "initial_records": good.records,
        "records_after_injected_read_failure": bad.records,
        "retry_after_restored_read_skipped": restored.skipped,
        "retry_records": restored.records,
        "source_part_still_exists": part.exists(),
    }
    assert bad.records == 0 and restored.skipped and restored.records == 0
    print(json.dumps(result, indent=2))
