from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

from chatimport.config import Config, ConfigError, load_config
from chatimport.gui.pages import settings_config as sc
from chatimport.gui.widgets.switch import Switch

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.gui.kit import UiKit


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def card_of(kit: UiKit, config_file: Path, key: str) -> sc.ConfigCard:
    card = next(c for c in sc.build_config_cards(kit, config_file) if c.key == key)
    card.load(Config())
    return card


def test_make_editor_kinds(kit: UiKit) -> None:
    flag = sc.make_editor(kit, sc.FieldSpec("a", "b", "bool"))
    assert isinstance(flag.widget, Switch)
    flag.write(True)
    assert flag.read() is True

    number = sc.make_editor(kit, sc.FieldSpec("a", "b", "int", 2, 9))
    number.write(5)
    assert number.read() == 5
    assert isinstance(number.widget, QSpinBox)

    decimal = sc.make_editor(kit, sc.FieldSpec("a", "b", "float", 0.5, 9))
    decimal.write(1.5)
    assert decimal.read() == 1.5
    assert isinstance(decimal.widget, QDoubleSpinBox)

    clock = sc.make_editor(kit, sc.FieldSpec("a", "b", "time"))
    clock.write("06:30")
    assert clock.read() == "06:30"

    types = sc.make_editor(kit, sc.FieldSpec("a", "b", "media_types"))
    seen: list[None] = []
    types.changed.connect(lambda: seen.append(None))
    types.write(["photo", "audio"])
    assert types.read() == ["photo", "audio"]
    assert seen


def test_field_spec_text_key() -> None:
    assert sc.FieldSpec("live", "x", "int").text_key == "settings.f.live.x"


def test_load_shows_config_and_is_clean(kit: UiKit, config_file: Path) -> None:
    card = card_of(kit, config_file, "collection")
    assert not card.dirty
    assert not card._save.isEnabled()
    editor = card._editors["live", "flush_every_messages"]
    assert editor.read() == Config().live.flush_every_messages


def test_editing_enables_save_and_shows_status(kit: UiKit, config_file: Path) -> None:
    card = card_of(kit, config_file, "collection")
    card.show_message("danger", "old")
    spin = card._editors["live", "flush_every_messages"].widget
    assert isinstance(spin, QSpinBox)
    spin.setValue(spin.value() + 1)
    assert card.dirty
    assert card._save.isEnabled()
    assert card._status.text() != ""
    assert card.message.isHidden()


def test_save_writes_only_changed_keys(kit: UiKit, config_file: Path) -> None:
    card = card_of(kit, config_file, "collection")
    saved: list[None] = []
    card.saved.connect(lambda: saved.append(None))
    spin = card._editors["live", "flush_every_messages"].widget
    assert isinstance(spin, QSpinBox)
    spin.setValue(7)
    card.save()
    assert load_config(config_file).live.flush_every_messages == 7
    text = config_file.read_text(encoding="utf-8")
    assert "flush_every_messages" in text
    assert "batch_size" not in text
    assert saved == [None]
    assert not card.dirty
    assert not card.message.isHidden()
    assert not card._save.isEnabled()


def test_every_card_saves_a_change(kit: UiKit, config_file: Path) -> None:
    recheck = card_of(kit, config_file, "recheck")
    recheck._editors["recheck", "daily_at"].write("03:15")
    recheck._editors["recheck", "enabled"].write(False)
    recheck.save()
    media = card_of(kit, config_file, "media")
    media._editors["media", "types"].write(["photo"])
    media.save()
    privacy = card_of(kit, config_file, "privacy")
    privacy._editors["output", "include_raw"].write(True)
    privacy.save()
    loaded = load_config(config_file)
    assert loaded.recheck.daily_at == "03:15"
    assert not loaded.recheck.enabled
    assert list(loaded.media.types) == ["photo"]
    assert loaded.output.include_raw


def test_disk_order_is_validated_before_writing(kit: UiKit, config_file: Path) -> None:
    card = card_of(kit, config_file, "disk")
    low = card._editors["disk", "low_watermark_gb"].widget
    high = card._editors["disk", "high_watermark_gb"].widget
    assert isinstance(low, QSpinBox)
    assert isinstance(high, QSpinBox)
    low.setValue(20)
    high.setValue(10)
    saved: list[None] = []
    card.saved.connect(lambda: saved.append(None))
    card.save()
    assert not card.message.isHidden()
    assert not config_file.exists()
    assert not saved
    high.setValue(30)
    card.save()
    assert load_config(config_file).disk.high_watermark_gb == 30
    assert saved == [None]


def test_order_ignores_non_integers() -> None:
    assert (
        sc._order({("disk", "low_watermark_gb"): 1.0, ("disk", "high_watermark_gb"): 0.5}) is None
    )
    assert sc._order({("disk", "low_watermark_gb"): 1, ("disk", "high_watermark_gb"): 2}) is None
    assert (
        sc._order({("disk", "low_watermark_gb"): 2, ("disk", "high_watermark_gb"): 2})
        == "settings.err.disk_order"
    )


@pytest.mark.parametrize("error", [ConfigError("bad"), OSError("disk")])
def test_write_failures_become_messages(
    kit: UiKit, config_file: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def refuse(*_: object) -> None:
        raise error

    monkeypatch.setattr(sc, "update_config", refuse)
    card = card_of(kit, config_file, "privacy")
    card._editors["output", "include_raw"].write(True)
    saved: list[None] = []
    card.saved.connect(lambda: saved.append(None))
    card.save()
    assert not card.message.isHidden()
    assert card.dirty
    assert not saved


def test_retranslate_follows_the_language(kit: UiKit, config_file: Path) -> None:
    card = card_of(kit, config_file, "media")
    english = card._save.text()
    kit.language.set_language("ru")
    assert card._save.text() != english
    kit.language.set_language("en")
    assert card._save.text() == english
