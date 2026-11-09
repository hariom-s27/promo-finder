"""P08b fresh block B (episodes 15-17 and 35): split table, check-gold, list-lines, workbook, export, guard.

All data invented. Block B is sealed exactly like block A."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from shutil import copyfile

import pytest
from openpyxl import Workbook, load_workbook

from promo_finder import cli
from promo_finder import diagnostic as D
from promo_finder.checker import build_index
from promo_finder.gold import HEADER, check_sheet, format_report
from promo_finder.labelling import (FRESH, FRESH_B, FRESH_B_SPLIT, FRESH_SPLIT, HELD_OUT, SEALED, SPLITS,
                                    compact_eps, parse_eps)
from promo_finder.workbook import template_header
from test_fresh_split import SPEAKERS, guard, neg_row, row

ROOT = Path(__file__).resolve().parents[1]


def test_block_b_constants_and_split_table():
    assert FRESH_B == (15, 16, 17, 35)
    assert parse_eps(FRESH_B_SPLIT.spec) == list(FRESH_B) and compact_eps(FRESH_B) == FRESH_B_SPLIT.spec == "15-17,35"
    assert set(FRESH_B).isdisjoint(FRESH) and set(FRESH_B).isdisjoint(HELD_OUT)
    assert SEALED == FRESH + FRESH_B
    assert SPLITS["fresh_b"] is FRESH_B_SPLIT and FRESH_B_SPLIT.default_gold == "eval/gold_fresh_b.csv"
    assert (FRESH_B_SPLIT.pos_range, FRESH_B_SPLIT.neg_range) == ((6, 10), (1, 3)) == (FRESH_SPLIT.pos_range, FRESH_SPLIT.neg_range)
    assert FRESH_B_SPLIT.subdir == "fresh_b" and FRESH_B_SPLIT.default_workbook.startswith("outputs/labelling/fresh_b/")


def test_compact_eps_is_the_inverse_of_parse_eps():
    for spec in ("1-4,11-14,26-29,42-45", "31-34", "15-17,35", "7", "2,4,6", "9-10,12"):
        assert compact_eps(parse_eps(spec)) == spec
    assert compact_eps([4, 3, 3, 1]) == "1,3-4"


def test_block_b_is_sealed_in_the_diagnostic_tools():
    for ep in SEALED:
        with pytest.raises(D.SealedEpisode):
            D.refuse_fresh([1, ep])
    D.refuse_fresh([5, 18, 30, 36])


def test_guard_and_gitignore_block_gold_fresh_b():
    bad = guard.path_problems(["eval/gold_fresh_b.csv", "eval/gold_fresh_b_v2.csv"])
    assert len(bad) == 2 and all("gold labels" in b for b in bad)
    patterns = [x for x in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines() if x.startswith("eval/gold")]
    assert any(fnmatch.fnmatchcase("eval/gold_fresh_b.csv", p) for p in patterns)
    assert guard.path_problems(["eval/match_rule_fresh_b.md"]) == []


# ---------- check-gold ----------


@pytest.fixture
def index(episode_factory):
    spans = [(i * 5000, (i + 1) * 5000) for i in range(20)]
    return build_index(episode_factory(ep, spans) for ep in (1, 14, 15, 16, 17, 18, 31, 35, 36))


def check(index, rows, split=FRESH_B_SPLIT):
    return check_sheet(HEADER, list(enumerate(rows, 2)), index, SPEAKERS, split=split)


def pos(ep, **kw):
    return row(s1=(f"E{ep:02d}-L001", f"E{ep:02d}-L005"), **kw)


def cross(a, b):
    return row(s1=(f"E{a:02d}-L019", f"E{a:02d}-L020"), s2=(f"E{b:02d}-L001", f"E{b:02d}-L002"))


def test_block_b_check_gold_rules(index):
    assert check(index, [pos(15), neg_row(s1=("E15-L006", "E15-L010"))]).ok
    for ep in (14, 18, 31, 36, 1):
        errors = check(index, [pos(ep)]).rows[0].errors
        assert "NOT_IN_SPLIT" in errors and "NOT_HELD_OUT" not in errors, ep
    assert check(index, [cross(15, 16)]).rows[0].errors == []             # consecutive episodes inside the block
    assert check(index, [cross(16, 17)]).rows[0].errors == []
    assert "EP_SKIP" in check(index, [cross(15, 17)]).rows[0].errors      # skipping 16
    assert "EP_SKIP" in check(index, [cross(17, 35)]).rows[0].errors      # 17 and 35 are not consecutive episodes
    assert "NOT_IN_SPLIT" in check(index, [cross(17, 18)]).rows[0].errors  # 18 is outside the block
    # block A labels are not valid in block B, and the other way round
    assert "NOT_IN_SPLIT" in check(index, [pos(31)]).rows[0].errors
    assert "NOT_IN_SPLIT" in check(index, [pos(15)], split=FRESH_SPLIT).rows[0].errors


def test_block_b_report_and_warning_ranges(index):
    rows = []
    for n, ep in enumerate(FRESH_B):
        rows.append(pos(ep, gid=f"G{n}a"))
        rows.append(row(gid=f"G{n}b", s1=(f"E{ep:02d}-L011", f"E{ep:02d}-L015")))
    rows += [neg_row("N1", s1=("E15-L006", "E15-L010")), neg_row("N2", s1=("E16-L006", "E16-L010"))]
    lines = format_report(check(index, rows), [], FRESH_B_SPLIT)
    assert "block FB (15-17,35): pos=8 neg=2" in lines and lines[-1] == "check-gold: clean"
    assert not [x for x in lines if x.startswith("WARNING")]
    low = format_report(check(index, [pos(15)]), [], FRESH_B_SPLIT)
    assert "WARNING total positives 1 outside 6-10 (~8)" in low and "WARNING total negatives 0 outside 1-3 (~2)" in low
    assert "WARNING block FB: 1 positives (< 3)" in low


# ---------- CLI ----------


def test_list_lines_block_b_routing_and_refusals(tmp_path, write_config, monkeypatch, capsys, episode_factory):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    episodes = [episode_factory(ep, [(0, 25000)]) for ep in (1, 15, 16, 17, 18, 31, 35)]
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: episodes)
    assert cli.main(["list-lines", "--split", "fresh_b"]) == 0
    out = capsys.readouterr().out
    assert "outputs/labelling/fresh_b/E15_lines.md rows=1 scenes=1" in out and "written: 4 files" in out
    base = tmp_path / "outputs" / "labelling"
    assert sorted(p.name for p in (base / "fresh_b").iterdir()) == ["E15_lines.md", "E16_lines.md", "E17_lines.md", "E35_lines.md"]
    assert not (base / "fresh").exists() and not (base / "E15_lines.md").exists()
    assert cli.main(["list-lines", "--eps", "15-16"]) == 0                      # inside block B alone: routed there
    assert (base / "fresh_b" / "E16_lines.md").is_file() and not (base / "E16_lines.md").exists()
    capsys.readouterr()
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: pytest.fail("must refuse before loading"))
    assert cli.main(["list-lines", "--eps", "15,31"]) == 2                       # blocks A and B together
    assert cli.main(["list-lines", "--eps", "17,18"]) == 2                       # B with an ordinary episode
    assert "cannot be mixed" in capsys.readouterr().err
    assert cli.main(["list-lines", "--split", "fresh_b", "--eps", "15,18"]) == 2
    assert "fresh_b split covers episodes 15-17,35 only" in capsys.readouterr().err
    assert cli.main(["list-lines", "--split", "fresh", "--eps", "15"]) == 2      # a block B episode is not in block A


def test_block_b_workbook_and_export_defaults(tmp_path, write_config, monkeypatch, capsys, episode_factory):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    (tmp_path / "eval").mkdir()
    copyfile(ROOT / "eval" / "gold_template.csv", tmp_path / "eval" / "gold_template.csv")
    (tmp_path / "eval" / "HASHES.md").write_text("| File | sha256 | Bytes |\n", encoding="utf-8")
    spans = [(i * 5000, (i + 1) * 5000) for i in range(20)]
    monkeypatch.setattr(cli, "_load_episodes", lambda cfg, args: [episode_factory(ep, spans) for ep in FRESH_B])
    assert cli.main(["make-workbook", "--split", "fresh_b"]) == 0
    assert capsys.readouterr().out.strip() == (
        "outputs/labelling/fresh_b/gold_labelling_fresh_b.xlsx episode_sheets=4 line_rows=80 scene_rows=4")
    path = tmp_path / "outputs/labelling/fresh_b/gold_labelling_fresh_b.xlsx"
    wb = load_workbook(path)
    try:
        assert wb.sheetnames == ["README", "LABELS", "E15", "E16", "E17", "E35", "LINES", "CODES"]
        assert "block FB" in wb["E35"]["A1"].value
        assert {r[1] for r in wb["LINES"].iter_rows(min_row=2, values_only=True)} == set(FRESH_B)
        assert any("15-17,35" in c[0].value for c in wb["README"].iter_rows())
    finally:
        wb.close()
    labels = Workbook()
    labels.active.title = "LABELS"
    labels.active.append(template_header(ROOT))
    labels.active.append(["G01", "pos", 3, "E35-L001", "E35-L005", None, None, None, None, "H1", "C1", None, "the wife shouts"])
    labels.save(path)
    labels.close()
    assert cli.main(["export-gold", "--split", "fresh_b"]) == 0
    assert (tmp_path / "eval" / "gold_fresh_b.csv").is_file() and not (tmp_path / "eval" / "gold_fresh.csv").exists()
    assert "block FB (15-17,35): pos=1 neg=0" in capsys.readouterr().out
    csv_path = str(tmp_path / "eval/gold_fresh_b.csv")
    assert cli.main(["check-gold", csv_path, "--split", "fresh_b"]) == 0
    assert cli.main(["check-gold", csv_path, "--split", "fresh"]) == 1           # E35 is not in block A
