from __future__ import annotations

from chatimport import assets


def test_bundled_icons_exist_and_sit_in_the_assets_folder() -> None:
    assert assets.ICON_PNG.parent == assets.ASSETS_DIR
    assert assets.ICON_ICO.parent == assets.ASSETS_DIR
    assert assets.ICON_PNG.is_file()
    assert assets.ICON_ICO.is_file()
