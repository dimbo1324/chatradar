"""Strings of the "coming soon" pages (namespace `placeholder`)."""

# ruff: noqa: RUF001 - Cyrillic letters look like Latin ones, which is the point here
from __future__ import annotations

from typing import Final

from chatimport.gui.strings import register_strings

EN: Final[dict[str, str | tuple[str, ...]]] = {
    "title": "{page} is coming soon",
    "log.text": "A live view of what the service is doing, filterable by chat and severity.",
    "data.text": "Disk usage per chat, clean-up, exports and integrity checks in one place.",
    "settings.text": "Language, freshness colours, autostart, the data folder and Telegram login.",
    "subtitle": "Arrives in a later version of the window",
}

RU: Final[dict[str, str | tuple[str, ...]]] = {
    "title": "Раздел «{page}» скоро появится",
    "log.text": "Живая картина того, что делает служба, с фильтрами по чату и важности.",
    "data.text": "Место на диске по чатам, очистка, экспорт и проверка целостности в одном месте.",
    "settings.text": "Язык, цвета свежести, автозапуск, папка данных и вход в Telegram.",
    "subtitle": "Появится в одной из следующих версий окна",
}

register_strings("placeholder", EN, RU)
