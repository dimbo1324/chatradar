"""`chatradar lexicon`: look at the learning lexicon and make term decisions by hand.

Registered in `cli.py`. Thin wrappers over the lexicon repository; the revision moves in
the repository, and the next `process` run applies it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any

import typer

from chatradar.config import get_settings
from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconTerm,
    TermDecision,
    TermSource,
    TermStatus,
)
from chatradar.pipeline.lexicons import fold
from chatradar.services.container import open_runtime

if TYPE_CHECKING:
    from collections.abc import Coroutine


HUMAN = "human"


class Order(StrEnum):
    SCORE = "score"
    OCCURRENCES = "occurrences"
    RECENT = "recent"


lexicon_app = typer.Typer(no_args_is_help=True, help="The learning lexicon.")

KindArg = Annotated[LexiconKind, typer.Argument(help="Term kind.")]
TermArg = Annotated[str, typer.Argument(help="The phrase.")]
LangOpt = Annotated[str, typer.Option("--lang", help="Language, or 'any'.")]
NoteOpt = Annotated[str | None, typer.Option("--note", help="Why.")]


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _line(term: LexiconTerm) -> str:
    return (
        f"{term.kind.value:<16} {term.lang:<4} {term.status.value:<9} "
        f"{term.source.value:<6} score={term.score:7.2f} n={term.occurrences:<5} "
        f"chats={term.chats:<3} authors={term.authors:<3} {term.term}"
    )


@lexicon_app.command("list")
def list_terms(
    kind: Annotated[LexiconKind | None, typer.Option("--kind")] = None,
    status: Annotated[TermStatus | None, typer.Option("--status")] = None,
    lang: Annotated[str | None, typer.Option("--lang")] = None,
    order: Annotated[Order, typer.Option("--order")] = Order.SCORE,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 50,
) -> None:
    """Terms, filtered and ordered."""

    async def go() -> None:
        async with open_runtime(get_settings()) as rt:
            page = await rt.lexicon.list_terms(
                kind=kind,
                status=status,
                lang=lang,
                order=order.value,
                limit=limit,
            )
        for term in page.items:
            typer.echo(_line(term))
        typer.echo(f"{len(page.items)} of {page.total}")

    _run(go())


@lexicon_app.command()
def stats() -> None:
    """Revision, applied revisions and term counts."""

    async def go() -> None:
        async with open_runtime(get_settings()) as rt:
            summary = await rt.lexicon.summary()
        typer.echo(f"revision: {summary.revision}")
        for stage, applied in summary.applied.items():
            typer.echo(f"applied {stage}: {applied}")
        typer.echo(f"pending apply: {'yes' if summary.pending_apply else 'no'}")
        typer.echo(f"labels: {summary.labels}")
        for status, count in summary.by_status.items():
            typer.echo(f"{status}: {count}")
        for kind, counts in summary.by_kind.items():
            parts = ", ".join(f"{status}={count}" for status, count in counts.items() if count)
            typer.echo(f"  {kind}: {parts or '-'}")

    _run(go())


def _decide(
    decision: TermDecision, kind: LexiconKind, term: str, lang: str, note: str | None
) -> None:
    async def go() -> None:
        async with open_runtime(get_settings()) as rt:
            try:
                decided = await rt.lexicon.decide(
                    kind, lang, term.strip(), decision, by=HUMAN, note=note
                )
            except KeyError:
                typer.secho(f"unknown term: {kind.value}/{lang}/{term}", fg="red", err=True)
                raise typer.Exit(code=1) from None
            revision = await rt.lexicon.revision()
        typer.echo(f"{decided.status.value}: {decided.kind.value}/{decided.lang}/{decided.term}")
        typer.echo(f"revision: {revision}")

    _run(go())


def _as_stored(term: str) -> str:
    """New terms are stored folded, except symbols such as "+1" that fold to nothing."""
    stripped = term.strip()
    return fold(stripped) or stripped


@lexicon_app.command()
def accept(kind: KindArg, term: TermArg, lang: LangOpt = "any", note: NoteOpt = None) -> None:
    """Make a term active."""
    _decide(TermDecision.ACCEPT, kind, term, lang, note)


@lexicon_app.command()
def reject(kind: KindArg, term: TermArg, lang: LangOpt = "any", note: NoteOpt = None) -> None:
    """Reject a term; it is not proposed again."""
    _decide(TermDecision.REJECT, kind, term, lang, note)


@lexicon_app.command()
def reset(kind: KindArg, term: TermArg, lang: LangOpt = "any", note: NoteOpt = None) -> None:
    """Send a term back to the candidates."""
    _decide(TermDecision.RESET, kind, term, lang, note)


@lexicon_app.command()
def add(kind: KindArg, term: TermArg, lang: LangOpt = "any") -> None:
    """Add an active term by hand."""

    async def go() -> None:
        new = LexiconTerm(
            kind=kind,
            lang=lang,
            term=_as_stored(term),
            status=TermStatus.ACTIVE,
            source=TermSource.HUMAN,
            decided_at=datetime.now(UTC),
            decided_by=HUMAN,
        )
        async with open_runtime(get_settings()) as rt:
            stored = await rt.lexicon.add_term(new)
            revision = await rt.lexicon.revision()
        typer.echo(f"{stored.status.value}: {stored.kind.value}/{stored.lang}/{stored.term}")
        typer.echo(f"revision: {revision}")

    _run(go())
