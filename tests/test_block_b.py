"""P08b fresh block B: the selection rule, its tool, and the sealed episode set. All data invented."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from promo_finder import evaluation_lists as E

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pick_block_b", ROOT / "tools/pick_block_b.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def cand(ep, first, last, pid="P05-E00-001", pre=1.0, flags=None):
    return {"promo_id": pid, "pre_score": pre, "flags": flags or {}, "segments": [
        {"episode": ep, "first_line_id": f"E{ep:02d}-L{first:03d}", "last_line_id": f"E{ep:02d}-L{last:03d}"}]}


# ── the rule ────────────────────────────────────────────────────────────


def test_eligible_episodes_exclude_held_out_dev_block_a_and_late_series():
    eligible = E.block_b_eligible()
    assert eligible == [9, 10, 15, 16, 17, 18, 23, 24, 25, 30, 35, 36, 37, 38, 39, 40, 41]
    for excluded in (1, 4, 11, 14, 26, 29, 42, 45, 5, 8, 19, 22, 31, 32, 33, 34, 46, 47, 50):
        assert excluded not in eligible


def test_candidate_identity_ignores_ids_scores_and_flags():
    a = [cand(9, 1, 5, pid="P05-E09-001", pre=3.2), cand(9, 6, 9, pid="P05-E09-002")]
    b = [cand(9, 6, 9, pid="P05-E09-001", pre=1.0, flags={"extended": True}), cand(9, 1, 5, pid="P05-E09-002")]
    assert E.span_set(a) == E.span_set(b)                                   # renumbered / re-scored / flagged: same set
    assert E.span_set([cand(9, 1, 6)]) != E.span_set([cand(9, 1, 5)])       # a different end line is a different candidate
    two = {"promo_id": "x", "segments": [cand(9, 1, 2)["segments"][0], cand(9, 7, 8)["segments"][0]]}
    assert E.span_set([two]) != E.span_set([cand(9, 1, 2)])                 # a montage is not its first piece


def test_symmetric_difference_counts_what_only_one_version_keeps():
    v1 = {9: [cand(9, 1, 5), cand(9, 6, 9)], 10: [cand(10, 1, 5)], 15: []}
    v2 = {9: [cand(9, 1, 5), cand(9, 6, 9), cand(9, 10, 14), cand(9, 15, 19)], 10: [], 15: [cand(15, 2, 8)]}
    assert E.symmetric_difference_counts(v1, v2) == {9: 2, 10: 1, 15: 1}
    swapped = E.symmetric_difference_counts(v2, v1)
    assert swapped == {9: 2, 10: 1, 15: 1}                                  # symmetric
    assert E.symmetric_difference_counts(v1, v1) == {9: 0, 10: 0, 15: 0}
    with pytest.raises(E.ListError):
        E.symmetric_difference_counts({9: []}, {10: []})


def test_pick_takes_the_largest_four_and_ties_go_to_the_lower_episode():
    counts = {9: 3, 10: 7, 15: 7, 16: 7, 17: 7, 18: 7, 23: 1}
    assert E.pick_block_b(counts) == [10, 15, 16, 17]                      # five-way tie at 7: lowest four episodes
    assert E.pick_block_b({9: 5, 10: 9, 15: 2, 16: 9, 17: 4, 18: 4}) == [10, 16, 9, 17]   # 4-4 tie: 17 before 18
    assert E.pick_block_b(counts, size=2) == [10, 15]
    with pytest.raises(E.ListError):
        E.pick_block_b({9: 1, 10: 2})


def test_pick_is_deterministic_under_input_order():
    counts = {35: 4, 9: 4, 23: 6, 40: 2, 16: 5, 30: 5}
    assert E.pick_block_b(counts) == E.pick_block_b(dict(reversed(list(counts.items())))) == [23, 16, 30, 9]


# ── the tool ────────────────────────────────────────────────────────────


def write_run(root, run, by_ep):
    for ep, cands in by_ep.items():
        path = root / run / f"promos/candidates_E{ep:02d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"episode": ep, "candidates": cands}), encoding="utf-8")


def test_select_reads_only_eligible_episodes_from_both_runs(tmp_path):
    eligible = E.block_b_eligible()
    v1 = {ep: [cand(ep, 1, 5)] for ep in eligible}
    v2 = {ep: [cand(ep, 1, 5)] + [cand(ep, 10 + i, 14 + i) for i in range(n)] for n, ep in enumerate(eligible)}
    write_run(tmp_path, tool.V1, v1)
    write_run(tmp_path, tool.V2, v2)
    # sealed episodes are never read: files for them would fail the parse if they were opened
    for sealed in (31, 32, 2, 6):
        for run in (tool.V1, tool.V2):
            path = tmp_path / run / f"promos/candidates_E{sealed:02d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("NOT JSON", encoding="utf-8")
    picks, counts = tool.select(tmp_path)
    assert sorted(counts) == eligible and picks == [41, 40, 39, 38]        # growth with list position: largest last
    assert counts[41] == 16 and counts[9] == 0


def test_console_shows_only_the_four_picks(tmp_path, monkeypatch, capsys):
    counts = {ep: n for n, ep in enumerate(E.block_b_eligible())}
    picks = E.pick_block_b(counts)
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "select", lambda root=None: (picks, counts))
    assert tool.main([]) == 0
    out = capsys.readouterr().out
    for ep in picks:
        assert f"E{ep:02d}: {counts[ep]}" in out
    not_picked = [ep for ep in counts if ep not in picks]
    assert not any(f"E{ep:02d}" in out for ep in not_picked)               # nobody else is printed
    saved = json.loads((tmp_path / tool.OUT).read_text())
    assert saved["symmetric_difference_by_episode"] == {str(k): v for k, v in counts.items()}   # full table kept in the file
    assert saved["block_b_ranked"] == picks and "symmetric difference" in saved["rule"]


def test_match_rule_fresh_b_quotes_the_selection_rule_verbatim():
    from promo_finder.labelling import FRESH_B
    text = " ".join((ROOT / "eval/match_rule_fresh_b.md").read_text(encoding="utf-8").split())
    doc = " ".join(tool.__doc__.split())
    rule = doc.split("Selection rule (also stated verbatim in eval/match_rule_fresh_b.md):", 1)[1].split("The full per-episode table", 1)[0].strip()
    assert rule.startswith("Eligible episodes are all episodes except") and rule.endswith("No gold file or label is read.")
    assert rule in text                                                      # word for word
    assert "evaluation episodes = 15, 16, 17, 35" in text and "promos fully inside 15, 16, 17, 35" in text
    assert "eval/gold_fresh_b.csv" in text and "K = 2 × |G|" in text
    assert "reported separately and never pooled" in text and "scoring_runs = 1" in text
    assert [int(x) for x in "15, 16, 17, 35".split(", ")] == list(FRESH_B)
    raw = (ROOT / "eval/match_rule_fresh_b.md").read_bytes()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"\n")


def test_the_rule_text_in_the_tool_and_the_code_agree():
    doc = tool.__doc__
    for phrase in ("held-out episodes (1-4, 11-14, 26-29, 42-45)", "DEV episodes", "5-8, 19-22", "31-34",
                   "episodes 46 and above", "the 4 eligible episodes with the largest count", "lower",
                   "No gold file or label is read"):
        assert phrase in " ".join(doc.split())
