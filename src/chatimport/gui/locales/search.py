"""Strings of the Search page (namespace `find`; `search.*` already belongs to the search box)."""

# ruff: noqa: RUF001 - Cyrillic letters look like Latin ones, which is the point here
from __future__ import annotations

from typing import Final

from chatimport.gui.strings import register_strings

EN: Final[dict[str, str | tuple[str, ...]]] = {
    "subtitle": "Find any stored message as you type",
    "placeholder": "Search all messages (Ctrl+F)",
    "count": ("{n} result", "{n} results"),
    "count.none": "No results",
    "count.partial": "{shown} loaded",
    "next": "Next result (Enter)",
    "previous": "Previous result (Shift+Enter)",
    "edited": "edited",
    "edited_tip": "The text was edited after it was sent",
    "chats.all": "All chats",
    "chats.some": ("{n} chat", "{n} chats"),
    "chats.tip": "Choose the chats to search in",
    "chats.menu_all": "All chats",
    "chats.none": "No chats in the index yet",
    "period.label": "Period",
    "period.any": "Any time",
    "period.today": "Today",
    "period.week": "7 days",
    "period.month": "30 days",
    "period.year": "Year",
    "status.ready": ("{n} message in the index", "{n} messages in the index"),
    "status.building": "Indexing {percent}",
    "status.building_tip": "{indexed} of {total} messages are indexed so far",
    "status.disabled": "Search is off",
    "status.missing": "No search index yet",
    "status.unknown": "Checking the index",
    "state.idle.title": "Search your whole archive",
    "state.idle.text": (
        "Type a word or a part of one. Case, accents and the difference between yo and ye "
        "are ignored, and results appear while you type."
    ),
    "state.building.title": "Search is still indexing",
    "state.building.text": "Results cover the part of the archive that is already indexed.",
    "state.short.text": "One or two letters can match a lot. Add a letter to narrow it down.",
    "state.disabled.title": "Search is off",
    "state.disabled.text": (
        "The search index is not available on this computer, so messages cannot be searched. "
        "The archive itself is not affected."
    ),
    "state.missing.title": "The search index is not built yet",
    "state.missing.text": (
        "The index file is missing. The service builds it from your archive in the background "
        "and this page starts working by itself when it is ready."
    ),
    "state.nothing.title": "Nothing found",
    "state.nothing.text": (
        "No stored message contains this text. Check the spelling or widen the filters."
    ),
    "state.error.title": "The search failed",
    "state.error.text": "The index could not be read. Try again in a moment.",
    "state.loading": "Searching",
    "ctx.title": "Context",
    "ctx.close": "Close the context",
    "ctx.loading": "Loading the neighbouring messages",
    "ctx.missing": "The neighbouring messages are no longer available.",
    "ctx.hint": "Press Enter or double-click a result to see the messages around it.",
    "ctx.open": "Open in Telegram",
    "ctx.open_none": "This message has no link",
    "ctx.copy_link": "Copy link",
    "ctx.copy_text": "Copy text",
    "ctx.target": "Found message",
    "toast.link_copied": "The link is copied.",
    "toast.text_copied": "The message text is copied.",
    "toast.open_failed": "Could not open the link.",
    "toast.failed": "The search could not be completed.",
}

RU: Final[dict[str, str | tuple[str, ...]]] = {
    "subtitle": "Поиск по всем сохранённым сообщениям прямо во время набора",
    "placeholder": "Искать по всем сообщениям (Ctrl+F)",
    "count": ("{n} результат", "{n} результата", "{n} результатов"),
    "count.none": "Нет результатов",
    "count.partial": "Загружено {shown}",
    "next": "Следующий результат (Enter)",
    "previous": "Предыдущий результат (Shift+Enter)",
    "edited": "изменено",
    "edited_tip": "Текст изменили после отправки",
    "chats.all": "Все чаты",
    "chats.some": ("{n} чат", "{n} чата", "{n} чатов"),
    "chats.tip": "Выберите чаты для поиска",
    "chats.menu_all": "Все чаты",
    "chats.none": "В индексе пока нет чатов",
    "period.label": "Период",
    "period.any": "За всё время",
    "period.today": "Сегодня",
    "period.week": "7 дней",
    "period.month": "30 дней",
    "period.year": "Год",
    "status.ready": (
        "В индексе {n} сообщение",
        "В индексе {n} сообщения",
        "В индексе {n} сообщений",
    ),
    "status.building": "Индексация {percent}",
    "status.building_tip": "Проиндексировано {indexed} из {total} сообщений",
    "status.disabled": "Поиск выключен",
    "status.missing": "Индекса поиска пока нет",
    "status.unknown": "Проверяем индекс",
    "state.idle.title": "Поиск по всему архиву",
    "state.idle.text": (
        "Введите слово или его часть. Регистр, ударения и разница между «ё» и «е» не важны, "
        "результаты появляются по мере набора."
    ),
    "state.building.title": "Поиск ещё индексирует архив",
    "state.building.text": "Результаты охватывают ту часть архива, которая уже проиндексирована.",
    "state.short.text": "Одна-две буквы совпадают слишком часто. Добавьте ещё, чтобы сузить поиск.",
    "state.disabled.title": "Поиск выключен",
    "state.disabled.text": (
        "Индекс поиска недоступен на этом компьютере, поэтому по сообщениям искать нельзя. "
        "Сам архив это не затрагивает."
    ),
    "state.missing.title": "Индекс поиска ещё не построен",
    "state.missing.text": (
        "Файл индекса не найден. Служба строит его из вашего архива в фоне, и эта страница "
        "заработает сама, когда он будет готов."
    ),
    "state.nothing.title": "Ничего не найдено",
    "state.nothing.text": (
        "Ни одно сохранённое сообщение не содержит этот текст. "
        "Проверьте написание или расширьте фильтры."
    ),
    "state.error.title": "Не удалось выполнить поиск",
    "state.error.text": "Индекс не удалось прочитать. Попробуйте ещё раз через минуту.",
    "state.loading": "Идёт поиск",
    "ctx.title": "Контекст",
    "ctx.close": "Закрыть контекст",
    "ctx.loading": "Загружаем соседние сообщения",
    "ctx.missing": "Соседние сообщения больше недоступны.",
    "ctx.hint": (
        "Нажмите Enter или дважды щёлкните результат, чтобы увидеть сообщения вокруг него."
    ),
    "ctx.open": "Открыть в Telegram",
    "ctx.open_none": "У этого сообщения нет ссылки",
    "ctx.copy_link": "Копировать ссылку",
    "ctx.copy_text": "Копировать текст",
    "ctx.target": "Найденное сообщение",
    "toast.link_copied": "Ссылка скопирована.",
    "toast.text_copied": "Текст сообщения скопирован.",
    "toast.open_failed": "Не удалось открыть ссылку.",
    "toast.failed": "Не удалось завершить поиск.",
}

register_strings("find", EN, RU)
