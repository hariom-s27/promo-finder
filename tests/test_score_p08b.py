"""Fresh score-once safeguards; all labels, spans and episodes are invented fixtures."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from promo_finder import evaluation_lists as E, gold as G, ranking, scoring as S
from promo_finder.checker import LineIndex
from promo_finder.models import Line

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("score_p08b", ROOT / "tools/score_p08b.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def put(root, rel, doc):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def segment(ep, number):
    start = number * 8 + 1
    return {"episode": ep, "first_line_id": f"E{ep:02d}-L{start:03d}",
            "last_line_id": f"E{ep:02d}-L{start+5:03d}", "start_ms": (start-1)*5000, "end_ms": (start+5)*5000}


@pytest.fixture
def world(tmp_path, monkeypatch):
    index = LineIndex()
    for ep in (1, 15, 31):
        for n in range(1, 201):
            lid = f"E{ep:02d}-L{n:03d}"
            index[lid] = Line(id=lid, ep=ep, idx=n, scene=1, kind="action", text="x",
                              start_ms=(n-1)*5000, end_ms=n*5000)
    root = tmp_path / "repo"
    root.mkdir()
    for rel in tool.REQUIRED_HASHES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("invented metadata\n", encoding="utf-8", newline="\n")
    for block, (split, npos, nneg, suffix) in tool.BLOCKS.items():
        ep = split.episodes[0]
        for e in split.episodes:
            put(root, f"{tool.V1}/baseline/baseline_E{e:02d}.json",
                {"invented_timestamps": [0,1], "drops": [{"reasons": ["TOO_SHORT"]}], "sensitivity_drops": []})
        with (root / split.default_gold).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, G.HEADER, lineterminator="\n")
            writer.writeheader()
            for j in range(npos+nneg):
                s = segment(ep, j)
                writer.writerow({"gold_id": f"TEST-{j:02d}", "kind": "pos" if j<npos else "neg",
                                 "grade": 3 if j<npos else 0, "hook_type": sorted(G.HOOKS)[0] if j<npos else "",
                                 "cliff_type": sorted(G.CLIFFS)[0] if j<npos else "",
                                 "neg_code": "" if j<npos else sorted(G.NEG_CODES)[0],
                                 "seg1_start": s["first_line_id"], "seg1_end": s["last_line_id"], "rationale": "Invented reason."})
    ranked = {}
    for version, offset in (("v1", 1), ("v2", 0)):
        rows = [{"promo_id": f"TEST-{ep}-{j:02d}", "segments": [segment(ep,j)], "S": 1-j/100, "pre_score": 1}
                for ep in (1,15,31) for j in range(offset,offset+10)]
        rows = ranking.evaluation_order(rows)
        doc = {"promos": rows, "evaluation_order": [r["promo_id"] for r in rows]}
        ranked[version] = doc
        put(root, f"outputs/runs/{'full' if version=='v1' else 'full_v2'}/ranked/promos_dev.json", doc)
    base_rows = [{"episode": ep, "within_episode_rank": j+1, "spans": [[0,1]], "segments": [segment(ep,j)]}
                 for ep in (1,15,31) for j in range(10)]
    order = {"promos": base_rows, "sensitivity_promos": base_rows + [dict(base_rows[0], within_episode_rank=99)]}
    put(root, f"{tool.V1}/baseline/baseline_order.json", order)
    seal = {"fresh_episodes": list(tool.FRESH_SPLIT.episodes), "files": {}, "inputs": {}, "sealed_p08_held_out_lists": {}}
    for block, (split, npos, nneg, suffix) in tool.BLOCKS.items():
        target = {} if block=="b" else seal["files"]
        for version in (("v2",) if block=="held_out" else ("v1","v2")):
            name = f"tool_{version}_{suffix}"
            rows = E.tool_list(ranked[version], split.episodes)
            rel = f"{tool.EVALUATION}/{name}_L.json"
            p = put(root, rel, E.document(rows,"invented",32 if block=="held_out" else None))
            target[rel] = {"sha256": tool.sha(p), "count": len(rows)}
        if block!="held_out":
            rows = E.baseline_list(order,split.episodes)
            rel = f"{tool.EVALUATION}/baseline_{suffix}_L.json"
            p = put(root,rel,E.document(rows,"invented",None))
            target[rel] = {"sha256": tool.sha(p), "count": len(rows)}
        if block=="b":
            before = put(root,f"{tool.EVALUATION}/L_seal_before_block_b.json",{"invented":"previous"})
            seal["block_b"] = {"episodes":list(split.episodes),"files":target,
                               "selection":{"rule_file":"eval/match_rule_fresh_b.md", "rule_file_sha256":tool.sha(root/"eval/match_rule_fresh_b.md")},
                               "block_a_seal_sha256_before_block_b":tool.sha(before)}
    for name in ("tool_held_out_L.json","baseline_held_out_L.json"):
        rel = f"{tool.V1}/evaluation/{name}"
        p = put(root,rel,{"invented":"P08 unchanged"})
        seal["sealed_p08_held_out_lists"][rel] = {"sha256":tool.sha(p,True),"sha256_raw_on_disk":tool.sha(p)}
    for rel in (f"{tool.V1}/ranked/promos_dev.json",f"{tool.V2}/ranked/promos_dev.json",
                f"{tool.V1}/baseline/baseline_order.json","config/v2.yaml"):
        seal["inputs"][rel] = tool.sha(root/rel)
    put(root,f"{tool.V2}/run_manifest.json",{"status":"complete","stages":{"judge":{"status":"complete"}},
                                          "overlay_sha256":tool.sha(root/"config/v2.yaml")})
    gold = [S.GoldPromo(f"TEST-{j:02d}","pos",3,((1,j*40000,j*40000+30000),)) for j in range(16)]
    official = S.evaluate_list([],gold,32)
    official_path = put(root,"outputs/eval/metrics.json",{"scoring_runs":1,"tool":official,"baseline":official})
    seal_path = put(root,f"{tool.EVALUATION}/L_seal.json",seal)
    lines = ["| File | sha256 | Bytes |", "|---|---|---|"]
    for rel in sorted(tool.REQUIRED_HASHES)+["eval/gold_fresh.csv"]:
        p = root/rel
        lines.append(f"| {rel} | {tool.sha(p,True)} | {len(p.read_bytes())} |")
    (root/"eval/HASHES.md").write_text("\n".join(lines)+"\n",encoding="utf-8",newline="\n")
    monkeypatch.setattr(tool,"context",lambda r:index)
    return root,tool.sha(seal_path),tool.sha(official_path)


def test_verify_accepts_identical_duplicate_rows_and_checks_all_inputs(world):
    root,seal,p08 = world
    v = tool.verify(root,seal,p08)
    assert len(v["HASHES_rows"])==16 and v["duplicate_rows"]=={"eval/gold_fresh.csv":2}


@pytest.mark.parametrize("rel", ["eval/gold_fresh.csv","eval/gold_fresh_b.csv","eval/gold_rubric.md",
                                f"{tool.EVALUATION}/tool_v2_fresh_b_L.json", f"{tool.V1}/ranked/promos_dev.json",
                                f"{tool.EVALUATION}/L_seal_before_block_b.json","outputs/eval/metrics.json"])
def test_any_input_mismatch_stops_before_reserving_a_run(world,rel):
    root,seal,p08 = world
    with (root/rel).open("ab") as f:
        f.write(b" ")
    with pytest.raises(tool.Stop):
        tool.score(root,"a",seal,p08)
    assert not tool.paths(root,"a")[1].exists()


def test_conflicting_duplicate_row_is_rejected(world):
    root,seal,p08 = world
    path = root/"eval/HASHES.md"
    lines = path.read_text().splitlines()
    c = lines[-1].split("|")
    c[2] = " "+"0"*64+" "
    lines[-1] = "|".join(c)
    path.write_text("\n".join(lines)+"\n")
    with pytest.raises(tool.Stop):
        tool.verify(root,seal,p08)


def test_seal_itself_is_pinned_and_not_just_its_references(world):
    root,seal,p08 = world
    path = root/tool.EVALUATION/"L_seal.json"
    path.write_text(path.read_text()+" ")
    with pytest.raises(tool.Stop,match="approved seal"):
        tool.verify(root,seal,p08)


def test_blocks_have_independent_once_only_ledgers_and_k(world):
    root,seal,p08 = world
    a = tool.score(root,"a",seal,p08)
    b = tool.score(root,"b",seal,p08)
    assert (a["G"],a["negatives"],a["K"])==(8,2,16)
    assert (b["G"],b["negatives"],b["K"])==(4,1,8)
    assert b["systems"]["v2"]["primary"]["recall_at_K"]["k"]==4
    assert b["systems"]["v1"]["primary"]["recall_at_K"]["k"]==3
    assert b["paired"]["v2_vs_v1"]["bootstrap"]["mean_diff"]==.25
    before = {p:p.read_bytes() for block in ("a","b") for p in tool.paths(root,block)}
    for block in ("a","b"):
        ledger = tool.jload(tool.paths(root,block)[1])
        assert ledger["status"]=="completed" and ledger["scoring_runs"]==1
        with pytest.raises(tool.Stop,match="already attempted"):
            tool.score(root,block,seal,p08)
    assert all(p.read_bytes()==b for p,b in before.items())
    assert "diagnostics" not in tool.jload(tool.paths(root,"b")[2])
    assert "pilot" in b["block_b_disclosure"]
    assert b["baseline_context"]["invented_timestamps"]==8 and b["baseline_context"]["drop_reasons"]=={"TOO_SHORT":4}


def test_abort_consumes_only_that_block_and_cannot_be_silently_retried(world,monkeypatch):
    root,seal,p08 = world
    monkeypatch.setattr(tool,"compute",lambda *args: (_ for _ in ()).throw(tool.Stop("invented failure")))
    with pytest.raises(tool.Stop):
        tool.score(root,"b",seal,p08)
    metrics,ledger,public = tool.paths(root,"b")
    assert not metrics.exists() and not public.exists()
    assert tool.jload(ledger)["status"]=="aborted, no completed result"
    with pytest.raises(tool.Stop,match="already attempted"):
        tool.score(root,"b",seal,p08)
    assert not tool.paths(root,"a")[1].exists()


def test_forged_timestamp_is_rejected_even_if_the_list_hash_is_resealed(world):
    root,seal,p08 = world
    verification = tool.verify(root,seal,p08)
    rel = f"{tool.EVALUATION}/tool_v2_fresh_L.json"
    doc = tool.jload(root/rel)
    doc["promos"][0]["segments"][0]["end_ms"]+=1
    put(root,rel,doc)
    with pytest.raises(S.ScoringError,match="stored ms"):
        tool.compute(root,"a",verification,tool.context(root))


def test_split_membership_is_checked_before_prediction_reconstruction(world):
    root,seal,p08 = world
    rel = f"{tool.EVALUATION}/tool_v2_fresh_L.json"
    doc = tool.jload(root/rel)
    doc["promos"][0]["segments"][0]["episode"]=15
    put(root,rel,doc)
    with pytest.raises(tool.Stop,match="outside block"):
        tool.load_predictions(root,"tool_v2_fresh",tool.FRESH_SPLIT,tool.context(root),{"count":10})


def test_p10_keeps_frozen_top_k_matching_when_k_is_less_than_ten():
    gold = [S.GoldPromo("TEST", "pos",3,((1,0,30000),))]
    preds = [S.PredPromo(i,f"X-{i}",((1,100000,130000),)) for i in range(1,9)]
    preds.append(S.PredPromo(9,"match-after-K",((1,0,30000),)))
    ev = tool.evaluate(preds,gold,8)
    assert ev["primary"]["precision_at_10"]["k"]==0
    assert ev["primary"]["precision_at_10"]["n"]==9
    assert "wilson95" in ev["primary"]["precision_at_10"]


def test_posthoc_uses_stored_official_results_without_recomputing_them(world):
    root,seal,p08 = world
    original = (root/"outputs/eval/metrics.json").read_bytes()
    post = tool.score(root,"held_out",seal,p08)
    assert post["label"]=="post-hoc (after seeing v1 results)"
    assert post["systems"]["v1_official"]==json.loads(original)["tool"]
    assert (root/"outputs/eval/metrics.json").read_bytes()==original
    assert not tool.paths(root,"a")[1].exists() and not tool.paths(root,"b")[1].exists()
