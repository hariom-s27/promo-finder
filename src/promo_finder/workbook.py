"""Excel labelling aids; the existing check-gold remains the authority."""

from __future__ import annotations

import csv
from pathlib import Path, PurePosixPath

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from .labelling import BLOCKS, HELD_OUT, fmt_ms
from .models import Episode

LABEL_ROWS = 60
HELPERS = ("seg1_s", "seg2_s", "seg3_s", "total_s", "length_check", "words")
EPISODE_HEADER = ("line_id", "start", "end", "kind", "speaker", "emotion", "text")
README_LINES = (
    "Read the episode sheets, then fill one candidate per row in LABELS.",
    "Columns A-M are the gold CSV fields; keep their headers unchanged.",
    "Use a unique gold_id and choose kind pos or neg.",
    "For pos choose grade 1-3, hook H1-H9 and cliff C1-C9; leave neg_code blank.",
    "For neg choose grade 0 and neg_code N1-N6; leave hook and cliff blank.",
    "Enter each segment's first and last line IDs using the dropdowns.",
    "Fill segment 1 first; use at most three segments in order.",
    "Use only held-out episodes; check-gold checks all span rules.",
    "Write a short rationale of at most 20 words, without character names.",
    "Column N onward are helpers and are not exported.",
    "Helpers measure first-line start to last-line end; aim for 20-60 seconds total.",
    "Excel calculates helpers when opened; check-gold is the final authority.",
    "Save this workbook as .xlsx; never save as CSV from Excel.",
    "Run python -m promo_finder export-gold to make and check the CSV.",
)

_BLUE = PatternFill("solid", fgColor="D9EAF7")
_GREY = PatternFill("solid", fgColor="E7E6E6")
_RED = PatternFill("solid", fgColor="FFC7CE")
_GREEN = PatternFill("solid", fgColor="C6EFCE")


class WorkbookError(ValueError):
    """A safe error message that never includes workbook cell values."""


