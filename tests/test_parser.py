from __future__ import annotations

from collections import Counter

import pytest

from promo_finder.config import load_config
from promo_finder.parser import classify_label, parse_dir, parse_file, parse_time
from promo_finder.validate import build_parse_report, validate_episode


def codes(ep):
    return Counter(w.code for w in ep.warnings)


def test_normal_episode(fixtures_dir):
    e = parse_file(fixtures_dir / "normal" / "episode-001-Episode 9000001.txt")
    assert e.ep == 1 and e.header_ep == 1 and e.source_id == "9000001"
    assert e.logline.startswith("A young lighthouse keeper")
    assert len(e.scenes) == 2
    assert [s.number for s in e.scenes] == [1, 2]
    assert (e.scenes[0].start_ms, e.scenes[0].end_ms) == (0, 30000)
    assert (e.scenes[1].start_ms, e.scenes[1].end_ms) == (30000, 70000)
    assert len(e.lines) == 13
    assert e.lines[0].id == "E01-L001" and e.lines[-1].id == "E01-L013"
    assert [x.idx for x in e.lines] == list(range(1, 14))
    kinds = Counter(x.kind for x in e.lines)
    assert kinds == {"camera": 4, "action": 2, "sfx": 2, "dialogue": 5}
    d = e.lines[3]
    assert (d.kind, d.speaker, d.emotion, d.ext) == ("dialogue", "MARA QUILL", "Startled", None)
    assert (d.start_ms, d.end_ms) == (8500, 12000)
    sfx = e.lines[2]
    assert sfx.kind == "sfx" and sfx.text.startswith("[") and sfx.text.endswith("]")
    assert e.scenes[0].line_ids == [f"E01-L{i:03d}" for i in range(1, 8)]
    assert all(x.scene == 2 for x in e.lines[7:])
    assert e.duration_ms == 70000
    assert e.warnings == []


def test_multiline_text_joined(fixtures_dir):
    e = parse_file(fixtures_dir / "edge" / "episode-021-Episode 9000021.txt")
    assert len(e.lines) == 3
    assert e.lines[0].text == ("Tobin sands the hull of an upturned dinghy. "
                               "He stops when he hears footsteps on the gravel.")
    assert codes(e)["MULTILINE_JOINED"] == 1


def test_odd_time_formats(fixtures_dir):
    e = parse_file(fixtures_dir / "edge" / "episode-022-Episode 9000022.txt")
    got = [(x.start_ms, x.end_ms) for x in e.lines]
    assert got == [(0, 5000), (5500, 9250), (9000, 12000), (12500, 65125)]
    assert (e.scenes[0].start_ms, e.scenes[0].end_ms) == (0, 65000)
    assert e.warnings == []


@pytest.mark.parametrize("s,ms", [
    ("00:04.80", 4800), ("0:05", 5000), ("00:09", 9000), ("1:02.5", 62500),
    ("00:01:05.00", 65000), ("01:00:00", 3600000), ("(00:12.34)", 12340), ("75:00.00", 4500000),
])
def test_parse_time_ok(s, ms):
    assert parse_time(s) == ms


@pytest.mark.parametrize("s", ["", "ab:cd", "00:61.00", "12", "1:2:3:4", "00-05"])
def test_parse_time_bad(s):
    assert parse_time(s) is None


def test_broken_block_warns_and_continues(fixtures_dir):
    e = parse_file(fixtures_dir / "edge" / "episode-023-Episode 9000023.txt")
    c = codes(e)
    assert c["NO_TIMING"] == 1 and c["BAD_TIME"] == 1
    assert [x.kind for x in e.lines] == ["camera", "dialogue", "camera"]
    assert [x.id for x in e.lines] == ["E23-L001", "E23-L002", "E23-L003"]
    for w in e.warnings:  # warnings carry no script text
        assert "barrel" not in w.reason.lower() and "drips" not in w.reason.lower()


def test_filename_header_mismatch(fixtures_dir):
    e = parse_file(fixtures_dir / "edge" / "episode-010-Episode 9000010.txt")
    assert e.ep == 10 and e.header_ep == 11
    assert codes(e)["EP_MISMATCH"] == 1
    assert e.lines[0].id == "E10-L001"


def test_all_caps_scene_labels(fixtures_dir):
    e = parse_file(fixtures_dir / "edge" / "episode-024-Episode 9000024.txt")
    assert len(e.scenes) == 2
    assert e.scenes[0].heading.startswith("INT. KEEPER")
    assert (e.scenes[1].start_ms, e.scenes[1].end_ms) == (15000, 25000)
    assert len(e.lines) == 3 and e.warnings == []


