"""CSV byte and checker integration tests using invented labels only."""

from pathlib import Path
from shutil import copyfile

import pytest
from openpyxl import Workbook

from promo_finder import cli
from promo_finder.workbook import WorkbookError, export_labels, template_header

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def export_setup(tmp_path, write_config, monkeypatch):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    folder = tmp_path / "eval"
    folder.mkdir()
    copyfile(ROOT / "eval" / "gold_template.csv", folder / "gold_template.csv")
    (folder / "HASHES.md").write_text("| File | sha256 | Bytes |\n", encoding="utf-8")
    return tmp_path


def labels_file(root, rows, header=None):
    wb = Workbook()
    wb.active.title = "LABELS"
    wb.active.append(header if header is not None else template_header(ROOT))
    for row in rows:
        wb.active.append(row)
    # Export must ignore helpers even on otherwise empty rows.
    wb.active["N3"] = "=1+1"
    wb.create_sheet("E01")["A1"] = "invented episode cell must not be accessed"
    out = root / "labels.xlsx"
    wb.save(out)
    wb.close()
    return out


def valid_rows():
    return [
        [" G01 ", " POS ", 3.0, " e01-l004 ", "e01-l007", None, None, None, None,
         " h1 ", " c1 ", None, ' a turn, followed by "danger" '],
        [None] * 13,
        [" N01 ", " NEG ", 0, "e02-l002", "e02-l005", None, None, None, None,
         None, None, " n1 ", "the resolution occurs inside the clip"],
    ]


def test_csv_exact_bytes_then_check_gold(export_setup, fixtures_dir, capsys):
    root = export_setup
    xlsx = labels_file(root, valid_rows())
    out = root / "eval" / "fixture_gold.csv"
    assert cli.main(["export-gold", "--xlsx", str(xlsx), "--out", str(out),
                     "--data-dir", str(fixtures_dir / "normal")]) == 0
    expected = (
        ",".join(template_header(ROOT)) + "\n"
        'G01,pos,3,E01-L004,E01-L007,,,,,H1,C1,,"a turn, followed by ""danger"""\n'
        "N01,neg,0,E02-L002,E02-L005,,,,,,,N1,the resolution occurs inside the clip\n"
    ).encode("utf-8")
    assert out.read_bytes() == expected
    captured = capsys.readouterr()
    assert "G01  pos  OK" in captured.out and "N01  neg  OK" in captured.out
    assert "block A (1-4): pos=1 neg=1" in captured.out and "WARNING" in captured.out
    assert "check-gold: clean" in captured.out
    assert "danger" not in captured.out and "resolution" not in captured.out and not captured.err
    assert cli.main(["check-gold", str(out), "--data-dir", str(fixtures_dir / "normal")]) == 0


@pytest.mark.parametrize("recorded", ["eval/fixture_gold.csv", "fixture_gold.csv", "other/FIXTURE_GOLD.CSV"])
def test_seal_refuses_without_touching_target(export_setup, recorded, fixtures_dir, capsys):
    root = export_setup
    out = root / "eval" / "fixture_gold.csv"
    out.write_bytes(b"invented sealed sentinel\n")
    (root / "eval" / "HASHES.md").write_text(f"| {recorded} | fakehash | 1 |\n", encoding="utf-8")
    assert cli.main(["export-gold", "--xlsx", str(root / "not-opened.xlsx"), "--out", str(out),
                     "--data-dir", str(fixtures_dir / "normal")]) == 1
    assert out.read_bytes() == b"invented sealed sentinel\n"
    assert "--out eval/gold_v2.csv" in capsys.readouterr().err


def test_unsealed_export_can_be_repeated(export_setup, fixtures_dir, capsys):
    root = export_setup
    xlsx = labels_file(root, valid_rows())
    out = root / "eval" / "fixture_gold.csv"
    out.write_bytes(b"invented older export\n")
    args = ["export-gold", "--xlsx", str(xlsx), "--out", str(out),
            "--data-dir", str(fixtures_dir / "normal")]
    assert cli.main(args) == 0
    first = out.read_bytes()
    assert cli.main(args) == 0 and out.read_bytes() == first
    capsys.readouterr()


def test_checker_error_exit_and_rationale_not_printed(export_setup, fixtures_dir, capsys):
    root = export_setup
    rows = valid_rows()[:1]
    rows[0][4] = "E01-L004"
    rows[0][2] = 3.5  # Do not silently truncate an invalid grade into a valid one.
    xlsx = labels_file(root, rows)
    out = root / "eval" / "fixture_bad.csv"
    assert cli.main(["export-gold", "--xlsx", str(xlsx), "--out", str(out),
                     "--data-dir", str(fixtures_dir / "normal")]) == 1
    captured = capsys.readouterr()
    assert "TOO_SHORT" in captured.out and "BAD_GRADE" in captured.out
    assert "danger" not in captured.out


def test_bad_header_refuses_before_output(export_setup):
    root = export_setup
    xlsx = labels_file(root, [], header=["wrong"])
    out = root / "eval" / "fixture_gold.csv"
    with pytest.raises(WorkbookError, match="template header"):
        export_labels(xlsx, out, template_header(ROOT), root / "eval" / "HASHES.md")
    assert not out.exists()


def test_export_only_reads_labels_columns_a_to_m(export_setup, monkeypatch):
    from promo_finder import workbook

    root = export_setup
    seen = []

    class Labels:
        def iter_rows(self, **kwargs):
            seen.append(kwargs)
            return iter([tuple(template_header(ROOT))] + [tuple(row) for row in valid_rows()])

    class Book:
        sheetnames = ["LABELS", "E01"]

        def __getitem__(self, key):
            assert key == "LABELS"
            return Labels()

        def close(self):
            pass

    def load(path, **kwargs):
        assert kwargs == {"read_only": True, "data_only": True}
        return Book()

    monkeypatch.setattr(workbook, "load_workbook", load)
    export_labels(root / "unused.xlsx", root / "fixture_gold.csv", template_header(ROOT),
                  root / "eval" / "HASHES.md")
    assert seen == [{"min_row": 1, "max_col": 13, "values_only": True}]
    assert b"G01,pos,3," in (root / "fixture_gold.csv").read_bytes()
