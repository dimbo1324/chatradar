"""Strings of the Overview page and its event feed (namespace `overview`)."""

# ruff: noqa: RUF001 - Cyrillic letters look like Latin ones, which is the point here
from __future__ import annotations

from typing import Final

from chatimport.gui.strings import register_strings

EN: Final[dict[str, str | tuple[str, ...]]] = {
    "subtitle": "The archive at a glance",
    "stat.chats": "Chats",
    "stat.chats_hint": "{live} live now",
    "stat.messages": "Messages saved",
    "stat.messages_new": (
        "{n} new message since the window opened",
        "{n} new messages since the window opened",
    ),
    "stat.messages_none": "No new messages since the window opened",
    "stat.disk": "Free disk space",
    "stat.disk_hint": "Archive size: {size}",
    "stat.disk_unknown": "Unknown",
    "stat.backfill": "History download",
    "backfill.running": "Downloading",
    "backfill.done": "All downloaded",
    "backfill.idle": "Nothing running",
    "backfill.hint_running": "{title}",
    "backfill.hint_waiting": "{title} - {n} waiting",
    "backfill.waiting": ("{n} chat waiting in the queue", "{n} chats waiting in the queue"),
    "backfill.hint_done": "Every enabled chat is complete",
    "backfill.hint_idle": "The queue is empty for now",
    "stat.quiet": "Quietest chat",
    "quiet.none": "No data",
    "quiet.hint_none": "No chat has stored messages yet",
    "stat.service": "Service",
    "service.starting": "Starting",
    "service.running": "Running",
    "service.stopping": "Stopping",
    "service.stopped": "Stopped",
    "service.hint": "Up {up} - updated {updated}",
    "service.hint_stopped": "Last update {updated}",
    "callout.errors": "Service problem",
    "callout.cloud.title": "The data folder is synced to the cloud",
    "callout.cloud.text": (
        "The archive holds sender names, so it should stay on this computer. "
        "Move it with `chatimport set-root`."
    ),
    "callout.disk.title": "Free disk space is running low",
    "callout.disk.text": (
        "Only {free} left; the reserve is {limit}. Downloads stop and the oldest history "
        "may be trimmed to protect the disk."
    ),
    "callout.join.title": ("{n} library chat was not found", "{n} library chats were not found"),
    "callout.join.text": (
        "The account has to join the chat first; the service never joins by itself."
    ),
    "feed.title": "Recent events",
    "feed.empty.title": "No events yet",
    "feed.empty.text": "Changes in your chats show up here while the window is open.",
    "feed.live": "{title} is live",
    "feed.paused": "{title} was paused",
    "feed.no_access": "Access to {title} was lost",
    "feed.backfill_running": "History download started: {title}",
    "feed.backfill_done": "History of {title} fully downloaded",
    "feed.backfill_paused": "History download paused: {title}",
    "feed.backfill_disk": "History download stopped, low disk: {title}",
    "feed.backfill_retrying": "History download failed, retrying: {title}",
    "feed.chat_added": "{title} added to the archive",
    "feed.chat_removed": "{title} removed from the archive",
    "feed.error": "A service error appeared",
    "feed.error_resolve": "A library chat could not be found",
    "feed.error_cleared": "Service errors cleared",
}

RU: Final[dict[str, str | tuple[str, ...]]] = {
    "subtitle": "Архив одним взглядом",
    "stat.chats": "Чаты",
    "stat.chats_hint": "{live} в эфире",
    "stat.messages": "Сообщений сохранено",
    "stat.messages_new": (
        "{n} новое сообщение с открытия окна",
        "{n} новых сообщения с открытия окна",
        "{n} новых сообщений с открытия окна",
    ),
    "stat.messages_none": "Новых сообщений с открытия окна нет",
    "stat.disk": "Свободно на диске",
    "stat.disk_hint": "Размер архива: {size}",
    "stat.disk_unknown": "Неизвестно",
    "stat.backfill": "Загрузка истории",
    "backfill.running": "Скачивается",
    "backfill.done": "Всё скачано",
    "backfill.idle": "Ничего не идёт",
    "backfill.hint_running": "{title}",
    "backfill.hint_waiting": "{title} - в очереди: {n}",
    "backfill.waiting": (
        "{n} чат ждёт в очереди",
        "{n} чата ждут в очереди",
        "{n} чатов ждут в очереди",
    ),
    "backfill.hint_done": "Все включённые чаты скачаны полностью",
    "backfill.hint_idle": "Очередь пока пуста",
    "stat.quiet": "Самый тихий чат",
    "quiet.none": "Нет данных",
    "quiet.hint_none": "Ни в одном чате пока нет сохранённых сообщений",
    "stat.service": "Служба",
    "service.starting": "Запуск",
    "service.running": "Работает",
    "service.stopping": "Остановка",
    "service.stopped": "Остановлена",
    "service.hint": "Работает {up} - обновлено {updated}",
    "service.hint_stopped": "Последнее обновление {updated}",
    "callout.errors": "Проблема в службе",
    "callout.cloud.title": "Папка с данными синхронизируется с облаком",
    "callout.cloud.text": (
        "В архиве есть имена отправителей, поэтому он должен оставаться на этом компьютере. "
        "Перенесите его командой `chatimport set-root`."
    ),
    "callout.disk.title": "Свободного места на диске остаётся мало",
    "callout.disk.text": (
        "Осталось только {free}, резерв - {limit}. Загрузка остановится, а самая старая "
        "история может быть удалена, чтобы защитить диск."
    ),
    "callout.join.title": (
        "{n} чат из библиотеки не найден",
        "{n} чата из библиотеки не найдены",
        "{n} чатов из библиотеки не найдены",
    ),
    "callout.join.text": ("Аккаунт должен сначала вступить в чат: служба сама никуда не вступает."),
    "feed.title": "Последние события",
    "feed.empty.title": "Событий пока нет",
    "feed.empty.text": "Изменения в чатах появятся здесь, пока окно открыто.",
    "feed.live": "{title}: идёт приём в реальном времени",
    "feed.paused": "{title}: поставлен на паузу",
    "feed.no_access": "Потерян доступ к чату {title}",
    "feed.backfill_running": "Началась загрузка истории: {title}",
    "feed.backfill_done": "История чата {title} скачана полностью",
    "feed.backfill_paused": "Загрузка истории на паузе: {title}",
    "feed.backfill_disk": "Загрузка истории остановлена, мало места: {title}",
    "feed.backfill_retrying": "Загрузка истории не удалась, повтор: {title}",
    "feed.chat_added": "{title}: добавлен в архив",
    "feed.chat_removed": "{title}: убран из архива",
    "feed.error": "Появилась ошибка службы",
    "feed.error_resolve": "Чат из библиотеки не найден",
    "feed.error_cleared": "Ошибки службы исчезли",
}

register_strings("overview", EN, RU)