def test_double_bracket_speaker(fixtures_dir):
    e = parse_file(fixtures_dir / "edge" / "episode-025-Episode 9000025.txt")
    a, b, c = e.lines
    assert (a.speaker, a.ext, a.emotion) == ("IVES RENNICK", "O.S.", "Mocking")
    assert (b.speaker, b.ext, b.emotion) == ("MARA QUILL", "V.O.", "Determined")
    assert c.kind == "sfx" and c.text == "[Heavy bolt slides shut]"


def test_classify_label():
    assert classify_label("CAMERA") == ("camera", None, None, None)
    assert classify_label("Sound FX") == ("sfx", None, None, None)
    assert classify_label("ACTION") == ("action", None, None, None)
    assert classify_label("NEW PERSON") == ("dialogue", "NEW PERSON", None, None)


def test_same_ids_across_two_parses(fixtures_dir):
    f = fixtures_dir / "normal" / "episode-001-Episode 9000001.txt"
    a, b = parse_file(f), parse_file(f)
    assert [(x.id, x.start_ms, x.end_ms, x.text) for x in a.lines] == \
           [(x.id, x.start_ms, x.end_ms, x.text) for x in b.lines]
    assert a.model_dump() == b.model_dump()


def test_parse_dir_and_report(fixtures_dir):
    eps, fw = parse_dir(fixtures_dir / "normal")
    assert [e.ep for e in eps] == [1, 2] and fw == []
    rep = build_parse_report(eps, fw)
    t = rep["totals"]
    assert t["episodes"] == 2 and t["scenes"] == 3 and t["lines"] == 20
    assert t["distinct_speakers"] == 3
    # report is numbers only: no speaker names anywhere
    blob = str(rep).upper()
    assert "MARA" not in blob and "TOBIN" not in blob and "RENNICK" not in blob


def test_validator_counts(episode_factory, fixtures_dir):
    e = episode_factory(5, [(0, 5000), (4000, 9000), (9000, 9000), (12000, 15000), (11500, 13000)])
    rep, warns = validate_episode(e)
    assert rep.start_ge_end == ["E05-L003"]
    assert rep.backwards_starts == 1                     # 11500 after 12000
    assert rep.overlaps_by_pair == {"dialogue+dialogue": 2}
    assert rep.gaps_over_2s == 1                         # nothing covers 9000 -> 11500
    e3 = episode_factory(6, [(0, 5000), (7000, 8000)])   # exactly 2 s is not a gap
    assert validate_episode(e3)[0].gaps_over_2s == 0
    assert {w.code for w in warns} == {"START_GE_END"}
    # odd-times fixture has a line ending after its scene end
    e2 = parse_file(fixtures_dir / "edge" / "episode-022-Episode 9000022.txt")
    rep2, _ = validate_episode(e2)
    assert rep2.out_of_scene == ["E22-L004"]


def test_parser_handles_no_fixed_scene_count(tmp_path):
    body = ["EPISODE NUMBER: Episode 3", "EPISODE LOGLINE: x", "CONTINUITY NOTES: y", "", "--- SCRIPT START ---"]
    for n in range(1, 6):
        body += [f"SCENE {n:02d}", "Scene heading: INT. ROOM – DAY", f"Scene start: 00:{(n-1)*10:02d}.00",
                 f"Scene end: 00:{n*10:02d}.00", "", "**CAMERA:**",
                 f"Start: (00:{(n-1)*10:02d}.00) | End: (00:{n*10:02d}.00)", "An invented shot.", ""]
    body.append("--- SCRIPT END ---")
    f = tmp_path / "episode-003-Episode 1.txt"
    f.write_text("\n".join(body), encoding="utf-8")
    e = parse_file(f)
    assert len(e.scenes) == 5 and len(e.lines) == 5 and e.warnings == []


# ------------------------------------------------------------ integration (real scripts)
@pytest.mark.integration
def test_integration_real_scripts():
    cfg = load_config()
    if not cfg.data_dir.is_dir():
        pytest.skip("data_dir missing")
    eps, fw = parse_dir(cfg.data_dir)
    flagged = set()
    for e in eps:
        rep, _ = validate_episode(e)
        flagged |= set(rep.start_ge_end)
    ids = [x.id for e in eps for x in e.lines]
    n_lines = len(ids)
    print(f"\n[integration] episodes={len(eps)} lines={n_lines} scenes={sum(len(e.scenes) for e in eps)} "
          f"file_warnings={len(fw)} start_ge_end_flagged={len(flagged)}")
    assert len(eps) == 50
    assert all(len(e.lines) > 0 for e in eps)
    assert all(x.start_ms < x.end_ms or x.id in flagged for e in eps for x in e.lines)
    assert len(ids) == len(set(ids))
