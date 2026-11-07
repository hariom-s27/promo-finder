"""hash_eval tests. Runs in a temp folder with invented files."""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "hash_eval.py"
spec = importlib.util.spec_from_file_location("hash_eval", TOOL)
he = importlib.util.module_from_spec(spec)
spec.loader.exec_module(he)

FILES = {"eval/match_rule.md": b"invented rule\n", "eval/gold_rubric.md": b"invented rubric\n",
         "eval/gold_template.csv": b"a,b\n"}
ROW = re.compile(r"^\| (\S+) \| ([0-9a-f]{64}) \| (\d+) \| (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) \| (.*) \|$")


@pytest.fixture
def repo(tmp_path):
    for rel, b in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return tmp_path


def expected():
    return {k: hashlib.sha256(v).hexdigest() for k, v in FILES.items()}


def test_expected_table_matches_prompt():
    assert he.EXPECTED == {
        "eval/match_rule.md": "d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2",
        "eval/gold_rubric.md": "6f7b5161a66d857e913e5f73715f6b36c129d4cd57b69cd7d618e2b53f5550c0",
        "eval/gold_template.csv": "bb794d8a826bbc62288c30d16010e162c647ae5bdd19673dc22ebaf422bd8391",
    }


def test_init_writes_table(repo):
    assert he.main(["--root", str(repo), "init"], expected=expected()) == 0
    raw = (repo / "eval" / "HASHES.md").read_bytes()
    assert b"\r" not in raw
    lines = raw.decode().splitlines()
    assert lines[0] == "# EVAL HASHES (sha256 of file bytes, LF line endings)"
    assert lines[1].startswith("Frozen BEFORE any gold label exists.")
    assert lines[3] == "| File | sha256 | Bytes | Recorded (UTC) | Note |"
    assert lines[4] == "|---|---|---|---|---|"
    rows = [ROW.match(x) for x in lines[5:]]
    assert len(rows) == 3 and all(rows)
    for m in rows:
        assert m.group(2) == hashlib.sha256(FILES[m.group(1)]).hexdigest()
        assert int(m.group(3)) == len(FILES[m.group(1)])
        assert m.group(5) == "frozen before labelling"


def test_init_fails_loudly_on_mismatch(repo, capsys):
    (repo / "eval" / "gold_rubric.md").write_bytes(b"invented rubric, edited\n")
    assert he.main(["--root", str(repo), "init"], expected=expected()) == 1
    err = capsys.readouterr().err
    assert "MISMATCH eval/gold_rubric.md" in err and "not written" in err
    assert not (repo / "eval" / "HASHES.md").exists()


def test_init_refuses_overwrite(repo):
    assert he.main(["--root", str(repo), "init"], expected=expected()) == 0
    assert he.main(["--root", str(repo), "init"], expected=expected()) == 1


def test_add_appends_gold_row(repo):
    he.main(["--root", str(repo), "init"], expected=expected())
    (repo / "eval" / "gold.csv").write_bytes(b"a,b\n1,2\n")
    assert he.main(["--root", str(repo), "add", "eval/gold.csv"]) == 0
    lines = (repo / "eval" / "HASHES.md").read_text().splitlines()
    m = ROW.match(lines[-1])
    assert m and m.group(1) == "eval/gold.csv" and m.group(3) == "8"
    assert m.group(5) == "gold labels, hash only (file committed at P08)"
    assert len(lines) == 9


def test_add_refuses_crlf_and_bom(repo, capsys):
    he.main(["--root", str(repo), "init"], expected=expected())
    before = (repo / "eval" / "HASHES.md").read_bytes()
    (repo / "eval" / "gold.csv").write_bytes(b"a,b\r\n1,2\r\n")
    assert he.main(["--root", str(repo), "add", "eval/gold.csv"]) == 1
    assert "CRLF" in capsys.readouterr().err
    (repo / "eval" / "gold_v2.csv").write_bytes(b"\xef\xbb\xbfa,b\n")
    assert he.main(["--root", str(repo), "add", "eval/gold_v2.csv"]) == 1
    assert "BOM" in capsys.readouterr().err
    assert (repo / "eval" / "HASHES.md").read_bytes() == before


def test_add_needs_init(repo):
    (repo / "eval" / "gold.csv").write_bytes(b"a\n")
    assert he.main(["--root", str(repo), "add", "eval/gold.csv"]) == 1
