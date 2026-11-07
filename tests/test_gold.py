"""check-gold tests. Every episode, label, name and rationale here is invented."""

from __future__ import annotations

from pathlib import Path

import pytest

from promo_finder import cli
from promo_finder.checker import build_index
from promo_finder.gold import (HEADER, NAME_SKIP_WORDS, check_sheet, format_report, has_name,
                               name_patterns, read_sheet)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "eval" / "gold_template.csv"
SPEAKERS = {"WREN ASHDOWN", "DR KESTREL", "GUARD", "TEST SPEAKER"}


@pytest.fixture
def index(episode_factory):
    # 20 lines of 5 s each (0-100 s) in held-out eps 1-4 and 11, and non-held-out ep 5
    spans = [(i * 5000, (i + 1) * 5000) for i in range(20)]
    return build_index(episode_factory(ep, spans) for ep in (1, 2, 3, 4, 5, 11))


def row(gid="G01", kind="pos", grade="3", s1=("E01-L001", "E01-L005"), s2=("", ""), s3=("", ""),
        hook="H1", cliff="C1", neg="", rat="the wife confronts the boss at dinner"):
    return [gid, kind, grade, s1[0], s1[1], s2[0], s2[1], s3[0], s3[1], hook, cliff, neg, rat]


def neg_row(gid="N01", s1=("E01-L010", "E01-L015"), **kw):
    base = dict(kind="neg", grade="0", hook="", cliff="", neg="N1", rat="the rescue happens inside the clip")
    base.update(kw)
    return row(gid=gid, s1=s1, **base)


def check(index, rows, speakers=SPEAKERS):
    return check_sheet(HEADER, list(enumerate(rows, 2)), index, speakers)


def errs(index, r):
    return check(index, [r]).rows[0].errors


def test_valid_pos_and_neg(index):
    rep = check(index, [row(), neg_row()])
    assert [r.errors for r in rep.rows] == [[], []]
    assert rep.ok
    assert rep.rows[0].total_ms == 25000 and rep.rows[1].total_ms == 30000


def test_valid_cross_to_next_held_out_episode(index):
    r = row(s1=("E02-L019", "E02-L020"), s2=("E03-L001", "E03-L002"))
    assert errs(index, r) == []


@pytest.mark.parametrize("r, code", [
    (row(grade="0"), "BAD_GRADE"),
    (row(grade=""), "BAD_GRADE"),
    (neg_row(grade="2"), "BAD_GRADE"),
    (row(kind="maybe"), "BAD_KIND"),
    (row(hook="H10"), "BAD_HOOK"),
    (row(hook=""), "BAD_HOOK"),
    (neg_row(hook="H1"), "BAD_HOOK"),
    (row(cliff="C10"), "BAD_CLIFF"),
    (neg_row(cliff="C2"), "BAD_CLIFF"),
    (row(neg="N1"), "BAD_NEG_CODE"),
    (neg_row(neg="N7"), "BAD_NEG_CODE"),
    (neg_row(neg=""), "BAD_NEG_CODE"),
    (row(gid=""), "MISSING_ID"),
    (row(s1=("", ""), s2=("E01-L001", "E01-L005")), "MISSING_SEG1"),
    (row(s1=("", ""), s2=("E01-L001", "E01-L005")), "SEG_GAP"),
    (row(s1=("E01-L001", "E01-L003"), s3=("E01-L005", "E01-L007")), "SEG_GAP"),
    (row(s1=("E01-L001", "")), "INCOMPLETE_SEG"),
    (row(s2=("E01-L010", "")), "INCOMPLETE_SEG"),
    (row(s1=("E05-L001", "E05-L005")), "NOT_HELD_OUT"),
    (row(s1=("E04-L001", "E04-L003"), s2=("E11-L001", "E11-L002")), "EP_SKIP"),
    (row(s1=("E01-L019", "E01-L020"), s2=("E03-L001", "E03-L002")), "EP_SKIP"),
    (row(rat=""), "EMPTY_RATIONALE"),
    (row(rat=" ".join(["word"] * 21)), "RATIONALE_TOO_LONG"),
    (row(rat="the wife slaps kestrel"), "NAME_IN_RATIONALE"),
    (row(rat="the boss fires Wren   Ashdown"), "NAME_IN_RATIONALE"),
    (row(rat="ASHDOWN's secret is out"), "NAME_IN_RATIONALE"),
    # passed through unchanged from check_promo
    (row(s1=("E01-L001", "E01-L099")), "UNKNOWN_ID"),
    (row(s1=("E01-L001", "E01-L002")), "TOO_SHORT"),
    (row(s1=("E01-L001", "E01-L015")), "TOO_LONG"),
    (row(s1=("E01-L010", "E01-L005")), "REVERSED_SPAN"),
    (row(s1=("E01-L019", "E02-L002")), "CROSS_EP_SPAN"),
    (row(s1=("E01-L010", "E01-L013"), s2=("E01-L001", "E01-L003")), "OUT_OF_ORDER"),
    (row(s1=("E01-L001", "E01-L004"), s2=("E01-L003", "E01-L006")), "OVERLAP"),
])
def test_error_codes(index, r, code):
    assert code in errs(index, r)


def test_exactly_20_words_ok(index):
    assert errs(index, row(rat=" ".join(["word"] * 20))) == []


