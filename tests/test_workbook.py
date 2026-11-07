"""Workbook structure and CLI tests using invented episodes only."""

from pathlib import Path
from shutil import copyfile

import pytest
from openpyxl import load_workbook

from promo_finder import cli
from promo_finder.labelling import HELD_OUT
from promo_finder.parser import parse_dir
from promo_finder.workbook import template_header, write_workbook

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def episodes(fixtures_dir, episode_factory):
    normal, _ = parse_dir(fixtures_dir / "normal")
    return normal + [episode_factory(ep, [(0, 25000)]) for ep in HELD_OUT if ep not in (1, 2)]


@pytest.fixture
def generated(tmp_path, episodes):
    out = tmp_path / "workbook.xlsx"
    counts = write_workbook(episodes, out, template_header(ROOT))
    wb = load_workbook(out)
    yield wb, counts
    wb.close()


def test_sheet_order_hidden_lookup_and_counts(generated, episodes):
    wb, counts = generated
    assert wb.sheetnames == ["README", "LABELS"] + [f"E{ep:02d}" for ep in HELD_OUT] + ["LINES", "CODES"]
    assert wb["LINES"].sheet_state == wb["CODES"].sheet_state == "hidden"
    assert counts == (16, 34, 17)
    assert wb["LINES"].max_row == counts[1] + 1
    assert wb["LINES"].max_column == 4
    assert list(wb["LINES"].values)[1:] == [
        (ln.id, ln.ep, ln.start_ms, ln.end_ms) for ep in episodes for ln in ep.lines]
    assert 10 <= wb["README"].max_row <= 15


def test_episode_layout_without_reading_script_cells(generated):
    wb, _ = generated
    sheet = wb["E01"]
    assert sheet.max_row == 17  # title + header + two scenes + thirteen lines
    assert sheet.freeze_panes == "A3"
    assert sheet.auto_filter.ref == "A2:G17"
    assert [c.value for c in sheet[2]] == ["line_id", "start", "end", "kind", "speaker", "emotion", "text"]
    assert sheet["B4"].value == "00:00.0" and sheet["B4"].data_type == "s"
    assert sheet["G4"].alignment.wrap_text
    assert sheet["A3"].fill.fgColor.rgb == "00E7E6E6"
    assert sheet.column_dimensions["G"].width >= 80


def test_labels_header_helpers_and_formula_endpoints(generated):
    wb, _ = generated
    sheet = wb["LABELS"]
    assert [sheet.cell(1, c).value for c in range(1, 14)] == template_header(ROOT)
    assert sheet.max_row == 61 and sheet.max_column == 19
    assert sheet.freeze_panes == "B2"
    assert all("helper" in sheet.cell(1, c).value for c in range(14, 20))
    assert sheet["N1"].fill.fgColor.rgb == "00E7E6E6"
    for r in (2, 61):
        for col, start, end in (("N", "D", "E"), ("O", "F", "G"), ("P", "H", "I")):
            formula = sheet[f"{col}{r}"].value
            assert "IFERROR" in formula and '"bad ID"' in formula and "XLOOKUP" not in formula
            assert f"INDEX(LINES!$D:$D,MATCH({end}{r},LINES!$A:$A,0))" in formula
            assert f"INDEX(LINES!$C:$C,MATCH({start}{r},LINES!$A:$A,0))" in formula
            assert f'AND({start}{r}="",{end}{r}="")' in formula and "/1000" in formula
        assert sheet[f"Q{r}"].value == f"=SUM(N{r}:P{r})"
        assert f'COUNTA(D{r}:I{r})=0,""' in sheet[f"R{r}"].value
        assert f'Q{r}<20,"too short"' in sheet[f"R{r}"].value
        assert f'Q{r}>60,"too long","ok"' in sheet[f"R{r}"].value
        assert f"SUBSTITUTE(M{r},CHAR(9)" in sheet[f"S{r}"].value
        assert "CHAR(10)" in sheet[f"S{r}"].value and "CHAR(13)" in sheet[f"S{r}"].value
    assert all(sheet.cell(r, c).value is None for r in range(2, 62) for c in range(1, 14))


def test_validation_lists_and_conditional_formatting(generated):
    wb, _ = generated
    sheet = wb["LABELS"]
    validations = {dv.formula1: dv for dv in sheet.data_validations.dataValidation}
    expected = {"KindCodes": "B", "GradeCodes": "C", "HookCodes": "J", "CliffCodes": "K",
                "NegCodes": "L", "LineIDs": "D E F G H I"}
    for name, columns in expected.items():
        dv = validations[f"={name}"]
        assert dv.type == "list" and dv.errorStyle == "stop" and dv.showErrorMessage
        assert dv.allow_blank and not dv.showDropDown
        assert str(dv.sqref) == " ".join(f"{col}2:{col}61" for col in columns.split())
        defined = wb.defined_names[name]
        assert "LINES" in defined.attr_text if name == "LineIDs" else "CODES" in defined.attr_text
    assert list(wb["CODES"].values)[:3] == [
        ("kind", "grade", "hook", "cliff", "neg_code"),
        ("pos", 0, "H1", "C1", "N1"), ("neg", 1, "H2", "C2", "N2")]
    rules = {str(key.sqref): value for key, value in sheet.conditional_formatting._cf_rules.items()}
    assert [r.formula for r in rules["R2:R61"]] == [['"too short"'], ['"too long"'], ['"ok"']]
    assert rules["R2:R61"][0].dxf.fill.fgColor.rgb == "00FFC7CE"
    assert rules["R2:R61"][2].dxf.fill.fgColor.rgb == "00C6EFCE"
    assert rules["S2:S61"][0].formula == ["20"]


def test_refuses_overwrite_and_force_replaces(tmp_path, episodes):
    out = tmp_path / "labels.xlsx"
    out.write_bytes(b"invented existing workbook sentinel")
    with pytest.raises(FileExistsError):
        write_workbook(episodes, out, template_header(ROOT))
    assert out.read_bytes() == b"invented existing workbook sentinel"
    assert write_workbook(episodes, out, template_header(ROOT), force=True) == (16, 34, 17)


def test_missing_held_out_refuses_before_writing(tmp_path, fixtures_dir):
    normal, _ = parse_dir(fixtures_dir / "normal")
    out = tmp_path / "missing.xlsx"
    with pytest.raises(ValueError, match="missing held-out episodes"):
        write_workbook(normal, out, template_header(ROOT))
    assert not out.exists()


def test_cli_counts_defaults_and_overwrite_refusal(tmp_path, write_config, monkeypatch, capsys, episodes):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    (tmp_path / "eval").mkdir()
    copyfile(ROOT / "eval" / "gold_template.csv", tmp_path / "eval" / "gold_template.csv")
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: episodes)
    assert cli.main(["make-workbook"]) == 0
    assert capsys.readouterr().out.strip() == (
        "outputs/labelling/gold_labelling.xlsx episode_sheets=16 line_rows=34 scene_rows=17")
    assert cli.main(["make-workbook"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert cli.main(["make-workbook", "--force"]) == 0


def test_cli_parses_fixture_data_live(tmp_path, fixtures_dir, write_config, monkeypatch, capsys):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    (tmp_path / "eval").mkdir()
    copyfile(ROOT / "eval" / "gold_template.csv", tmp_path / "eval" / "gold_template.csv")
    assert cli.main(["make-workbook", "--data-dir", str(fixtures_dir / "normal")]) == 1
    assert "missing held-out episodes" in capsys.readouterr().err
    assert not (tmp_path / "outputs" / "labelling" / "gold_labelling.xlsx").exists()
