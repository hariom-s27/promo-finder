"""Data models shared by the parser, validator, checker and later phases."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Kind = Literal["dialogue", "action", "camera", "sfx", "other"]
KINDS: tuple[str, ...] = ("dialogue", "action", "camera", "sfx", "other")


def line_id(ep: int, idx: int) -> str:
    """Stable line ID: 2-digit episode, 3-digit 1-based line index in file order."""
    return f"E{ep:02d}-L{idx:03d}"


class ParseWarning(BaseModel):
    """A non-fatal problem. Never contains script text."""

    code: str
    ep: Optional[int] = None
    line_no: Optional[int] = None  # 1-based line number in the source file
    reason: str = ""


class Line(BaseModel):
    id: str
    ep: int
    idx: int
    scene: int
    kind: Kind
    speaker: Optional[str] = None
    emotion: Optional[str] = None
    ext: Optional[str] = None
    text: str
    start_ms: int
    end_ms: int
    src_line: int = 0  # file line number of the block label

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class Scene(BaseModel):
    number: int
    heading: str = ""
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    line_ids: list[str] = Field(default_factory=list)


class Episode(BaseModel):
    ep: int
    source_file: str
    source_id: str = ""
    header_ep: Optional[int] = None
    logline: str = ""
    continuity: str = ""
    scenes: list[Scene] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    duration_ms: int = 0
    warnings: list[ParseWarning] = Field(default_factory=list)


class Segment(BaseModel):
    ep: int
    start_ms: int
    end_ms: int
    line_ids: list[str]

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class Promo(BaseModel):
    segments: list[Segment]
    total_ms: int


class CheckResult(BaseModel):
    ok: bool
    segments: list[Segment] = Field(default_factory=list)
    total_ms: int = 0
    errors: list[str] = Field(default_factory=list)
