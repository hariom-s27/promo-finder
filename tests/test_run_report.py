"""P08b D1 aggregation: groups, counts and that no ids leak into the aggregates. All data invented."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p08b_run_report", ROOT / "tools/p08b_run_report.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def prow(pid, status="scored", lane="reserve", reasons=(), flags=None, segments=1):
    return {"promo_id": pid, "judge_status": status, "lane": lane, "needs_human_reasons": list(reasons),
            "flags": flags or {}, "segments": [{}] * segments}


def test_group_of_covers_every_episode_once():
    groups = [tool.group_of(e) for e in range(1, 51)]
    assert groups.count("held_out") == 16 and groups.count("fresh") == 4 and groups.count("fresh_b") == 4
    assert groups.count("other") == 26 and tool.group_of(35) == "fresh_b" and tool.group_of(36) == "other"
    assert tool.group_of(31) == tool.group_of(34) == "fresh" and tool.group_of(28) == "held_out"
    assert [tool.group_of(e) for e in (15, 16, 17)] == ["fresh_b"] * 3


def test_ranked_counts_by_group_without_ids():
    ranked = {"promos": [
        prow("P05-E01-001", lane="launch_batch"),
        prow("P05-E01-002", status="not_selected", lane="needs_human", reasons=["missing_evidence"]),
        prow("P05-E31-001", lane="needs_human", reasons=["blocking_resolution"], flags={"contains_blocking_resolution": True}),
        prow("P05-E32-001", flags={"extended": True}, segments=2),
        prow("P05-E32-002", status="failed_evidence", lane="needs_human", reasons=["missing_evidence", "blocking_resolution"],
             flags={"contains_blocking_resolution": True}),
        prow("P05-E05-001"), prow("P05-E40-003", status="not_selected")]}
    counts = tool.ranked_counts(ranked)
    held, fresh, other = counts["held_out"], counts["fresh"], counts["other"]
    assert (held["kept"], held["selected_for_judging"], held["scored"]) == (2, 1, 1)
    assert held["lanes"] == {"launch_batch": 1, "needs_human": 1} and held["needs_human_reasons"] == {"missing_evidence": 1}
    assert (fresh["kept"], fresh["scored"], fresh["failed_evidence"], fresh["extended"], fresh["montage"]) == (3, 2, 1, 1, 1)
    assert fresh["blocking_resolution_flagged"] == 2 and fresh["needs_human_reasons"] == {"blocking_resolution": 2, "missing_evidence": 1}
    assert (other["kept"], other["selected_for_judging"]) == (2, 1)
    assert "P05-" not in json.dumps(counts)                      # aggregates only


def test_build_counts_and_other_per_episode():
    def summary(generated, kept, **dropped):
        return {"generated": generated, "kept": kept, "dropped": {"checker": 1, "J4": 2, **dropped}, "extended_generated": 1}
    build = {"episodes": {"E01": summary(10, 3), "E02": summary(8, 0), "E31": summary(6, 2), "E05": summary(9, 4), "E07": summary(5, 0)}}
    counts = tool.build_counts(build)
    assert counts["held_out"] == {"episodes": 2, "generated": 18, "kept": 3, "empty_episodes": 1, "dropped": {"checker": 2, "J4": 4},
                                  "extended_generated": 2, "resolution_flagged_generated": 0}
    assert counts["fresh"]["episodes"] == 1 and counts["fresh"]["kept"] == 2
    assert counts["other"]["empty_episodes"] == 1 and counts["other"]["dropped"]["J4"] == 4
    assert tool.other_per_episode(build) == {"E05": 4, "E07": 0}   # held-out and fresh episodes never appear per episode
