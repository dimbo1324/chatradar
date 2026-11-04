"""How a chat row reads: chip texts, tones and icons, ages and tooltips. Qt-free and table-testable.

Every function takes the row, the moment `now` and the language it needs, so the same code
feeds the table model, the delegate and the Overview.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chatimport.gui.format import (
    Freshness,
    FreshnessThresholds,
    classify,
    format_ago,
    format_exact,
    humanize_age,
)
from chatimport.gui.locales import chats as _chat_strings
from chatimport.gui.strings import translate
from chatimport.runtime import BackfillState

if TYPE_CHECKING:
    from datetime import datetime

    from chatimport.gui.models.snapshot import ChatRow
    from chatimport.gui.strings import Language
    from chatimport.gui.widgets.base import Tone

_ = _chat_strings
MONTH_FORMAT: Final = "%Y-%m"
MOMENT_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
NS: Final = "chats."


@dataclass(frozen=True, slots=True)
class ChipSpec:
    text: str
    tone: Tone
    icon: str


_HISTORY: Final[dict[BackfillState, tuple[Tone, str]]] = {
    BackfillState.RUNNING: ("live", "download"),
    BackfillState.WAITING: ("neutral", "hourglass"),
    BackfillState.PAUSED: ("muted", "pause"),
    BackfillState.DISK_STOPPED: ("warning", "disk"),
    BackfillState.RETRYING: ("warning", "refresh"),
    BackfillState.DONE: ("success", "check-circle"),
    BackfillState.NO_ACCESS: ("danger", "ban"),
    BackfillState.IDLE: ("muted", "clock"),
}

_STATUS: Final[dict[str, tuple[Tone, str]]] = {
    "no_access": ("danger", "ban"),
    "error": ("danger", "alert"),
    "paused": ("muted", "pause"),
    "live": ("live", "radio"),
    "starting": ("info", "activity"),
}

STATUS_ORDER: Final = ("error", "no_access", "starting", "live", "paused")


def status_kind(row: ChatRow) -> str:
    if not row.has_access:
        return "no_access"
    if row.error is not None:
        return "error"
    if row.is_paused:
        return "paused"
    if row.phase == "live":
        return "live"
    return "starting"


def status_chip(row: ChatRow, language: Language) -> ChipSpec:
    kind = status_kind(row)
    tone, icon = _STATUS[kind]
    return ChipSpec(translate(language, f"{NS}status.{kind}"), tone, icon)


def history_chip(row: ChatRow, language: Language) -> ChipSpec:
    state = row.backfill.state
    tone, icon = _HISTORY[state]
    return ChipSpec(translate(language, f"{NS}history.{state.value}"), tone, icon)


def countdown_text(seconds: float, language: Language) -> str:
    whole = max(math.ceil(seconds), 0)
    if whole < 5:
        return f"{whole} {translate(language, 'time.s')}"
    return humanize_age(whole, language)


def history_detail(row: ChatRow, now: datetime, language: Language) -> str:
    info = row.backfill
    if info.state is BackfillState.RETRYING and info.retry_at is not None:
        left = (info.retry_at - now).total_seconds()
        if left <= 0:
            return translate(language, f"{NS}retry_now")
        return translate(language, f"{NS}retry_in", age=countdown_text(left, language))
    if info.state is BackfillState.RUNNING and info.month:
        return info.month
    return ""


def age_seconds(row: ChatRow, now: datetime) -> float | None:
    if row.newest_date is None:
        return None
    return max((now - row.newest_date).total_seconds(), 0.0)


def freshness_of(row: ChatRow, now: datetime, thresholds: FreshnessThresholds) -> Freshness:
    return classify(age_seconds(row, now), thresholds)


def last_message_text(row: ChatRow, now: datetime, absolute: bool, language: Language) -> str:
    if row.newest_date is None:
        return translate(language, "time.never")
    if absolute:
        return row.newest_date.astimezone().strftime(MOMENT_FORMAT)
    return format_ago(age_seconds(row, now), language)


def last_message_tooltip(row: ChatRow, now: datetime, language: Language) -> str:
    if row.newest_date is None:
        lines = [translate(language, f"{NS}tip.no_messages")]
    else:
        lines = [
            format_exact(row.newest_date),
            format_ago(age_seconds(row, now), language),
        ]
    if row.last_contact_at is not None:
        contact = max((now - row.last_contact_at).total_seconds(), 0.0)
        lines.append(translate(language, f"{NS}tip.contact", age=format_ago(contact, language)))
    lines.append(translate(language, f"{NS}tip.toggle"))
    return "\n".join(lines)


def history_tooltip(row: ChatRow, now: datetime, language: Language) -> str:
    info = row.backfill
    lines = [translate(language, f"{NS}history_tip.{info.state.value}")]
    if info.month:
        lines.append(translate(language, f"{NS}tip.month", month=info.month))
    if info.progress is not None and info.state is not BackfillState.DONE:
        lines.append(translate(language, f"{NS}tip.approx"))
    if info.retry_at is not None and info.state is BackfillState.RETRYING:
        lines.append(format_exact(info.retry_at))
    if info.detail:
        lines.append(translate(language, f"{NS}tip.detail", detail=info.detail))
    return "\n".join(lines)


def span_text(row: ChatRow) -> str:
    if row.oldest_date is None or row.newest_date is None:
        return "—"
    first = row.oldest_date.astimezone().strftime(MONTH_FORMAT)
    last = row.newest_date.astimezone().strftime(MONTH_FORMAT)
    return first if first == last else f"{first} → {last}"
