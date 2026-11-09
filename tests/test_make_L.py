"""P08b D2: evaluation lists L and their seal. All promos, episodes and ids are invented."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

from promo_finder import evaluation_lists as E

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_L", ROOT / "tools/make_L.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def seg(ep, start=0, end=30000):
    return {"episode": ep, "start_ms": start, "end_ms": end, "first_line_id": f"E{ep:02d}-L001", "last_line_id": f"E{ep:02d}-L009"}


def row(pid, eps, S=None, pre=1.0, reasons=()):
    return {"promo_id": pid, "segments": [seg(e) for e in eps], "S": S, "pre_score": pre, "needs_human_reasons": list(reasons)}


def ranked(rows):
    """A ranked document whose stored order is the frozen rule: S descending, then unscored by pre_score."""
    from promo_finder import ranking
    ordered = ranking.evaluation_order(rows)
    return {"promos": ordered, "evaluation_order": [r["promo_id"] for r in ordered]}


ROWS_V2 = [row("A-31", [31], S=0.9, reasons=["blocking_resolution"]), row("A-28", [28], S=0.8), row("A-05", [5], S=0.7),
           row("A-32", [32], S=0.6), row("A-34-35", [34, 35], S=0.55), row("A-33", [33], pre=2.0),
           row("A-01", [1], pre=1.5, reasons=["blocking_resolution"]), row("A-30-31", [30, 31], pre=1.2),
           row("A-31b", [31], pre=1.0)]
ROWS_V1 = [row("B-31", [31], S=0.9), row("B-02", [2], S=0.5), row("B-33", [33], pre=1.0)]
BASELINE = {"promos": [{"episode": 31, "within_episode_rank": 1, "spans": [[0, 1]], "segments": [seg(31)], "rank": 1},
                       {"episode": 5, "within_episode_rank": 1, "spans": [[0, 1]], "segments": [seg(5)], "rank": 2},
                       {"episode": 33, "within_episode_rank": 1, "spans": [[0, 1]], "segments": [seg(33)], "rank": 3}]}


# ── pure functions ──────────────────────────────────────────────────────


def test_tool_list_keeps_only_promos_fully_inside_in_stored_order():
    fresh = E.tool_list(ranked(ROWS_V2), [31, 32, 33, 34])
    assert [r["promo_id"] for r in fresh] == ["A-31", "A-32", "A-33", "A-31b"]
    assert [r["rank"] for r in fresh] == [1, 2, 3, 4]               # position in L, not the global rank
    assert set(fresh[0]) == {"rank", "promo_id", "segments"}
    held = E.tool_list(ranked(ROWS_V2), [1, 28])
    assert [r["promo_id"] for r in held] == ["A-28", "A-01"]
    assert E.tool_list(ranked(ROWS_V2), [40]) == []


def test_crossing_out_of_the_set_and_empty_segments_are_excluded():
    rows = ROWS_V2 + [{"promo_id": "A-empty", "segments": [], "S": None, "pre_score": 0.1, "needs_human_reasons": []}]
    ids = [r["promo_id"] for r in E.tool_list(ranked(rows), [31, 32, 33, 34])]
    assert "A-34-35" not in ids and "A-30-31" not in ids and "A-empty" not in ids


def test_lane_labels_never_reorder_the_list():
    flagged_first = E.tool_list(ranked(ROWS_V2), [31, 32])
    assert flagged_first[0]["promo_id"] == "A-31"                    # flagged needs_human promo keeps its S rank
    plain = [dict(r, needs_human_reasons=[]) for r in ROWS_V2]
    assert [r["promo_id"] for r in E.tool_list(ranked(plain), [31, 32, 33, 34])] == ["A-31", "A-32", "A-33", "A-31b"]


def test_a_stored_order_that_breaks_the_frozen_rule_is_refused():
    doc = ranked(ROWS_V2)
    swapped = dict(doc, evaluation_order=[doc["evaluation_order"][1], doc["evaluation_order"][0], *doc["evaluation_order"][2:]])
    with pytest.raises(E.ListError, match="stored evaluation order"):
        E.tool_list(swapped, [31])
    wrong = dict(doc, promos=list(reversed(doc["promos"])), evaluation_order=list(reversed(doc["evaluation_order"])))
    with pytest.raises(E.ListError, match="frozen ordering rule"):
        E.tool_list(wrong, [31])
    dup = dict(doc, promos=doc["promos"] + [doc["promos"][0]], evaluation_order=doc["evaluation_order"] + [doc["evaluation_order"][0]])
    with pytest.raises(E.ListError):
        E.tool_list(dup, [31])


def test_baseline_list_keeps_its_own_order_and_fields():
    rows = E.baseline_list(BASELINE, [31, 32, 33, 34])
    assert [(r["rank"], r["episode"]) for r in rows] == [(1, 31), (2, 33)]
    assert set(rows[0]) == {"rank", "episode", "within_episode_rank", "spans", "segments"}


def test_write_new_is_write_once_and_returns_the_byte_hash(tmp_path):
    path = tmp_path / "x_L.json"
    doc = E.document(E.tool_list(ranked(ROWS_V2), [31]), "invented source", None)
    sha = E.write_new(path, doc)
    assert sha == hashlib.sha256(path.read_bytes()).hexdigest() and b"\r" not in path.read_bytes()
    assert json.loads(path.read_text()) == {"K": None, "count": 2, "order_source": "invented source", "promos": doc["promos"]}
    with pytest.raises(E.ListError, match="already exists"):
        E.write_new(path, doc)


# ── the tool ────────────────────────────────────────────────────────────


@pytest.fixture
def world(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy2(ROOT / "config/v2.yaml", root / "config/v2.yaml")
    sha = hashlib.sha256((root / "config/v2.yaml").read_bytes()).hexdigest()
    (root / "eval").mkdir()
    (root / "eval/HASHES.md").write_text(f"| File | sha256 | Bytes |\n|---|---|---|\n| config/v2.yaml | {sha} | 766 |\n", encoding="utf-8")
    for run, rows in (("full", ROWS_V1), ("full_v2", ROWS_V2)):
        base = root / "outputs/runs" / run
        (base / "ranked").mkdir(parents=True)
        (base / "ranked/promos_dev.json").write_text(json.dumps(ranked(rows)), encoding="utf-8")
    (root / "outputs/runs/full/baseline").mkdir(parents=True)
    (root / "outputs/runs/full/baseline/baseline_order.json").write_text(json.dumps(BASELINE), encoding="utf-8")
    manifest = {"status": "complete", "overlay_sha256": sha, "stages": {"understand": {"status": "complete"}, "judge": {"status": "complete"}}}
    (root / "outputs/runs/full_v2/run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    sealed = {}
    (root / "outputs/runs/full/evaluation").mkdir()
    for name in ("tool_held_out_L.json", "baseline_held_out_L.json"):
        path = root / "outputs/runs/full/evaluation" / name
        path.write_text(json.dumps({"K": 32, "count": 2, "order_source": "x", "promos": [1, 2]}), encoding="utf-8")
        sealed[f"outputs/runs/full/evaluation/{name}"] = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return root, sealed


def test_build_writes_four_lists_and_a_seal_with_counts_only_on_the_console(world):
    root, sealed = world
    lines = []
    seal = tool.build(root, sealed, out=lines.append)
    evaluation = root / "outputs/runs/full_v2/evaluation"
    assert sorted(p.name for p in evaluation.iterdir()) == [
        "L_seal.json", "baseline_fresh_L.json", "tool_v1_fresh_L.json", "tool_v2_fresh_L.json", "tool_v2_held_out_L.json"]
    for rel, row in seal["files"].items():
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == row["sha256"]
    docs = {Path(rel).name: json.loads((root / rel).read_text()) for rel in seal["files"]}
    assert docs["tool_v2_held_out_L.json"]["K"] == 32
    assert docs["tool_v2_fresh_L.json"]["K"] is None and docs["tool_v1_fresh_L.json"]["K"] is None
    assert docs["tool_v2_fresh_L.json"]["count"] == 4 and docs["tool_v1_fresh_L.json"]["count"] == 2
    assert docs["baseline_fresh_L.json"]["count"] == 2 and docs["tool_v2_held_out_L.json"]["count"] == 2
    assert seal["label_files_read"] == 0 and seal["sealed_p08_held_out_lists"].keys() == sealed.keys()
    assert json.loads((evaluation / "L_seal.json").read_text()) == seal
    assert seal["inputs"]["config/v2.yaml"] == hashlib.sha256((root / "config/v2.yaml").read_bytes()).hexdigest()
    text = "\n".join(lines)
    assert "tool_v2_fresh_L.json: 4 promos in 3 episodes, 1 flagged blocking_resolution" in text
    assert not re.search(r"A-\d|B-\d|E\d\d-L|P05-", text)          # no promo ids, spans or line ids


def test_build_never_reads_a_label_file(world, monkeypatch):
    root, sealed = world
    real_read_text, real_read_bytes = Path.read_text, Path.read_bytes

    def guard(real):
        def wrapper(self, *a, **k):
            if "gold" in self.name.lower():
                pytest.fail(f"label file read: {self.name}")
            return real(self, *a, **k)
        return wrapper

    monkeypatch.setattr(Path, "read_text", guard(real_read_text))
    monkeypatch.setattr(Path, "read_bytes", guard(real_read_bytes))
    tool.build(root, sealed, out=lambda line: None)
    sources = (ROOT / "tools/make_L.py").read_text(encoding="utf-8") + (ROOT / "src/promo_finder/evaluation_lists.py").read_text(encoding="utf-8")
    # the only label-file name in the code is block B's gold path, and it is only tested for existence (never read)
    assert set(re.findall(r"gold[\w]*\.csv", sources)) == {"gold_fresh_b.csv"}
    assert sources.count('"eval/gold_fresh_b.csv").exists()') == 1


@pytest.mark.parametrize("case", ["incomplete", "overlay_changed", "manifest_overlay", "sealed_list_changed", "already_written"])
def test_preconditions_stop_before_writing(world, case):
    root, sealed = world
    manifest_path = root / "outputs/runs/full_v2/run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if case == "incomplete":
        manifest["stages"]["judge"]["status"] = "failed"
        manifest_path.write_text(json.dumps(manifest))
    elif case == "overlay_changed":
        (root / "config/v2.yaml").write_text("version: 2\n", encoding="utf-8")
    elif case == "manifest_overlay":
        manifest["overlay_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    elif case == "sealed_list_changed":
        (root / "outputs/runs/full/evaluation/tool_held_out_L.json").write_text("{}", encoding="utf-8")
    else:
        tool.build(root, sealed, out=lambda line: None)
    with pytest.raises(tool.Stop):
        tool.build(root, sealed, out=lambda line: None)
    if case != "already_written":
        assert not (root / "outputs/runs/full_v2/evaluation").exists()


def test_a_bad_stored_order_stops_the_tool_before_any_list_is_written(world):
    root, sealed = world
    path = root / "outputs/runs/full_v2/ranked/promos_dev.json"
    doc = json.loads(path.read_text())
    doc["evaluation_order"][0], doc["evaluation_order"][1] = doc["evaluation_order"][1], doc["evaluation_order"][0]
    path.write_text(json.dumps(doc))
    with pytest.raises(E.ListError):
        tool.build(root, sealed, out=lambda line: None)
    assert not list((root / "outputs/runs/full_v2").glob("evaluation/*_L.json"))


def test_sealed_lists_written_with_crlf_are_matched_by_their_lf_hash(world):
    """P08 recorded LF-normalized hashes of files that sit on disk with CRLF; both must be accepted and kept."""
    root, sealed = world
    for rel in sealed:
        path = root / rel
        path.write_bytes(json.dumps({"K": 32, "count": 2, "order_source": "x", "promos": [1, 2]}, indent=2).replace("\n", "\r\n").encode())
        sealed[rel] = E.lf_sha256_file(path)
        assert E.sha256_file(path) != sealed[rel]                    # raw bytes differ from the recorded value
    before = {rel: (root / rel).read_bytes() for rel in sealed}
    seal = tool.build(root, sealed, out=lambda line: None)
    for rel, row in seal["sealed_p08_held_out_lists"].items():
        assert row["sha256"] == sealed[rel] and row["sha256_raw_on_disk"] == E.sha256_file(root / rel)
        assert (root / rel).read_bytes() == before[rel]              # never rewritten
    for rel, row in seal["files"].items():                           # new lists are LF-only: both hashes agree
        assert b"\r" not in (root / rel).read_bytes() and row["sha256"] == E.lf_sha256_file(root / rel)


def test_lf_hash_helper_and_a_changed_list_still_stops(tmp_path):
    path = tmp_path / "a.json"
    path.write_bytes(b"{\r\n}\r\n")
    assert E.lf_sha256_file(path) == hashlib.sha256(b"{\n}\n").hexdigest() != E.sha256_file(path)
