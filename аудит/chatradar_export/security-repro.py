import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "audit_source" / "chatradar"))
from tests.fakes import FakeGateway
from tests.unit.maintenance.test_media import drop_file, media_msg, saved, setup

from chatimport.config import MediaConfig, parse_config
from chatimport.records import MediaInfo

logging.disable(logging.CRITICAL)


async def main():
    results = {"default_media_enabled": MediaConfig().enabled, "default_types": MediaConfig().types}
    cfg = parse_config({"media": {"enabled": True, "types": ["document"], "max_file_mb": 1}})
    results["document_configuration_accepted"] = cfg.media.types == ("document",)
    with tempfile.TemporaryDirectory(prefix="chatradar-security-repro-") as temp:

        class Interrupted(FakeGateway):
            async def download_media(self, chat_id, msg_id, target_dir):
                drop_file(target_dir, "synthetic.exe", b"INERT TEST DATA - NOT EXECUTABLE")
                raise ConnectionError("synthetic interruption after file creation")

        dl, chat, _, _, _ = setup(
            Path(temp) / "interrupted",
            [[media_msg(1, MediaInfo(type="document", size=30))]],
            types=("document",),
        )
        dl._gateway = Interrupted()
        await dl._download_one(chat)
        leftover = chat.folder / "media" / "2026-09" / "synthetic.exe"
        results["SEC1_original_suffix_left_after_failure"] = leftover.exists()
        results["SEC1_mark_of_web_present"] = Path(str(leftover) + ":Zone.Identifier").exists()

        class Oversize(FakeGateway):
            async def download_media(self, chat_id, msg_id, target_dir):
                return drop_file(target_dir, "synthetic.txt", b"x" * (1024 * 1024 + 1))

        dl, chat, _, _, _ = setup(
            Path(temp) / "oversize",
            [[media_msg(2, MediaInfo(type="document", size=None))]],
            types=("document",),
            max_file_mb=1,
        )
        dl._gateway = Oversize()
        await dl._download_one(chat)
        (record,) = saved(chat)
        results["SEC2_configured_limit_bytes"] = 1024 * 1024
        results["SEC2_saved_bytes"] = (chat.folder / record.file).stat().st_size
    print(json.dumps(results, indent=2))


asyncio.run(main())
