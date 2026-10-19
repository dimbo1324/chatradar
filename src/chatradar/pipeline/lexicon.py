"""The lexicon as the rule stages see it: an immutable value built from the ACTIVE terms.

The built-in word lists in `resources/lexicons/*.txt` are the seed (`seed_terms`); at run
time the database is the source (`load_lexicon`) and the files are only a fallback for code
that has no repository, such as unit tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING

from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconSnapshot,
    LexiconTerm,
    TermSource,
    TermStatus,
)
from chatradar.pipeline.lexicons import fold

if TYPE_CHECKING:
    from collections.abc import Mapping

    from chatradar.domain.ports import LexiconRepository

SEED_REVISION = 0
"""Revision of a lexicon read from the files: it has no database behind it."""

LANG_ANY = "any"
_LANG_COMMENT = re.compile(r"^#\s*(ru|es|en)\s*$")


@dataclass(frozen=True)
class Lexicon:
    """ACTIVE terms per kind: as written (symbols such as "+1") and folded for matching."""

    revision: int
    raw_terms: Mapping[LexiconKind, frozenset[str]]
    folded_terms: Mapping[LexiconKind, frozenset[str]]

    @classmethod
    def from_snapshot(cls, snapshot: LexiconSnapshot) -> Lexicon:
        raw: dict[LexiconKind, frozenset[str]] = {}
        folded: dict[LexiconKind, frozenset[str]] = {}
        for kind in LexiconKind:
            terms = frozenset(t.strip() for t in snapshot.terms(kind) if t.strip())
            raw[kind] = terms
            folded[kind] = frozenset(f for t in terms if (f := fold(t)))
        return cls(revision=snapshot.revision, raw_terms=raw, folded_terms=folded)

    @classmethod
    def from_seed(cls) -> Lexicon:
        return _seed_lexicon()

    def raw(self, kind: LexiconKind) -> frozenset[str]:
        return self.raw_terms.get(kind, frozenset())

    def folded(self, kind: LexiconKind) -> frozenset[str]:
        return self.folded_terms.get(kind, frozenset())


@cache
def _seed_lexicon() -> Lexicon:
    entries: dict[str, tuple[str, ...]] = {}
    for term in seed_terms():
        entries[term.kind.value] = (*entries.get(term.kind.value, ()), term.term)
    return Lexicon.from_snapshot(LexiconSnapshot(revision=SEED_REVISION, entries=entries))


def seed_terms() -> list[LexiconTerm]:
    """Every entry of the built-in files as an ACTIVE seed term.

    A comment line `# ru`, `# es` or `# en` sets the language of the entries below it;
    before the first such line (and in files without them) the language is `any`.
    """
    found: dict[tuple[LexiconKind, str, str], LexiconTerm] = {}
    for kind in LexiconKind:
        resource = files("chatradar").joinpath("resources", "lexicons", f"{kind.value}.txt")
        lang = LANG_ANY
        for line in resource.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if match := _LANG_COMMENT.match(stripped):
                    lang = match.group(1)
                continue
            term = LexiconTerm(
                kind=kind,
                lang=lang,
                term=stripped,
                status=TermStatus.ACTIVE,
                source=TermSource.SEED,
            )
            found.setdefault(term.key, term)
    return list(found.values())


async def load_lexicon(repo: LexiconRepository | None) -> Lexicon:
    """One snapshot of the ACTIVE terms; the seed files when there is no repository."""
    if repo is None:
        return Lexicon.from_seed()
    return Lexicon.from_snapshot(await repo.snapshot())
