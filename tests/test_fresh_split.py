"""P08b fresh-split tooling: list-lines, check-gold, workbook, export-gold, guard. All data invented."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from shutil import copyfile

import pytest
from openpyxl import load_workbook

from promo_finder import cli
from promo_finder.checker import build_index
from promo_finder.gold import HEADER, check_sheet, format_report
from promo_finder.labelling import (FRESH, FRESH_SPLIT, HELD_OUT, HELD_OUT_SPLIT, SPLITS, parse_eps)
from promo_finder.workbook import readme_lines, template_header, write_workbook

ROOT = Path(__file__).resolve().parents[1]
SPEAKERS = {"WREN ASHDOWN", "TEST SPEAKER"}

spec = importlib.util.spec_from_file_location("guard", ROOT / "tools" / "guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def row(gid="G01", kind="pos", grade="3", s1=("E31-L001", "E31-L005"), s2=("", ""), s3=("", ""),
        hook="H1", cliff="C1", neg="", rat="the wife confronts the boss at dinner"):
    return [gid, kind, grade, s1[0], s1[1], s2[0], s2[1], s3[0], s3[1], hook, cliff, neg, rat]


def neg_row(gid="N01", s1=("E31-L006", "E31-L010"), **kw):
    base = dict(kind="neg", grade="0", hook="", cliff="", neg="N1", rat="the rescue happens inside the clip")
    base.update(kw)
    return row(gid=gid, s1=s1, **base)


@pytest.fixture
def index(episode_factory):
    spans = [(i * 5000, (i + 1) * 5000) for i in range(20)]
    return build_index(episode_factory(ep, spans) for ep in (1, 5, 30, 31, 32, 33, 34, 35))


def fresh_check(index, rows):
    return check_sheet(HEADER, list(enumerate(rows, 2)), index, SPEAKERS, split=FRESH_SPLIT)


def fresh_errs(index, r):
    return fresh_check(index, [r]).rows[0].errors


# ---------- constants ----------

def test_split_table_and_defaults():
    assert FRESH == (31, 32, 33, 34) and parse_eps(FRESH_SPLIT.spec) == list(FRESH)
    assert set(FRESH).isdisjoint(HELD_OUT)
    assert list(SPLITS) == ["held-out", "fresh", "fresh_b"]
    assert SPLITS["held-out"] is HELD_OUT_SPLIT and SPLITS["fresh"] is FRESH_SPLIT
    assert FRESH_SPLIT.pos_range == (6, 10) and FRESH_SPLIT.neg_range == (1, 3)
    assert HELD_OUT_SPLIT.pos_range == (12, 18) and HELD_OUT_SPLIT.neg_range == (3, 7)
    assert FRESH_SPLIT.default_gold == "eval/gold_fresh.csv"
    assert HELD_OUT_SPLIT.default_gold == "eval/gold.csv"


# ---------- guard and gitignore ----------

def test_guard_blocks_fresh_gold_names_only():
    bad = guard.path_problems(["eval/gold_fresh.csv", "eval/gold_fresh_v2.csv", "eval\\gold_fresh.csv"])
    assert len(bad) == 3 and all("gold labels" in b for b in bad)
    assert guard.path_problems(["eval/match_rule_fresh.md", "eval/gold_template.csv", "tests/eval/gold_fresh.csv",
                                "src/promo_finder/gold.py"]) == []


def test_gitignore_lists_fresh_gold():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "eval/gold_fresh*.csv" in lines and "eval/gold.csv" in lines


# ---------- check-gold --split fresh ----------

def test_fresh_valid_rows_and_checker_errors_unchanged(index):
    assert fresh_check(index, [row(), neg_row()]).ok
    assert "TOO_SHORT" in fresh_errs(index, row(s1=("E31-L001", "E31-L002")))
    assert "TOO_LONG" in fresh_errs(index, row(s1=("E31-L001", "E31-L015")))
    assert "UNKNOWN_ID" in fresh_errs(index, row(s1=("E31-L001", "E31-L099")))
    assert "BAD_HOOK" in fresh_errs(index, row(hook="H10"))
    assert "NAME_IN_RATIONALE" in fresh_errs(index, row(rat="ashdown wins"))


def test_fresh_crossing_only_between_consecutive_fresh_episodes(index):
    assert fresh_errs(index, row(s1=("E31-L019", "E31-L020"), s2=("E32-L001", "E32-L002"))) == []
    assert fresh_errs(index, row(s1=("E33-L019", "E33-L020"), s2=("E34-L001", "E34-L002"))) == []
    assert "EP_SKIP" in fresh_errs(index, row(s1=("E31-L019", "E31-L020"), s2=("E33-L001", "E33-L002")))
    # crossing out of the split, in either direction, is not allowed
    assert "NOT_IN_SPLIT" in fresh_errs(index, row(s1=("E34-L019", "E34-L020"), s2=("E35-L001", "E35-L002")))
    assert "NOT_IN_SPLIT" in fresh_errs(index, row(s1=("E30-L019", "E30-L020"), s2=("E31-L001", "E31-L002")))


@pytest.mark.parametrize("episode", ["E01", "E05", "E30", "E35"])
def test_fresh_rejects_labels_outside_split(index, episode):
    errors = fresh_errs(index, row(s1=(f"{episode}-L001", f"{episode}-L005")))
    assert "NOT_IN_SPLIT" in errors and "NOT_HELD_OUT" not in errors


def test_default_split_is_still_held_out(index):
    # same label, no split argument: fresh episodes are NOT held-out
    rep = check_sheet(HEADER, [(2, row())], index, SPEAKERS)
    assert "NOT_HELD_OUT" in rep.rows[0].errors and "NOT_IN_SPLIT" not in rep.rows[0].errors
    rep = check_sheet(HEADER, [(2, row(s1=("E01-L001", "E01-L005")))], index, SPEAKERS, split=FRESH_SPLIT)
    assert "NOT_IN_SPLIT" in rep.rows[0].errors


def test_fresh_pos_overlap_rule_unchanged(index):
    rep = fresh_check(index, [row(), row(gid="G02", s1=("E31-L002", "E31-L006"))])
    assert "POS_OVERLAP(G02)" in rep.rows[0].errors and "POS_OVERLAP(G01)" in rep.rows[1].errors


def eight_pos_two_neg():
    rows = []
    for n, ep in enumerate(FRESH):
        rows.append(row(gid=f"G{n}a", s1=(f"E{ep}-L001", f"E{ep}-L005")))
        rows.append(row(gid=f"G{n}b", s1=(f"E{ep}-L011", f"E{ep}-L015")))
    rows.append(neg_row("N1", s1=("E31-L006", "E31-L010")))
    rows.append(neg_row("N2", s1=("E32-L006", "E32-L010")))
    return rows


def test_fresh_report_blocks_and_warning_ranges(index):
    rep = fresh_check(index, eight_pos_two_neg())
    lines = format_report(rep, [], FRESH_SPLIT)
    assert rep.ok and lines[-1] == "check-gold: clean"
    assert "block F (31-34): pos=8 neg=2" in lines and "total: pos=8 neg=2" in lines
    assert not [x for x in lines if x.startswith("WARNING")]
    assert not any(x.startswith("block A") for x in lines)

    rep = fresh_check(index, [row(), neg_row(), neg_row("N2", s1=("E32-L006", "E32-L010")),
                              neg_row("N3", s1=("E33-L006", "E33-L010")), neg_row("N4", s1=("E34-L006", "E34-L010"))])
    lines = format_report(rep, [], FRESH_SPLIT)
    assert "WARNING block F: 1 positives (< 3)" in lines
    assert "WARNING total positives 1 outside 6-10 (~8)" in lines
    assert "WARNING total negatives 4 outside 1-3 (~2)" in lines
    assert rep.ok  # warnings never fail the check

    lines = format_report(fresh_check(index, [row()]), [], FRESH_SPLIT)
    assert "WARNING block F: 0 negatives" in lines
    assert "WARNING total negatives 0 outside 1-3 (~2)" in lines


def test_fresh_report_other_block_label(index):
    rep = fresh_check(index, [row(s1=("E05-L001", "E05-L005"))])
    lines = format_report(rep, [], FRESH_SPLIT)
    assert "block other (not in fresh split / unreadable): pos=1 neg=0" in lines


def test_cli_check_gold_split_fresh(tmp_path, write_config, monkeypatch, capsys, episode_factory):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    spans = [(i * 5000, (i + 1) * 5000) for i in range(20)]
    monkeypatch.setattr(cli, "_load_episodes",
                        lambda cfg, args: [episode_factory(ep, spans) for ep in (1, 31, 32, 33, 34)])
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(eight_pos_two_neg())
    path = tmp_path / "fresh.csv"
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")
    assert cli.main(["check-gold", str(path), "--split", "fresh"]) == 0
    out = capsys.readouterr().out
    assert "block F (31-34): pos=8 neg=2" in out and "check-gold: clean" in out
    # the same file under the default (held-out) split fails on every row
    assert cli.main(["check-gold", str(path)]) == 1
    assert "NOT_HELD_OUT" in capsys.readouterr().out


# ---------- list-lines ----------

@pytest.fixture
def fresh_episodes(episode_factory):
    return [episode_factory(ep, [(0, 25000)]) for ep in (1, 31, 32, 33, 34)]


def test_list_lines_split_fresh_writes_only_to_fresh_folder(tmp_path, write_config, monkeypatch, capsys, fresh_episodes):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: fresh_episodes)
    assert cli.main(["list-lines", "--split", "fresh"]) == 0
    cap = capsys.readouterr()
    assert "outputs/labelling/fresh/E31_lines.md rows=1 scenes=1" in cap.out and "written: 4 files" in cap.out
    assert "invented line" not in cap.out and "invented line" not in cap.err
    base = tmp_path / "outputs" / "labelling"
    assert sorted(p.name for p in (base / "fresh").iterdir()) == [f"E{n}_lines.md" for n in FRESH]
    assert not (base / "E31_lines.md").exists() and not (base / "E01_lines.md").exists()


def test_list_lines_eps_31_34_alone_routes_to_fresh(tmp_path, write_config, monkeypatch, capsys, fresh_episodes):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: fresh_episodes)
    assert cli.main(["list-lines", "--eps", "31-32"]) == 0
    assert "written: 2 files" in capsys.readouterr().out
    assert (tmp_path / "outputs" / "labelling" / "fresh" / "E32_lines.md").is_file()
    assert not (tmp_path / "outputs" / "labelling" / "E32_lines.md").exists()


def test_list_lines_refuses_mixed_or_foreign_eps_before_loading(write_config, monkeypatch, capsys):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: pytest.fail("must refuse before loading"))
    assert cli.main(["list-lines", "--eps", "1-2,31"]) == 2
    assert "cannot be mixed" in capsys.readouterr().err
    assert cli.main(["list-lines", "--split", "fresh", "--eps", "30-31"]) == 2
    assert "fresh split covers episodes 31-34 only" in capsys.readouterr().err


# ---------- workbook ----------

def test_workbook_fresh_structure_and_readme(tmp_path, fresh_episodes):
    out = tmp_path / "fresh.xlsx"
    counts = write_workbook(fresh_episodes, out, template_header(ROOT), split=FRESH_SPLIT)
    assert counts == (4, 4, 4)
    wb = load_workbook(out)
    try:
        assert wb.sheetnames == ["README", "LABELS"] + [f"E{n}" for n in FRESH] + ["LINES", "CODES"]
        readme = [c[0].value for c in wb["README"].iter_rows()]
        assert readme == list(readme_lines(FRESH_SPLIT))
        assert any("31-34" in line for line in readme) and not any("held-out" in line for line in readme)
        assert "block F" in wb["E31"]["A1"].value
        lookup_eps = {r[1] for r in wb["LINES"].iter_rows(min_row=2, values_only=True)}
        assert lookup_eps == set(FRESH)
    finally:
        wb.close()


def test_workbook_default_readme_unchanged():
    from promo_finder.workbook import README_LINES
    assert readme_lines() is README_LINES and readme_lines(HELD_OUT_SPLIT) is README_LINES
    assert sum("held-out" in line for line in README_LINES) == 1


def test_workbook_fresh_missing_episode_refused_before_writing(tmp_path, episode_factory):
    out = tmp_path / "x.xlsx"
    with pytest.raises(ValueError, match="missing fresh episodes: E34"):
        write_workbook([episode_factory(n, [(0, 25000)]) for n in (31, 32, 33)], out, template_header(ROOT),
                       split=FRESH_SPLIT)
    assert not out.exists()


def test_cli_make_workbook_fresh_default_path(tmp_path, write_config, monkeypatch, capsys, fresh_episodes):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    (tmp_path / "eval").mkdir()
    copyfile(ROOT / "eval" / "gold_template.csv", tmp_path / "eval" / "gold_template.csv")
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: fresh_episodes)
    assert cli.main(["make-workbook", "--split", "fresh"]) == 0
    assert capsys.readouterr().out.strip() == (
        "outputs/labelling/fresh/gold_labelling_fresh.xlsx episode_sheets=4 line_rows=4 scene_rows=4")
    assert cli.main(["make-workbook", "--split", "fresh"]) == 1
    assert "already exists" in capsys.readouterr().err
    # held-out default is untouched: it still demands all 16 held-out episodes
    assert cli.main(["make-workbook"]) == 1
    assert "missing held-out episodes" in capsys.readouterr().err
    assert not (tmp_path / "outputs" / "labelling" / "gold_labelling.xlsx").exists()


# ---------- export-gold ----------

def test_cli_export_gold_fresh_defaults(tmp_path, write_config, monkeypatch, capsys, episode_factory):
    from openpyxl import Workbook
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    (tmp_path / "eval").mkdir()
    copyfile(ROOT / "eval" / "gold_template.csv", tmp_path / "eval" / "gold_template.csv")
    (tmp_path / "eval" / "HASHES.md").write_text("| File | sha256 | Bytes |\n", encoding="utf-8")
    spans = [(i * 5000, (i + 1) * 5000) for i in range(20)]
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: [episode_factory(ep, spans) for ep in FRESH])
    wb = Workbook()
    wb.active.title = "LABELS"
    wb.active.append(template_header(ROOT))
    wb.active.append(["G01", "pos", 3, "E31-L001", "E31-L005", None, None, None, None, "H1", "C1", None, "the wife shouts"])
    default = tmp_path / "outputs" / "labelling" / "fresh" / "gold_labelling_fresh.xlsx"
    default.parent.mkdir(parents=True)
    wb.save(default)
    wb.close()
    assert cli.main(["export-gold", "--split", "fresh"]) == 0
    assert (tmp_path / "eval" / "gold_fresh.csv").is_file()
    assert not (tmp_path / "eval" / "gold.csv").exists()
    out = capsys.readouterr().out
    assert "block F (31-34): pos=1 neg=0" in out and "check-gold: clean" in out
