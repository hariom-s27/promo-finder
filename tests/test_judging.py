from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

import pytest
import yaml

from promo_finder import judge_prompts as prompts, judging
from promo_finder.builder import build_episode
from promo_finder.config import PricingCfg, PurposeCfg, load_config
from promo_finder.llm import LLMClient, SchemaError, schema_errors
from promo_finder.understanding_common import write_json
from test_builder import bundle
from test_find import prepare_context
from test_llm import FakeClock, resp


def cold_answer(local="L01", answer="yes"):
    return {**{q: {"answer": answer if q not in ("orphan_line", "spoils_ending") else "no", "evidence": local} for q in prompts.QUESTIONS},
            "hook_rating": "3", "cliff_rating": "4", **{key: "invented meaning" for key in prompts.READER_FIELDS}}


def successful(data=None):
    return {"status": "ok", "answers": data or cold_answer()}


def setup(cfg, episode_factory):
    data = bundle(episode_factory)
    output, _ = build_episode(*data, cfg)
    prepare_context(cfg, [data[0]], baseline=False)
    write_json(cfg.root / "outputs/runs/dev/promos/candidates_E05.json", output)
    target = cfg.root / "config/p03_human_majorities.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump({"promos": {f"P03-E07-{i:03d}": dict.fromkeys(("Q1", "Q2", "Q3"), True) for i in range(1, 7)}}), encoding="utf-8")
    return data[0], output["candidates"][0]


class Provider:
    def __init__(self, missing=False, bad_cold=False, bad_fidelity=False, long=False):
        self.calls = []
        self.missing, self.bad_cold, self.bad_fidelity, self.long = missing, bad_cold, bad_fidelity, long
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        props = kwargs["response_format"]["json_schema"]["schema"]["properties"]
        if "answers" in props:
            ids = props["answers"]["items"]["properties"]["promo_id"]["enum"]
            data = {"answers": [] if self.missing else [{"promo_id": key, **{field: "invented meaning" for field in prompts.KEY_FIELDS}, "resolved_inside": "no"} for key in ids]}
            if self.long:
                for row in data["answers"]:
                    row["who"] = " ".join(["invented"] * 20)
        elif "hook_rating" in props:
            data = cold_answer()
            if self.bad_cold:
                data["hook_now"]["evidence"] = "L99"
            if self.long:
                data["reader_who"] = " ".join(["invented"] * 20)
        else:
            data = dict.fromkeys(("who", "stakes", "next"), "yes")
            if self.bad_fidelity:
                data["next"] = "invalid"
        return resp(json.dumps(data), model="invented-judge", pt=30, ct=20)


