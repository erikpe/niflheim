from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePos:
    path: str
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class SourceSpan:
    start: SourcePos
    end: SourcePos