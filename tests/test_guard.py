"""Leak guard tests. All text here is invented; runs in a temp folder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

GUARD_PATH = Path(__file__).resolve().parents[1] / "tools" / "guard.py"
spec = importlib.util.spec_from_file_location("guard", GUARD_PATH)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SECRET_SCRIPT = (
    "**WREN (Calm):**\nStart: (00:01.00) | End: (00:04.00)\n"
    "The copper kettle sang a tune nobody in the valley had heard before tonight.\n"
)


@pytest.fixture
def setup(tmp_path):
    data = tmp_path / "data_src"
    data.mkdir()
    (data / "episode-001-Episode 1.txt").write_text(SECRET_SCRIPT, encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    return repo, data


def test_path_problems():
    bad = guard.path_problems(["data/x.txt", "outputs/parsed/E01.json", ".cache/llm/a.json",
                               ".venv/lib/x.py", ".env", "sub/.env", "prod.env", ".env.local"])
    assert len(bad) == 8
    assert guard.path_problems(["src/promo_finder/parser.py", "tests/fixtures/normal/x.txt",
                                "docs/environment.md"]) == []


def test_scan_hits_8_words_case_and_space_insensitive(setup):
    _, data = setup
    sh = guard.build_shingles(data)
    text = "line one is fine\nnote: THE copper   kettle sang a\n tune nobody in the valley\n"
    assert guard.scan_text(text, sh) == [2]


def test_scan_7_words_is_clean(setup):
    _, data = setup
    sh = guard.build_shingles(data)
    assert guard.scan_text("the copper kettle sang a tune nobody", sh) == []


def test_format_lines_alone_do_not_hit(setup):
    _, data = setup
    sh = guard.build_shingles(data)
    assert guard.scan_text("**WREN (Calm):**\nStart: (00:01.00) | End: (00:04.00)\n", sh) == []


def test_layout_only_window_does_not_hit(tmp_path):
    data = tmp_path / "d"
    data.mkdir()
    (data / "a.txt").write_text("--- SCRIPT START ---\n\nSCENE 01\nScene heading: EXT. MOOR – DAY\n", encoding="utf-8")
    sh = guard.build_shingles(data)
    assert guard.scan_text("--- SCRIPT START ---\n\nSCENE 01\nScene heading: INT. MILL – NIGHT\n", sh) == []


def test_main_all_mode_prints_only_path_line(setup, capsys):
    repo, data = setup
    (repo / "src" / "ok.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "src" / "leak.md").write_text("intro\n\nthe copper kettle sang a tune nobody in the valley\n",
                                          encoding="utf-8")
    (repo / ".env").write_text("SHOULD_NEVER_BE_READ=1\n", encoding="utf-8")
    rc = guard.main(["--all", "--root", str(repo), "--data-dir", str(data)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "src/leak.md:3" in out
    assert "kettle" not in out and "copper" not in out and "SHOULD_NEVER" not in out


def test_main_clean(setup, capsys):
    repo, data = setup
    (repo / "src" / "ok.py").write_text("print('hello')\n", encoding="utf-8")
    assert guard.main(["--all", "--root", str(repo), "--data-dir", str(data)]) == 0
    assert "clean" in capsys.readouterr().out


def test_staged_mode_blocks_paths_and_never_reads_env(setup, monkeypatch, capsys):
    repo, data = setup
    staged = {"src/ok.py": b"x = 1\n", ".env": b"KEY=nope\n", "outputs/parse_report.json": b"{}"}
    read = []
    monkeypatch.setattr(guard, "in_git_repo", lambda root: True)
    monkeypatch.setattr(guard, "staged_files", lambda root: list(staged))
    monkeypatch.setattr(guard, "read_staged", lambda root, p: read.append(p) or staged[p])
    rc = guard.main(["--root", str(repo), "--data-dir", str(data)])
    out = capsys.readouterr().out
    assert rc == 1
    assert ".env: env file" in out and "outputs/parse_report.json: blocked path" in out
    assert read == ["src/ok.py"]


def test_missing_data_dir_fails_closed(tmp_path):
    assert guard.main(["--all", "--root", str(tmp_path), "--data-dir", str(tmp_path / "nope")]) == 2
