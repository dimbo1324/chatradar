"""Learning commands: `eval` and `mine`. The lead registers `learning_app`'s commands in
`cli.py` at top level; the logic lives in `services/evaluation.py` and `services/learning.py`."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — Typer reads annotations at runtime
from typing import TYPE_CHECKING, Annotated, Protocol, cast

import typer

from chatradar.config import get_settings
from chatradar.domain.ports import MessageRepository, MessageScanner, QueryRepository
from chatradar.pipeline.registry import stage_versions
from chatradar.services.container import open_runtime
from chatradar.services.evaluation import evaluate_labels, evaluate_truth_files, format_report
from chatradar.services.learning import mine_candidates

if TYPE_CHECKING:
    from chatradar.domain.ports import LabelRepository, LexiconRepository


class _Repo(MessageRepository, QueryRepository, MessageScanner, Protocol): ...


class _LearningRuntime(Protocol):
    @property
    def repo(self) -> _Repo: ...
    @property
    def lexicon(self) -> LexiconRepository: ...
    @property
    def labels(self) -> LabelRepository: ...


learning_app = typer.Typer(no_args_is_help=True, help="Learning lexicon: evaluation and mining.")


def _fail(message: str) -> typer.Exit:
    typer.secho(message, fg="red", err=True)
    return typer.Exit(code=2)


@learning_app.command("eval")
def eval_command(
    truth: Annotated[
        list[Path] | None,
        typer.Option(
            "--truth", exists=True, dir_okay=False, help="Truth file(s) from the generator."
        ),
    ] = None,
    labels: Annotated[bool, typer.Option("--labels", help="Evaluate the human labels.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Precision, recall and F1 of the noise filter and the question detector."""
    if not truth and not labels:
        raise _fail("Give --truth PATH (repeatable) or --labels.")

    async def go() -> str:
        async with open_runtime(get_settings()) as opened:
            rt = cast("_LearningRuntime", opened)
            versions = dict(stage_versions())
            revision = await rt.lexicon.revision()
            if labels:
                report = await evaluate_labels(
                    rt.labels, rt.repo, stage_versions=versions, lexicon_revision=revision
                )
            else:
                report = await evaluate_truth_files(
                    truth or [],
                    queries=rt.repo,
                    messages=rt.repo,
                    stage_versions=versions,
                    lexicon_revision=revision,
                )
        return report.model_dump_json(indent=2) if as_json else format_report(report)

    typer.echo(asyncio.run(go()))


@learning_app.command("mine")
def mine_command() -> None:
    """Propose lexicon candidates from the stored messages (nothing becomes active)."""
    settings = get_settings()

    async def go() -> str:
        async with open_runtime(settings) as opened:
            rt = cast("_LearningRuntime", opened)
            report = await mine_candidates(
                settings.learning,
                scanner=rt.repo,
                lexicon=rt.lexicon,
                labels=rt.labels,
                now=datetime.now(UTC),
            )
        by_kind = ", ".join(f"{kind}={n}" for kind, n in report.by_kind.items()) or "-"
        return (
            f"scanned {report.messages} messages in {report.duration_ms} ms: "
            f"{report.new_candidates} new candidates ({by_kind}), "
            f"{report.refreshed} refreshed, {report.dormant} put to sleep"
        )

    typer.echo(asyncio.run(go()))