@pytest.fixture
def jcfg(write_config, monkeypatch):
    cfg = load_config(write_config(max_calls=100))
    cfg.purposes = {"answer_key": PurposeCfg(reasoning_effort="low", max_completion_tokens=6000),
                    "cold_judge": PurposeCfg(max_completion_tokens=800), "fidelity": PurposeCfg(max_completion_tokens=256)}
    cfg.pricing[cfg.active.picker] = PricingCfg(input_per_million_usd=.25, output_per_million_usd=2)
    monkeypatch.setattr(judging, "estimate_tokens", lambda text: len(text) // 4)
    return cfg


def client(cfg, provider):
    clock = FakeClock()
    return LLMClient(cfg, client_factory=lambda *args: provider, clock=clock, sleep=clock.sleep,
                     cache_dir=cfg.root / "outputs/runs/dev/judge/.llm_cache", token_estimator=lambda text: len(text) // 4)


def test_cold_request_contains_only_local_ids_and_fixed_prefix(episode_factory):
    ep = episode_factory(19, [(0, 10000), (10000, 20000)])
    first, second = prompts.shuffle(52, "invented", 0), prompts.shuffle(52, "invented", 1)
    a, schema, mapping = prompts.cold_request(ep.lines, first[1])
    b, _, _ = prompts.cold_request(ep.lines, second[1])
    serialized = json.dumps([a, schema])
    assert not re.search(r"E\d\d-L", serialized)
    assert not any(token in serialized for token in ('"episode"', '"rank"', '"score"', '"source"', "promo_id"))
    assert a[0]["content"].startswith(prompts.COLD_FIXED) and b[0]["content"].startswith(prompts.COLD_FIXED)
    assert a[0]["content"].endswith(prompts.QUESTIONS[first[1][-1]])
    assert mapping == {"L01": ep.lines[0].id, "L02": ep.lines[1].id}


def test_shuffle_is_reproducible_and_three_orders_differ():
    used = set()
    for run in range(3):
        seed, order = prompts.shuffle(52, "invented", run, used)
        assert set(order) == set(prompts.QUESTIONS)
        assert (seed, order) == prompts.shuffle(52, "invented", run, used)
        used.add(tuple(order))
    assert len(used) == 3


@pytest.mark.parametrize("mutation", ["type", "enum", "missing", "extra", "evidence", "rating", "reader"])
def test_every_field_code_validated(episode_factory, mutation):
    ep = episode_factory(5, [(0, 20000)])
    _, schema, _ = prompts.cold_request(ep.lines, list(prompts.QUESTIONS))
    data = cold_answer()
    if mutation == "type": data["hook_now"] = True
    elif mutation == "enum": data["hook_now"]["answer"] = "maybe"
    elif mutation == "missing": data.pop("standalone")
    elif mutation == "extra": data["extra"] = 1
    elif mutation == "evidence": data["hook_now"]["evidence"] = "L99"
    elif mutation == "rating": data["hook_rating"] = 3
    else: data["reader_who"] = 3
    assert schema_errors(data, schema)


def test_run_repeats_maps_evidence_and_fidelity(jcfg, episode_factory):
    ep, promo = setup(jcfg, episode_factory)
    provider = Provider(long=True)
    result = judging.run(jcfg, [ep], client(jcfg, provider))
    assert len(provider.calls) == 5  # one key, three cold, one fidelity
    rows = json.loads((jcfg.root / "outputs/runs/dev/judge/judge_E05.json").read_text())["items"]
    item = rows[0]
    assert item["aggregate"]["successful_runs"] == 3 and item["aggregate"]["flip_rate"] == 0
    assert item["runs"][0]["answers"]["hook_now"]["evidence"] == ep.lines[0].id
    assert len(item["runs"][0]["answers"]["reader_who"].split()) == 15
    assert item["runs"][0]["metadata"]["trims_by_field"]["reader_who"] == 1
    assert item["fidelity"]["cold"] is False and item["fidelity"]["status"] == "ok"
    key = json.loads((jcfg.root / "outputs/runs/dev/judge/answer_key_E05.json").read_text())["answers"][0]
    assert key["trims_by_field"]["who"] == 1 and len(key["who"].split()) == 15
    assert result["failed_runs_by_part"] == dict.fromkeys(("answer_key", "cold_judge", "fidelity"), 0)
    assert all(call["max_completion_tokens"] == 800 for call in provider.calls[1:4])
    assert all(call["temperature"] == .7 for call in provider.calls[1:])
    assert provider.calls[0]["reasoning_effort"] == "low"


def test_bad_runs_retry_once_fail_and_do_not_aggregate(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    provider = Provider(bad_cold=True)
    result = judging.run(jcfg, [ep], client(jcfg, provider))
    assert len(provider.calls) == 7 and result["failed_runs_by_part"]["cold_judge"] == 3
    item = json.loads((jcfg.root / "outputs/runs/dev/judge/judge_E05.json").read_text())["items"][0]
    assert item["aggregate"]["successful_runs"] == 0 and item["aggregate"]["hook_rating_mean"] is None
    assert item["fidelity"]["status"] == "skipped"


def test_missing_key_retries_once_then_records_missing(jcfg, episode_factory):
    ep, promo = setup(jcfg, episode_factory)
    provider = Provider(missing=True)
    summary = judging.run(jcfg, [ep], client(jcfg, provider))
    output = json.loads((jcfg.root / "outputs/runs/dev/judge/answer_key_E05.json").read_text())
    assert output["missing"] == [promo["promo_id"]] and len(provider.calls) == 5
    assert summary["failed_runs_by_part"]["answer_key"] == 1


def test_invalid_fidelity_excluded(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    provider = Provider(bad_fidelity=True)
    summary = judging.run(jcfg, [ep], client(jcfg, provider))
    assert summary["failed_runs_by_part"]["fidelity"] == 1 and len(provider.calls) == 6


def test_no_items_skips_key_and_all_calls(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    write_json(jcfg.root / "outputs/runs/dev/promos/candidates_E05.json", {"episode": 5, "candidates": []})
    provider = Provider()
    judging.run(jcfg, [ep], client(jcfg, provider))
    assert not provider.calls
    assert json.loads((jcfg.root / "outputs/runs/dev/judge/answer_key_E05.json").read_text())["status"] == "no items"


@pytest.mark.parametrize("changed,expected", [(0, 0), (1, .2), (2, .4), (5, 1)])
def test_flip_rate_is_share_of_disagreeing_questions(changed, expected):
    first, second, third = cold_answer(), cold_answer(), cold_answer()
    for q in list(prompts.QUESTIONS)[:changed]:
        third[q]["answer"] = "no" if first[q]["answer"] == "yes" else "yes"
    runs = [successful(first), successful(second), successful(third), {"status": "failed"}]
    agg = judging.aggregate(runs, 3)
    assert agg["flip_rate"] == expected and agg["failed_runs"] == 1
    assert agg["hook_rating_mean"] == 3


def test_single_run_flip_unmeasured_and_question_reliability():
    single = judging.aggregate([successful()])
    assert single["flip_rate"] is None
    data = cold_answer()
    data["hook_now"]["answer"] = "no"
    repeated = judging.aggregate([successful(), successful(), successful(data)], 3)
    result = judging.reliability([{"aggregate": single}, {"aggregate": repeated}])
    assert result["hook_now"] == {"flip_rate": 1, "flipped_items": 1, "measured_items": 1}


def test_human_agreement_maths_and_mean_threshold():
    human = {f"invented-{i}": {"Q1": i < 3, "Q2": True, "Q3": i % 2 == 0} for i in range(6)}
    items = [{"promo_id": key, "aggregate": judging.aggregate([successful()], 1)} for key in human]
    result = judging.agreement(items, human)
    assert result["questions"]["Q1"]["agree"] == 3
    assert result["questions"]["Q2"]["agree"] == 6
    assert result["questions"]["Q3"]["agree"] == 3
    assert len(result["per_promo"]) == 6


def test_dry_run_exact_schedule_cost_and_no_provider(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    result = judging.dry_run(jcfg, [ep])
    assert result["planned_calls"] == 5
    assert result["parts"]["cold_judge"]["output_budget_tokens"] == 2400
    assert result["parts"]["answer_key"]["estimated_usd"] > 0
    assert result["parts"]["fidelity"]["dependency_allowance_tokens"] == 512


def test_runtime_family_check_cannot_be_bypassed(jcfg):
    jcfg.models[jcfg.active.judge].family = " OPENAI "
    with pytest.raises(judging.FamilyRefused):
        judging.check_family(jcfg)


def test_reference_repeat_counts_and_no_double_count(jcfg):
    items = [{"promo_id": f"invented-{i}", "reference": i >= 3, "pre_score": 10-i} for i in range(5)]
    counts = judging.run_counts(items, jcfg)
    assert list(counts.values()) == [3, 3, 1, 3, 3]


def test_key_coverage_rejects_duplicates_and_missing():
    assert judging.coverage_errors({"answers": [{"promo_id": "a"}, {"promo_id": "a"}]}, ["a", "b"])
    assert not judging.coverage_errors({"answers": [{"promo_id": "b"}, {"promo_id": "a"}]}, ["a", "b"])


def test_schema_factories_have_no_unsupported_keywords(episode_factory):
    ep = episode_factory(5, [(0, 20000)])
    _, cold, _ = prompts.cold_request(ep.lines, list(prompts.QUESTIONS))
    _, fidelity = prompts.fidelity_request(dict.fromkeys(prompts.KEY_FIELDS, ""), dict.fromkeys(prompts.READER_FIELDS, ""))
    from promo_finder.cli import PING_SCHEMA
    serialized = json.dumps([prompts.key_schema(["invented"]), cold, fidelity, PING_SCHEMA])
    assert all('"'+key+'"' not in serialized for key in ("pattern", "minLength", "maxLength", "minItems", "maxItems"))


def test_failed_repeats_do_not_create_false_majority():
    yes, no = cold_answer(), cold_answer()
    no["hook_now"]["answer"] = "no"
    agg = judging.aggregate([successful(yes), successful(no), {"status": "failed"}], 3)
    assert agg["answers"]["hook_now"] is None and agg["flip_rate"] == .2