def template_header(root: Path) -> list[str]:
    with (root / "eval" / "gold_template.csv").open(encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def _header(sheet, row: int, helper_from: int | None = None) -> None:
    for cell in sheet[row]:
        cell.font = Font(bold=True)
        cell.fill = _GREY if helper_from and cell.column >= helper_from else _BLUE
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def _named_list(wb: Workbook, name: str, sheet: str, col: str, end: int) -> None:
    wb.defined_names.add(DefinedName(name, attr_text=f"'{sheet}'!${col}$2:${col}${end}"))


def _validation(sheet, name: str, columns: str) -> None:
    dv = DataValidation(type="list", formula1=f"={name}", allow_blank=True,
                        errorStyle="stop", showErrorMessage=True, showDropDown=False,
                        errorTitle="Choose a listed value", error="Use the dropdown or leave blank.")
    sheet.add_data_validation(dv)
    for col in columns.split():
        dv.add(f"{col}2:{col}{LABEL_ROWS + 1}")


def _labels(wb: Workbook, header: list[str]) -> None:
    sheet = wb["LABELS"]
    sheet.append(header + [f"{name} (helper)" for name in HELPERS])
    _header(sheet, 1, helper_from=14)
    sheet.row_dimensions[1].height = 32
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = f"A1:S{LABEL_ROWS + 1}"
    for col in "ABCDEFGHIJKL":
        sheet.column_dimensions[col].width = 18
    sheet.column_dimensions["M"].width = 55
    for col in "NOPQRS":
        sheet.column_dimensions[col].width = 22
    for r in range(2, LABEL_ROWS + 2):
        for target, start, end in (("N", "D", "E"), ("O", "F", "G"), ("P", "H", "I")):
            sheet[f"{target}{r}"] = (
                f'=IF(AND({start}{r}="",{end}{r}=""),"",IFERROR('
                f'(INDEX(LINES!$D:$D,MATCH({end}{r},LINES!$A:$A,0))-'
                f'INDEX(LINES!$C:$C,MATCH({start}{r},LINES!$A:$A,0)))/1000,"bad ID"))'
            )
            sheet[f"{target}{r}"].number_format = "0.0"
        sheet[f"Q{r}"] = f"=SUM(N{r}:P{r})"
        sheet[f"Q{r}"].number_format = "0.0"
        sheet[f"R{r}"] = (
            f'=IF(COUNTA(D{r}:I{r})=0,"",IF(COUNTIF(N{r}:P{r},"bad ID")>0,"bad ID",'
            f'IF(Q{r}<20,"too short",IF(Q{r}>60,"too long","ok"))))'
        )
        words = f'TRIM(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE(M{r},CHAR(9)," "),CHAR(10)," "),CHAR(13)," "))'
        sheet[f"S{r}"] = f'=IF(LEN({words})=0,0,LEN({words})-LEN(SUBSTITUTE({words}," ",""))+1)'
        sheet[f"M{r}"].alignment = Alignment(wrap_text=True, vertical="top")
    for name, cols in (("KindCodes", "B"), ("GradeCodes", "C"), ("HookCodes", "J"),
                       ("CliffCodes", "K"), ("NegCodes", "L"), ("LineIDs", "D E F G H I")):
        _validation(sheet, name, cols)
    for value, fill in (("too short", _RED), ("too long", _RED), ("ok", _GREEN)):
        sheet.conditional_formatting.add(
            f"R2:R{LABEL_ROWS + 1}", CellIsRule(operator="equal", formula=[f'"{value}"'], fill=fill))
    sheet.conditional_formatting.add(
        f"S2:S{LABEL_ROWS + 1}", CellIsRule(operator="greaterThan", formula=["20"], fill=_RED))


def write_workbook(episodes: list[Episode], out: Path, header: list[str],
                   force: bool = False) -> tuple[int, int, int]:
    """Write once without reading cells back. Return episode, line and scene counts."""
    if out.exists() and not force:
        raise FileExistsError("workbook already exists; use --force only to replace it deliberately")
    by_ep = {e.ep: e for e in episodes}
    missing = [n for n in HELD_OUT if n not in by_ep]
    if missing:
        raise WorkbookError("missing held-out episodes: " + ",".join(f"E{n:02d}" for n in missing))
    wb = Workbook()
    wb.active.title = "README"
    for instruction in README_LINES:
        wb["README"].append([instruction])
    wb["README"].column_dimensions["A"].width = 110
    wb.create_sheet("LABELS")
    lines = scenes = 0
    for n in HELD_OUT:
        ep = by_ep[n]
        sheet = wb.create_sheet(f"E{n:02d}")
        block = next(key for key, eps in BLOCKS.items() if n in eps)
        sheet.append([f"E{n:02d} \u2014 duration {fmt_ms(ep.duration_ms)} \u2014 block {block}"])
        sheet.merge_cells("A1:G1")
        sheet["A1"].font = Font(bold=True)
        sheet.append(EPISODE_HEADER)
        _header(sheet, 2)
        sheet.freeze_panes = "A3"
        previous_scene = None
        for line in ep.lines:
            if line.scene != previous_scene:
                previous_scene = line.scene
                sheet.append([f"--- scene {line.scene} ---"])
                for cell in sheet[sheet.max_row]:
                    cell.fill = _GREY
                scenes += 1
            values = (line.id, fmt_ms(line.start_ms), fmt_ms(line.end_ms), line.kind,
                      line.speaker if line.kind == "dialogue" else None, line.emotion, line.text)
            # Force strings to text, including source text beginning with '='.
            # Never inspect or print these cell values after writing them.
            row = sheet.max_row + 1
            for col, value in enumerate(values, 1):
                if value is not None:
                    cell = sheet.cell(row, col, value)
                    cell.data_type = "s"
                    cell.alignment = Alignment(wrap_text=col == 7, vertical="top")
            lines += 1
        sheet.auto_filter.ref = f"A2:G{sheet.max_row}"
        for col, width in (("A", 24), ("B", 12), ("C", 12), ("D", 14),
                           ("E", 24), ("F", 22), ("G", 100)):
            sheet.column_dimensions[col].width = width
    lookup = wb.create_sheet("LINES")
    lookup.append(["line_id", "ep", "start_ms", "end_ms"])
    for n in HELD_OUT:
        for line in by_ep[n].lines:
            lookup.append([line.id, line.ep, line.start_ms, line.end_ms])
    lookup.sheet_state = "hidden"
    _named_list(wb, "LineIDs", "LINES", "A", max(2, lines + 1))
    codes = wb.create_sheet("CODES")
    for col, (heading, name, values) in enumerate((
        ("kind", "KindCodes", ("pos", "neg")),
        ("grade", "GradeCodes", tuple(range(4))),
        ("hook", "HookCodes", tuple(f"H{i}" for i in range(1, 10))),
        ("cliff", "CliffCodes", tuple(f"C{i}" for i in range(1, 10))),
        ("neg_code", "NegCodes", tuple(f"N{i}" for i in range(1, 7))),
    ), 1):
        codes.cell(1, col, heading)
        for r, value in enumerate(values, 2):
            codes.cell(r, col, value)
        _named_list(wb, name, "CODES", chr(64 + col), len(values) + 1)
    codes.sheet_state = "hidden"
    _labels(wb, header)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against a file appearing during generation.
    with out.open("wb" if force else "xb") as f:
        wb.save(f)
    wb.close()
    return len(HELD_OUT), lines, scenes


def is_sealed(out: Path, hashes: Path) -> bool:
    """Match the target basename against file rows in the hash ledger."""
    for line in hashes.read_text(encoding="utf-8").splitlines():
        cells = line.split("|")
        if line.lstrip().startswith("|") and len(cells) >= 3:
            recorded = cells[1].strip().strip("`").replace("\\", "/")
            if PurePosixPath(recorded).name.casefold() == out.name.casefold():
                return True
    return False


def _clean(value, field: str) -> str:
    text = "" if value is None else str(value).strip()
    if field == "kind":
        return text.lower()
    if field.startswith("seg") or field in {"hook_type", "cliff_type", "neg_code"}:
        return text.upper()
    if field == "grade" and text:
        from decimal import Decimal, InvalidOperation

        try:
            number = Decimal(text)
            if number.is_finite() and number == number.to_integral_value():
                return str(int(number))
        except InvalidOperation:
            pass
    return text


def export_labels(xlsx: Path, out: Path, header: list[str], hashes: Path) -> None:
    if is_sealed(out, hashes):
        raise WorkbookError("target name is sealed in eval/HASHES.md; export to a new version name "
                            "(e.g. --out eval/gold_v2.csv)")
    if xlsx.resolve() == out.resolve():
        raise WorkbookError("CSV output must differ from the input workbook")
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    try:
        if "LABELS" not in wb.sheetnames:
            raise WorkbookError("workbook must contain a LABELS sheet")
        sheet = wb["LABELS"]
        rows = sheet.iter_rows(min_row=1, max_col=len(header), values_only=True)
        if list(next(rows, ())) != header:
            raise WorkbookError("LABELS columns A-M must equal the template header")
        cleaned = []
        for row in rows:
            values = [_clean(value, field) for value, field in zip(row, header)]
            if any(values):
                cleaned.append(values)
    finally:
        wb.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(cleaned)
