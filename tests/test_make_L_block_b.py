"""P08b fresh block B: its L files are written once and sealed before any block B gold exists. Invented data."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from promo_finder import evaluation_lists as E
from promo_finder.labelling import FRESH_B
from test_make_L import BASELINE, ranked, row, seg, tool

ROOT = Path(__file__).resolve().parents[1]
def prow(pid, eps, start=0, **kw):
    """A ranked row whose spans differ between promos through `start` (row() gives every promo the same span)."""
    out = row(pid, eps, **kw)
    out["segments"] = [seg(e, start, start + 30000) for e in eps]
    return out


ROWS_V1 = [prow("B-31", [31], S=0.9), prow("B-15", [15], S=0.8), prow("B-16", [16], S=0.7), prow("B-35", [35], S=0.6),
           prow("B-05", [5], S=0.5), prow("B-15b", [15], 40000, pre=1.0), prow("B-17-18", [17, 18], pre=0.9),
           prow("B-17", [17], pre=0.8)]
ROWS_V2 = [prow("V-31", [31], S=0.9), prow("V-15", [15], S=0.8), prow("V-16x", [16], 50000, S=0.75, reasons=["blocking_resolution"]),
           prow("V-16", [16], S=0.7), prow("V-35", [35], S=0.6), prow("V-05", [5], S=0.5), prow("V-15b", [15], 40000, pre=1.0),
           prow("V-35-36", [35, 36], pre=0.95), prow("V-17", [17], pre=0.8), prow("V-17x", [17], 60000, pre=0.7)]
BASELINE_B = {"promos": BASELINE["promos"] + [
    {"episode": 15, "within_episode_rank": 1, "spans": [[0, 1]], "segments": [seg(15)], "rank": 4},
    {"episode": 35, "within_episode_rank": 1, "spans": [[0, 1]], "segments": [seg(35)], "rank": 5},
    {"episode": 17, "within_episode_rank": 1, "spans": [[0, 1]], "segments": [seg(17), seg(18)], "rank": 6}]}


def candidates(ep, extra=0, base=1):
    def one(i):
        return {"promo_id": f"P05-E{ep:02d}-{i:03d}", "segments": [
            {"episode": ep, "first_line_id": f"E{ep:02d}-L{i:03d}", "last_line_id": f"E{ep:02d}-L{i + 4:03d}"}]}
    return [one(i) for i in range(1, base + 1)] + [one(100 + i) for i in range(extra)]


@pytest.fixture
def world_b(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy2(ROOT / "config/v2.yaml", root / "config/v2.yaml")
    sha = hashlib.sha256((root / "config/v2.yaml").read_bytes()).hexdigest()
    (root / "eval").mkdir()
    (root / "eval/HASHES.md").write_text(f"| File | sha256 | Bytes |\n|---|---|---|\n| config/v2.yaml | {sha} | 766 |\n", encoding="utf-8")
    shutil.copy2(ROOT / "eval/match_rule_fresh_b.md", root / "eval/match_rule_fresh_b.md")
    for run, rows in (("full", ROWS_V1), ("full_v2", ROWS_V2)):
        base = root / "outputs/runs" / run
        (base / "ranked").mkdir(parents=True)
        (base / "ranked/promos_dev.json").write_text(json.dumps(ranked(rows)), encoding="utf-8")
    (root / "outputs/runs/full/baseline").mkdir(parents=True)
    (root / "outputs/runs/full/baseline/baseline_order.json").write_text(json.dumps(BASELINE_B), encoding="utf-8")
    manifest = {"status": "complete", "overlay_sha256": sha, "stages": {"judge": {"status": "complete"}}}
    (root / "outputs/runs/full_v2/run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    # builder output for every eligible episode: block B episodes differ most between v1 and v2
    for n, ep in enumerate(E.block_b_eligible()):
        extra = {15: 3, 16: 3, 17: 6, 35: 4}.get(ep, n % 2)
        for run, count in (("full", 0), ("full_v2", extra)):
            path = root / "outputs/runs" / run / f"promos/candidates_E{ep:02d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"episode": ep, "candidates": candidates(ep, count)}), encoding="utf-8")
    sealed = {}
    (root / "outputs/runs/full/evaluation").mkdir()
    for name in ("tool_held_out_L.json", "baseline_held_out_L.json"):
        path = root / "outputs/runs/full/evaluation" / name
        path.write_text(json.dumps({"K": 32, "count": 2, "order_source": "x", "promos": [1, 2]}), encoding="utf-8")
        sealed[f"outputs/runs/full/evaluation/{name}"] = E.lf_sha256_file(path)
    tool.build(root, sealed, out=lambda line: None)          # block A first, as in the real run
    return root, sealed


def noop(line):
    pass


# ── a clean block B build ───────────────────────────────────────────────


def test_block_b_lists_are_written_once_and_sealed(world_b):
    root, sealed = world_b
    seal_path = root / "outputs/runs/full_v2/evaluation/L_seal.json"
    before_bytes, before = seal_path.read_bytes(), json.loads(seal_path.read_text())
    lines = []
    seal = tool.build_block_b(root, sealed, out=lines.append)
    evaluation = root / "outputs/runs/full_v2/evaluation"
    assert sorted(p.name for p in evaluation.iterdir()) == sorted([
        "L_seal.json", "L_seal_before_block_b.json", "baseline_fresh_L.json", "tool_v1_fresh_L.json", "tool_v2_fresh_L.json",
        "tool_v2_held_out_L.json", "baseline_fresh_b_L.json", "tool_v1_fresh_b_L.json", "tool_v2_fresh_b_L.json"])
    docs = {Path(rel).name: json.loads((root / rel).read_text()) for rel in seal["block_b"]["files"]}
    # only promos fully inside 15, 16, 17, 35, in the frozen order; crossings out of the block are excluded
    assert [p["promo_id"] for p in docs["tool_v2_fresh_b_L.json"]["promos"]] == ["V-15", "V-16x", "V-16", "V-35", "V-15b", "V-17", "V-17x"]
    assert [p["promo_id"] for p in docs["tool_v1_fresh_b_L.json"]["promos"]] == ["B-15", "B-16", "B-35", "B-15b", "B-17"]
    assert [p["episode"] for p in docs["baseline_fresh_b_L.json"]["promos"]] == [15, 35]
    assert all(d["K"] is None for d in docs.values()) and docs["tool_v2_fresh_b_L.json"]["count"] == 7
    for rel, row_ in seal["block_b"]["files"].items():
        assert E.lf_sha256_file(root / rel) == E.sha256_file(root / rel) == row_["sha256"]
    # block A is untouched, and the previous seal is kept byte for byte
    previous = evaluation / "L_seal_before_block_b.json"
    assert previous.read_bytes() == before_bytes
    assert seal["block_b"]["block_a_seal_sha256_before_block_b"] == hashlib.sha256(before_bytes).hexdigest()
    assert {k: v for k, v in seal.items() if k != "block_b"} == before
    assert json.loads(seal_path.read_text()) == seal
    block = seal["block_b"]
    assert block["episodes"] == list(FRESH_B) and block["selection"]["label_files_read"] == 0
    assert block["selection"]["gold_file_exists"] is False and block["selection"]["reproduced_from_builder_output"] is True
    assert block["selection"]["rule_file_sha256"] == hashlib.sha256((root / "eval/match_rule_fresh_b.md").read_bytes()).hexdigest()
    diff = block["v1_vs_v2_difference"]
    assert (diff["v1_promos"], diff["v2_promos"]) == (5, 7) and diff["only_in_v1"] == 0 and diff["only_in_v2"] == 2
    assert diff["positions_with_same_span"] == 1 and diff["first_differing_position"] == 2
    text = "\n".join(lines)
    assert "tool_v2_fresh_b_L.json: 7 promos in 4 episodes, 1 flagged blocking_resolution" in text
    assert not re.search(r"V-\d|B-\d|E\d\d-L|P05-", text)                      # counts only


def test_block_b_is_write_once(world_b):
    root, sealed = world_b
    tool.build_block_b(root, sealed, out=noop)
    snapshot = {p.name: p.read_bytes() for p in (root / "outputs/runs/full_v2/evaluation").iterdir()}
    with pytest.raises(tool.Stop, match="already sealed"):
        tool.build_block_b(root, sealed, out=noop)
    assert {p.name: p.read_bytes() for p in (root / "outputs/runs/full_v2/evaluation").iterdir()} == snapshot


def test_block_b_never_reads_a_label_file(world_b, monkeypatch):
    root, sealed = world_b
    real_text, real_bytes = Path.read_text, Path.read_bytes

    def guard(real):
        def wrapper(self, *a, **k):
            if "gold" in self.name.lower():
                pytest.fail(f"label file read: {self.name}")
            return real(self, *a, **k)
        return wrapper

    monkeypatch.setattr(Path, "read_text", guard(real_text))
    monkeypatch.setattr(Path, "read_bytes", guard(real_bytes))
    tool.build_block_b(root, sealed, out=noop)


# ── what stops it, before anything is written ───────────────────────────


@pytest.mark.parametrize("case", ["gold_exists", "no_seal", "block_a_list_changed", "input_changed", "selection_changed",
                                  "rule_missing", "run_incomplete", "overlay_changed", "sealed_p08_changed"])
def test_block_b_preconditions(world_b, case):
    root, sealed = world_b
    evaluation = root / "outputs/runs/full_v2/evaluation"
    if case == "gold_exists":
        (root / "eval/gold_fresh_b.csv").write_bytes(b"")           # existence alone must stop it (it is never opened)
    elif case == "no_seal":
        (evaluation / "L_seal.json").unlink()
    elif case == "block_a_list_changed":
        (evaluation / "tool_v2_fresh_L.json").write_text("{}", encoding="utf-8")
    elif case == "input_changed":
        path = root / "outputs/runs/full/ranked/promos_dev.json"
        path.write_text(path.read_text() + " ", encoding="utf-8")
    elif case == "selection_changed":
        path = root / "outputs/runs/full_v2/promos/candidates_E09.json"
        path.write_text(json.dumps({"episode": 9, "candidates": candidates(9, 50)}), encoding="utf-8")
    elif case == "rule_missing":
        (root / "eval/match_rule_fresh_b.md").unlink()
    elif case == "run_incomplete":
        path = root / "outputs/runs/full_v2/run_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["status"] = "failed"
        path.write_text(json.dumps(manifest))
    elif case == "overlay_changed":
        (root / "config/v2.yaml").write_text("version: 2\n", encoding="utf-8")
    else:
        (root / "outputs/runs/full/evaluation/tool_held_out_L.json").write_text("{}", encoding="utf-8")
    snapshot = {p.name: p.read_bytes() for p in evaluation.iterdir()}
    with pytest.raises(tool.Stop):
        tool.build_block_b(root, sealed, out=noop)
    assert {p.name: p.read_bytes() for p in evaluation.iterdir()} == snapshot       # nothing written, nothing changed
    assert not list(evaluation.glob("*_b_L.json")) and not (evaluation / "L_seal_before_block_b.json").exists()
    assert case == "no_seal" or "block_b" not in json.loads((evaluation / "L_seal.json").read_text())


def test_main_dispatch_runs_block_b_only_on_request(world_b, monkeypatch, capsys):
    root, sealed = world_b
    monkeypatch.setattr(tool, "ROOT", root)
    monkeypatch.setattr(tool, "SEALED_P08", sealed)
    ran = []
    monkeypatch.setattr(tool, "build_block_b", lambda *a, **k: ran.append("b"))
    monkeypatch.setattr(tool, "build", lambda *a, **k: ran.append("a"))
    assert tool.main(["block-b"]) == 0 and tool.main([]) == 0
    assert ran == ["b", "a"]
