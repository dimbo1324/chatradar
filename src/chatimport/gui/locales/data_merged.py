"""Strings of the Combined file card on the Data page (namespace `data`, keys `merged.*`)."""

# ruff: noqa: RUF001 - Cyrillic letters look like Latin ones, which is the point here
from __future__ import annotations

from typing import Final

from chatimport.gui.strings import register_strings

EN: Final[dict[str, str | tuple[str, ...]]] = {
    "merged.title": "Combined file",
    "merged.lede": "One file with the messages of every chat, sorted by time, kept next to the "
    "archive. It is a copy: the chat folders stay the source of truth.",
    "merged.enabled": "Keep the combined file up to date",
    "merged.enabled_hint": "Rebuilt in the background, only when some chat has changed.",
    "merged.format": "Format",
    "merged.format.json": "JSON",
    "merged.format.json_tip": "One array, like the single-chat export",
    "merged.format.jsonl": "JSONL",
    "merged.format.jsonl_tip": "One message per line, easier for big archives",
    "merged.names": "Include sender names",
    "merged.names_hint": "Off by default. Names and the original Telegram data are personal data.",
    "merged.names_warning": "The file will contain people's names. Do not share or publish it.",
    "merged.state": "Status",
    "merged.state.off": "Switched off",
    "merged.state.on": "Switched on",
    "merged.state.building": "Building now...",
    "merged.last": "Last build",
    "merged.last.never": "Not built yet",
    "merged.last.value": "{moment} ({ago})",
    "merged.size": "Contents",
    "merged.size.value": "{records} · {size}",
    "merged.records": ("{n} record", "{n} records"),
    "merged.path": "File",
    "merged.copy": "Copy the path",
    "merged.show": "Show in folder",
    "merged.copied": "Path copied",
    "merged.build": "Build now",
    "merged.building": "Building...",
    "merged.saved": "Saved",
    "merged.saved_later": "Saved. It applies when the service starts.",
    "merged.save_failed": "The setting could not be saved.",
    "merged.toast.ok": "Combined file is ready: {records}",
    "merged.toast.failed": "The combined file was not built.",
}

RU: Final[dict[str, str | tuple[str, ...]]] = {
    "merged.title": "Общий файл",
    "merged.lede": "Один файл с сообщениями всех чатов в порядке времени, рядом с архивом. "
    "Это копия: главными остаются папки чатов.",
    "merged.enabled": "Поддерживать общий файл актуальным",
    "merged.enabled_hint": "Пересобирается в фоне и только если какой-то чат изменился.",
    "merged.format": "Формат",
    "merged.format.json": "JSON",
    "merged.format.json_tip": "Один массив, как в экспорте одного чата",
    "merged.format.jsonl": "JSONL",
    "merged.format.jsonl_tip": "Одно сообщение в строке, удобнее для больших архивов",
    "merged.names": "Включить имена авторов",
    "merged.names_hint": "По умолчанию выключено. Имена и исходные данные Telegram — "
    "персональные данные.",
    "merged.names_warning": "В файле будут имена людей. Не публикуйте и не передавайте его.",
    "merged.state": "Состояние",
    "merged.state.off": "Выключено",
    "merged.state.on": "Включено",
    "merged.state.building": "Собирается...",
    "merged.last": "Последняя сборка",
    "merged.last.never": "Ещё не собирался",
    "merged.last.value": "{moment} ({ago})",
    "merged.size": "Содержимое",
    "merged.size.value": "{records} · {size}",
    "merged.records": ("{n} запись", "{n} записи", "{n} записей"),
    "merged.path": "Файл",
    "merged.copy": "Скопировать путь",
    "merged.show": "Показать в папке",
    "merged.copied": "Путь скопирован",
    "merged.build": "Собрать сейчас",
    "merged.building": "Собираем...",
    "merged.saved": "Сохранено",
    "merged.saved_later": "Сохранено. Вступит в силу при запуске службы.",
    "merged.save_failed": "Не удалось сохранить настройку.",
    "merged.toast.ok": "Общий файл готов: {records}",
    "merged.toast.failed": "Общий файл не собран.",
}

register_strings("data", EN, RU)