def test_bad_columns(index):
    assert check(index, [["G09", "pos", "3"]]).rows[0].errors == ["BAD_COLUMNS"]


def test_dup_id_marks_both(index):
    rep = check(index, [row(gid="G01"), row(gid="G01", s1=("E02-L001", "E02-L005"))])
    assert all("DUP_ID" in r.errors for r in rep.rows)


def test_pos_overlap_marks_both_and_names_partner(index):
    rep = check(index, [row(gid="G01"), row(gid="G02", s1=("E01-L002", "E01-L006")),
                        row(gid="G03", s1=("E01-L004", "E01-L008")), neg_row(s1=("E01-L001", "E01-L005"))])
    a, b, c, n = rep.rows
    assert "POS_OVERLAP(G02)" in a.errors and "POS_OVERLAP(G01)" in b.errors
    # G01 vs G03: 10 s shared / 40 s union = 0.25 < 0.5
    assert "POS_OVERLAP(G03)" not in a.errors
    assert n.errors == []  # negatives may overlap positives


def test_name_guard_skip_words_and_whole_words():
    pats = name_patterns(SPEAKERS)
    assert not has_name("the guard and the doctor argue; dr. arrives", pats)
    assert not has_name("the wrench drops", pats)  # 'wren' only as a whole word
    assert has_name("dr kestrel arrives", pats)
    assert has_name("WREN", pats)
    assert {"mr", "mrs", "ms", "dr", "doctor", "nurse", "guard", "officer", "mom", "dad",
            "boss", "man", "woman", "voice"} == set(NAME_SKIP_WORDS)
    # short words (<3 letters) are not matched alone
    assert not has_name("we go to lo", name_patterns({"LO VANCE"}))
    assert has_name("lo vance", name_patterns({"LO VANCE"}))


def test_output_never_shows_name_or_rationale(index):
    rep = check(index, [row(gid="G07", rat="kestrel strikes back at the boss")])
    text = "\n".join(format_report(rep, []))
    assert "G07" in text and "NAME_IN_RATIONALE" in text
    assert "kestrel" not in text.lower() and "strikes" not in text


def test_report_format_and_blocks(index):
    rep = check(index, [row(), neg_row(), row(gid="G02", s1=("E11-L001", "E11-L005"))])
    lines = format_report(rep, [])
    assert lines[0] == "G01  pos  OK  25.0s  E01  00:00.0–00:25.0"
    assert lines[1] == "N01  neg  OK  30.0s  E01  00:45.0–01:15.0"
    assert "block A (1-4): pos=1 neg=1" in lines and "block B (11-14): pos=1 neg=0" in lines
    assert "total: pos=2 neg=1" in lines
    assert "WARNING block B: 0 negatives" in lines
    assert "WARNING block C: 0 positives (< 3)" in lines
    assert "WARNING total positives 2 outside 12-18 (~15)" in lines
    assert "WARNING total negatives 1 outside 3-7 (~5)" in lines
    assert rep.ok and lines[-1] == "check-gold: clean"  # warnings are not errors


def test_bad_header(index):
    rep = check_sheet(HEADER[:-1], [], index, SPEAKERS)
    assert not rep.ok and rep.file_errors[0].startswith("BAD_HEADER")


def test_template_is_zero_rows(index):
    header, rows, warns = read_sheet(TEMPLATE)
    assert header == HEADER and rows == [] and warns == []
    rep = check_sheet(header, rows, index, SPEAKERS)
    assert rep.ok and format_report(rep, warns) == ["0 rows"]


def test_read_sheet_warns_bom_and_crlf(tmp_path):
    p = tmp_path / "g.csv"
    p.write_bytes(b"\xef\xbb\xbf" + ",".join(HEADER).encode() + b"\r\n")
    header, rows, warns = read_sheet(p)
    assert header == HEADER and rows == []
    assert any("BOM" in w for w in warns) and any("CRLF" in w for w in warns)


def _csv(rows):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(rows)
    return buf.getvalue()


def test_cli_end_to_end_on_fixtures(tmp_path, fixtures_dir, write_config, monkeypatch, capsys):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    g = tmp_path / "gold.csv"
    g.write_text(_csv([
        row(gid="G01", s1=("E01-L004", "E01-L007")),
        neg_row(gid="N01", s1=("E02-L002", "E02-L005")),
        row(gid="G02", s1=("E02-L002", "E02-L003"), rat="mara hides the letter"),
    ]), encoding="utf-8", newline="")
    rc = cli.main(["check-gold", str(g), "--data-dir", str(fixtures_dir / "normal")])
    out = capsys.readouterr().out
    assert rc == 1
    assert "G01  pos  OK  21.5s  E01  00:08.5–00:30.0" in out
    assert "N01  neg  OK  28.0s  E02  00:05.0–00:33.0" in out
    assert "G02  pos  TOO_SHORT NAME_IN_RATIONALE" in out
    assert "mara" not in out.lower() and "letter" not in out


def test_cli_template_exit_zero(tmp_path, fixtures_dir, write_config, monkeypatch, capsys):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    rc = cli.main(["check-gold", str(TEMPLATE), "--data-dir", str(fixtures_dir / "normal")])
    assert rc == 0 and capsys.readouterr().out.strip() == "0 rows"
