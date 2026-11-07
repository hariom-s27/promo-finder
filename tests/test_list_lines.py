"""list-lines tests over the invented fixtures."""

from __future__ import annotations

import re

import pytest

from promo_finder import cli
from promo_finder.labelling import HELD_OUT, HELD_OUT_SPEC, fmt_ms, parse_eps, render_episode, write_labelling
from promo_finder.parser import parse_dir

ROW = re.compile(r"^\| (E\d{2}-L\d{3}) \| (\d{2}:\d{2}\.\d) \| (\d{2}:\d{2}\.\d) \| (\w+) \| ")


def test_parse_eps():
    assert parse_eps("1-4,11-14,26-29,42-45") == list(HELD_OUT)
    assert parse_eps(HELD_OUT_SPEC) == list(HELD_OUT)
    assert parse_eps("7") == [7]
    assert parse_eps(" 3 , 1-2,2") == [1, 2, 3]
    for bad in ["", "a", "4-1", "1-", "0", "1,,2"]:
        with pytest.raises(ValueError):
            parse_eps(bad)


def test_fmt_ms():
    assert fmt_ms(0) == "00:00.0"
    assert fmt_ms(8500) == "00:08.5"
    assert fmt_ms(65125) == "01:05.1"
    assert fmt_ms(59960) == "01:00.0"  # never 00:60.0
    assert fmt_ms(754049) == "12:34.0"
    assert fmt_ms(754050) == "12:34.1"


def test_render_episode_rows_ids_and_scene_markers(fixtures_dir):
    eps, _ = parse_dir(fixtures_dir / "normal")
    e1 = next(e for e in eps if e.ep == 1)
    md, rows, markers = render_episode(e1)
    lines = md.splitlines()
    assert lines[0] == "# E01  duration 01:10.0"
    assert rows == len(e1.lines) == 13 and markers == 2
    data = [ln for ln in lines if ROW.match(ln)]
    assert [ROW.match(ln).group(1) for ln in data] == [x.id for x in e1.lines]
    first = ROW.match(data[0])
    assert first.group(2, 3, 4) == ("00:00.0", "00:06.0", "camera")
    scene_rows = [i for i, ln in enumerate(lines) if ln.startswith("| --- scene ")]
    assert [lines[i].split()[3] for i in scene_rows] == ["1", "2"]
    # scene 2 marker sits right before the first scene-2 line
    assert lines[scene_rows[1] + 1].startswith("| E01-L008 |")
    # every row has 7 cells
    for ln in data:
        assert len(re.split(r"(?<!\\)\|", ln)) == 9


def test_speaker_only_for_dialogue(episode_factory):
    e = episode_factory(5, [(0, 1000), (1000, 2000)], kind="action")
    md, _, _ = render_episode(e)
    assert "TEST SPEAKER" not in md


def test_pipes_escaped(episode_factory):
    e = episode_factory(5, [(0, 1000)])
    e.lines[0].text = "a | b\nc"
    md, _, _ = render_episode(e)
    assert "a \\| b c" in md


def test_write_labelling_missing(tmp_path, fixtures_dir):
    eps, _ = parse_dir(fixtures_dir / "normal")
    written, missing = write_labelling(eps, [1, 2, 3], tmp_path / "lab")
    assert [p.name for p, _, _ in written] == ["E01_lines.md", "E02_lines.md"]
    assert missing == [3]
    assert (tmp_path / "lab" / "E02_lines.md").read_bytes().count(b"\r") == 0


def test_cli_prints_only_paths_and_counts(tmp_path, fixtures_dir, write_config, monkeypatch, capsys):
    cfgp = write_config()
    monkeypatch.setenv("KUKU_CONFIG", str(cfgp))
    rc = cli.main(["list-lines", "--eps", "1-2", "--data-dir", str(fixtures_dir / "normal")])
    cap = capsys.readouterr()
    assert rc == 0
    out = cap.out
    assert "E01_lines.md rows=13 scenes=2" in out and "E02_lines.md rows=7 scenes=1" in out
    assert "MARA" not in out and "Startled" not in out and "MARA" not in cap.err
    assert (tmp_path / "outputs" / "labelling" / "E01_lines.md").is_file()


def test_cli_default_eps_reports_missing(tmp_path, fixtures_dir, write_config, monkeypatch, capsys):
    monkeypatch.setenv("KUKU_CONFIG", str(write_config()))
    rc = cli.main(["list-lines", "--data-dir", str(fixtures_dir / "normal")])
    cap = capsys.readouterr()
    assert rc == 0
    assert "written: 2 files" in cap.out
    assert "not found: 3,4,11,12,13,14,26,27,28,29,42,43,44,45" in cap.err
