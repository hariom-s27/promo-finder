"""check-gold: validate the gold label sheet against eval/gold_rubric.md (version 1).

Span rules (20-60 s, line boundaries, <=3 segments, order, overlap, unknown IDs) are NOT
re-implemented here: every span goes through checker.check_promo. Output never contains
script text, speaker names or rationale text, only gold_ids, codes, times and counts.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .checker import check_promo
from .labelling import BLOCKS, HELD_OUT_SPLIT, Split, compact_eps, fmt_ms
from .models import Line, Segment
from .tiou import set_tiou

HEADER = ["gold_id", "kind", "grade", "seg1_start", "seg1_end", "seg2_start", "seg2_end",
          "seg3_start", "seg3_end", "hook_type", "cliff_type", "neg_code", "rationale"]
HOOKS = {f"H{i}" for i in range(1, 10)}    # H10 (flash-forward) is not used for gold
CLIFFS = {f"C{i}" for i in range(1, 10)}
NEG_CODES = {f"N{i}" for i in range(1, 7)}
MAX_RATIONALE_WORDS = 20
POS_TIOU_LIMIT = 0.5
POS_RANGE = HELD_OUT_SPLIT.pos_range   # "about 15" positives (held-out; the fresh split has its own)
NEG_RANGE = HELD_OUT_SPLIT.neg_range   # "about 5" negatives
MIN_POS_PER_BLOCK = 3  # rubric: at least 3 per block
# Title/role words never treated as names (approved answer Q3, P01b).
NAME_SKIP_WORDS = frozenset({"mr", "mrs", "ms", "dr", "doctor", "nurse", "guard", "officer",
                             "mom", "dad", "boss", "man", "woman", "voice"})

ROW_CODES = (
    "BAD_COLUMNS", "MISSING_ID", "DUP_ID", "BAD_KIND", "BAD_GRADE", "BAD_HOOK", "BAD_CLIFF",
    "BAD_NEG_CODE", "MISSING_SEG1", "SEG_GAP", "INCOMPLETE_SEG", "NOT_HELD_OUT", "NOT_IN_SPLIT", "EP_SKIP",
    "POS_OVERLAP", "EMPTY_RATIONALE", "RATIONALE_TOO_LONG", "NAME_IN_RATIONALE",
)
ID_RE = re.compile(r"^E(\d{2})-L(\d{3})$")
_WORD = re.compile(r"[^\W\d_]+")


@dataclass
class RowResult:
    row_no: int
    gold_id: str
    kind: str
    errors: list[str] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    total_ms: int = 0
    first_ep: Optional[int] = None
    spans_ok: bool = False  # spans passed check_promo and the episode rules

    def err(self, code: str) -> None:
        if code not in self.errors:
            self.errors.append(code)


@dataclass
class GoldReport:
    rows: list[RowResult]
    file_errors: list[str]
    warnings: list[str]
    blocks: dict[str, dict[str, int]]
    totals: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.file_errors and all(not r.errors for r in self.rows)


# ---------- name guard ----------

def name_patterns(speakers: Iterable[str]) -> list[re.Pattern]:
    """Whole-word, case-insensitive patterns for each full speaker label and each 3+ letter word in it."""
    terms: set[str] = set()
    for label in speakers:
        if not label or not label.strip():
            continue
        norm = " ".join(label.split()).lower()
        if norm not in NAME_SKIP_WORDS:
            terms.add(norm)
        for w in _WORD.findall(norm):
            if len(w) >= 3 and w not in NAME_SKIP_WORDS:
                terms.add(w)
    pats = []
    for t in sorted(terms, key=lambda x: (-len(x), x)):
        body = r"\s+".join(re.escape(p) for p in t.split())
        pats.append(re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE))
    return pats


def has_name(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


# ---------- reading ----------

def read_sheet(path: Path) -> tuple[list[str], list[tuple[int, list[str]]], list[str]]:
    """Return (header, [(row_no, cells)], file_warnings). row_no = 1-based line number in the file."""
    raw = Path(path).read_bytes()
    warnings = []
    if raw.startswith(b"\xef\xbb\xbf"):
        warnings.append("WARNING file has a UTF-8 BOM (hash_eval add will refuse it; save as UTF-8 without BOM)")
    if b"\r\n" in raw:
        warnings.append("WARNING file has CRLF line endings (hash_eval add will refuse it; save with LF)")
    text = raw.decode("utf-8-sig")
    rdr = csv.reader(io.StringIO(text, newline=""))
    header: list[str] = []
    rows: list[tuple[int, list[str]]] = []
    for cells in rdr:
        if not header:
            header = cells
            continue
        if not cells or all(not c.strip() for c in cells):
            continue
        rows.append((rdr.line_num, cells))
    return header, rows, warnings


# ---------- checking ----------

def _ep_of(line_id: str) -> Optional[int]:
    m = ID_RE.match(line_id)
    return int(m.group(1)) if m else None


def _block_of(ep: Optional[int], blocks=BLOCKS) -> Optional[str]:
    for name, eps in blocks.items():
        if ep in eps:
            return name
    return None


def check_row(row_no: int, cells: list[str], index: Mapping[str, Line], patterns: list[re.Pattern], cfg=None,
              split: Split = HELD_OUT_SPLIT) -> RowResult:
    if len(cells) != len(HEADER):
        r = RowResult(row_no=row_no, gold_id=(cells[0].strip() if cells else ""), kind="?")
        r.err("BAD_COLUMNS")
        return r
    d = {k: v.strip() for k, v in zip(HEADER, cells)}
    r = RowResult(row_no=row_no, gold_id=d["gold_id"], kind=d["kind"])
    if not r.gold_id:
        r.err("MISSING_ID")

    if d["kind"] == "pos":
        if d["grade"] not in {"1", "2", "3"}:
            r.err("BAD_GRADE")
        if d["hook_type"] not in HOOKS:
            r.err("BAD_HOOK")
        if d["cliff_type"] not in CLIFFS:
            r.err("BAD_CLIFF")
        if d["neg_code"]:
            r.err("BAD_NEG_CODE")
    elif d["kind"] == "neg":
        if d["grade"] != "0":
            r.err("BAD_GRADE")
        if d["neg_code"] not in NEG_CODES:
            r.err("BAD_NEG_CODE")
        if d["hook_type"]:
            r.err("BAD_HOOK")
        if d["cliff_type"]:
            r.err("BAD_CLIFF")
    else:
        r.err("BAD_KIND")

    # segments: seg1 required; seg2 only if seg1; seg3 only if seg2; each pair complete
    pairs = [(d[f"seg{i}_start"], d[f"seg{i}_end"]) for i in (1, 2, 3)]
    present = [bool(a or b) for a, b in pairs]
    for a, b in pairs:
        if bool(a) != bool(b):
            r.err("INCOMPLETE_SEG")
    if not present[0]:
        r.err("MISSING_SEG1")
    if (present[1] and not present[0]) or (present[2] and not present[1]):
        r.err("SEG_GAP")
    spans = [(a, b) for a, b in pairs if a and b]
    if spans:
        r.first_ep = _ep_of(spans[0][0])
    structural = {"INCOMPLETE_SEG", "MISSING_SEG1", "SEG_GAP"}
    if spans and not structural & set(r.errors):
        for a, b in spans:
            for x in (a, b):
                ep = _ep_of(x)
                if ep is not None and ep not in split.episodes:
                    r.err(split.not_in_code)
        eps = [_ep_of(a) for a, _ in spans]
        for p, q in zip(eps, eps[1:]):
            if p is not None and q is not None and q > p + 1:
                r.err("EP_SKIP")
        ep_errors = bool({split.not_in_code, "EP_SKIP"} & set(r.errors))
        res = check_promo(spans, index, cfg)
        for code in res.errors:
            r.err(code)
        r.spans_ok = res.ok and not ep_errors
        r.segments = res.segments
        r.total_ms = res.total_ms

    rat = d["rationale"]
    if not rat:
        r.err("EMPTY_RATIONALE")
    else:
        if len(rat.split()) > MAX_RATIONALE_WORDS:
            r.err("RATIONALE_TOO_LONG")
        if has_name(rat, patterns):
            r.err("NAME_IN_RATIONALE")
    return r


def check_sheet(header: list[str], rows: list[tuple[int, list[str]]], index: Mapping[str, Line],
                speakers: Iterable[str], cfg=None, split: Split = HELD_OUT_SPLIT) -> GoldReport:
    if header != HEADER:
        return GoldReport(rows=[], file_errors=["BAD_HEADER (must equal eval/gold_template.csv exactly)"],
                          warnings=[], blocks={}, totals={})
    patterns = name_patterns(speakers)
    results = [check_row(n, cells, index, patterns, cfg, split) for n, cells in rows]

    counts: dict[str, int] = {}
    for r in results:
        if r.gold_id:
            counts[r.gold_id] = counts.get(r.gold_id, 0) + 1
    for r in results:
        if r.gold_id and counts[r.gold_id] > 1:
            r.err("DUP_ID")

    pos = [r for r in results if r.kind == "pos" and r.spans_ok]
    for i, a in enumerate(pos):
        for b in pos[i + 1:]:
            t = set_tiou([(s.ep, s.start_ms, s.end_ms) for s in a.segments],
                         [(s.ep, s.start_ms, s.end_ms) for s in b.segments])
            if t >= POS_TIOU_LIMIT:
                a.err(f"POS_OVERLAP({b.gold_id})")
                b.err(f"POS_OVERLAP({a.gold_id})")

    blocks = {name: {"pos": 0, "neg": 0} for name in split.blocks}
    blocks["other"] = {"pos": 0, "neg": 0}
    for r in results:
        if r.kind in ("pos", "neg"):
            blocks[_block_of(r.first_ep, split.blocks) or "other"][r.kind] += 1
    totals = {"pos": sum(b["pos"] for b in blocks.values()), "neg": sum(b["neg"] for b in blocks.values())}

    warnings: list[str] = []
    if results:
        for name in split.blocks:
            if blocks[name]["pos"] < MIN_POS_PER_BLOCK:
                warnings.append(f"WARNING block {name}: {blocks[name]['pos']} positives (< {MIN_POS_PER_BLOCK})")
            if blocks[name]["neg"] == 0:
                warnings.append(f"WARNING block {name}: 0 negatives")
        lo, hi = split.pos_range
        if not lo <= totals["pos"] <= hi:
            warnings.append(f"WARNING total positives {totals['pos']} outside {lo}-{hi} ({split.pos_target})")
        lo, hi = split.neg_range
        if not lo <= totals["neg"] <= hi:
            warnings.append(f"WARNING total negatives {totals['neg']} outside {lo}-{hi} ({split.neg_target})")
    return GoldReport(rows=results, file_errors=[], warnings=warnings, blocks=blocks, totals=totals)


# ---------- output ----------

def format_report(rep: GoldReport, file_warnings: list[str], split: Split = HELD_OUT_SPLIT) -> list[str]:
    out = list(file_warnings)
    if rep.file_errors:
        return out + [f"ERROR {e}" for e in rep.file_errors]
    if not rep.rows:
        return out + ["0 rows"]
    for r in rep.rows:
        gid = r.gold_id or f"(row {r.row_no})"
        status = "OK" if not r.errors else " ".join(r.errors)
        segs = "; ".join(f"E{s.ep:02d}  {fmt_ms(s.start_ms)}–{fmt_ms(s.end_ms)}" for s in r.segments)
        out.append(f"{gid}  {r.kind}  {status}  {r.total_ms / 1000:.1f}s  {segs}".rstrip())
    out.append(f"{len(rep.rows)} rows")
    for name, eps in split.blocks.items():
        b = rep.blocks[name]
        out.append(f"block {name} ({compact_eps(eps)}): pos={b['pos']} neg={b['neg']}")
    o = rep.blocks["other"]
    if o["pos"] or o["neg"]:
        out.append(f"block other ({split.other_label}): pos={o['pos']} neg={o['neg']}")
    out.append(f"total: pos={rep.totals['pos']} neg={rep.totals['neg']}")
    out.extend(rep.warnings)
    n_err = sum(1 for r in rep.rows if r.errors)
    out.append("check-gold: clean" if rep.ok else f"check-gold: {n_err} row(s) with errors")
    return out
