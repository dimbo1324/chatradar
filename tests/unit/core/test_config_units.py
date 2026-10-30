from __future__ import annotations

from chatimport.config import GIB, MIB, DiskConfig, MediaConfig, OutputConfig, parse_config


def test_units_are_binary() -> None:
    assert MIB == 1024 * 1024
    assert GIB == 1024 * MIB


def test_derived_byte_sizes_follow_the_configured_values() -> None:
    config = parse_config(
        {
            "output": {"max_chunk_mb": 3},
            "disk": {"low_watermark_gb": 2, "high_watermark_gb": 4},
            "media": {"max_file_mb": 7},
        }
    )
    assert config.output.max_chunk_bytes == 3 * MIB
    assert config.disk.low_bytes == 2 * GIB
    assert config.disk.high_bytes == 4 * GIB
    assert config.media.max_file_bytes == 7 * MIB


def test_derived_sizes_of_the_defaults() -> None:
    assert OutputConfig().max_chunk_bytes == 20 * MIB
    assert (DiskConfig().low_bytes, DiskConfig().high_bytes) == (15 * GIB, 17 * GIB)
    assert MediaConfig().max_file_bytes == 50 * MIB
