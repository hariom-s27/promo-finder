"""P08b v2: config overlay, F2 (extend) and F5b (flag unless at the end) in the builder, and lane routing.

All episodes, lines and speakers are invented."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from promo_finder import builder, cli, diagnostic as D, judging, ranking
from promo_finder.config import ConfigError, load_config, read_overlay
from promo_finder.run_context import fingerprints
from test_diagnostic import add_cliff, bundle, end_bundle, mark, random_bundle, short_bundle
from test_judging import Provider, client, jcfg, setup  # noqa: F401  (jcfg is a fixture)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "tests/fixtures/golden_v1_builder_digests.json").read_text(encoding="utf-8"))
V2 = {"too_short_mode": "extend", "resolution_mode": "flag_unless_end"}


@pytest.fixture
def v1cfg(write_config):
    return load_config(write_config())


@pytest.fixture
def v2cfg(write_config):
    """The real config/v2.yaml applied to the fake test config."""
    cfgp = write_config()
    (cfgp.parent / "config").mkdir()
    shutil.copy2(ROOT / "config/v2.yaml", cfgp.parent / "config/v2.yaml")
    return load_config(cfgp, overlay="config/v2.yaml")


def build(data, cfg):
    return builder.build_episode(*data, cfg, None)


# ── overlay ─────────────────────────────────────────────────────────────


def test_real_v2_file_sets_exactly_the_two_switches(v1cfg, v2cfg):
    assert read_overlay(ROOT / "config/v2.yaml") == {"version": 2, "builder": V2}
    assert (v1cfg.builder.too_short_mode, v1cfg.builder.resolution_mode) == ("drop", "drop")
    assert (v2cfg.builder.too_short_mode, v2cfg.builder.resolution_mode) == ("extend", "flag_unless_end")
    # nothing else differs between the two configurations
    a, b = v1cfg.model_dump(), v2cfg.model_dump()
    for key in V2:
        a["builder"].pop(key), b["builder"].pop(key)
    assert a == b


def test_real_config_yaml_defaults_are_v1():
    cfg = load_config()
    assert (cfg.builder.too_short_mode, cfg.builder.resolution_mode) == ("drop", "drop")
    v2 = load_config(overlay="config/v2.yaml")
    assert v2.builder.too_short_mode == "extend" and v2.builder.resolution_mode == "flag_unless_end"
    assert v2.builder.penalties == cfg.builder.penalties and v2.judge == cfg.judge and v2.models == cfg.models


@pytest.mark.parametrize("text", [
    "models: {x: 1}\n", "active: {picker: a}\n", "judge: {temperature: 1.0}\n", "purposes: {}\n",
    "builder: {dedupe_tiou: 0.5}\n", "builder: {max_per_episode: 9}\n", "builder: {penalties: {montage: 0}}\n",
    "builder: {j4_mode: flag}\n", "builder: {resolution_penalty: 0.1}\n", "version: x\n", "version: true\n",
    "- a\n- b\n", "builder: [1]\n", "builder: {too_short_mode: stretch}\n", "builder: {resolution_mode: flag}\n"])
def test_overlay_rejects_anything_but_the_two_switches(write_config, text):
    cfgp = write_config()
    (cfgp.parent / "config").mkdir()
    (cfgp.parent / "config/bad.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfgp, overlay="config/bad.yaml")


def test_overlay_file_must_exist_and_stay_inside_the_project(write_config, tmp_path_factory):
    cfgp = write_config()
    with pytest.raises(ConfigError, match="not found"):
        load_config(cfgp, overlay="config/missing.yaml")
    outside = tmp_path_factory.mktemp("outside") / "v2.yaml"
    shutil.copy2(ROOT / "config/v2.yaml", outside)
    with pytest.raises(ConfigError, match="inside the project"):
        load_config(cfgp, overlay=outside)


def test_overlay_error_names_keys_never_values(write_config):
    cfgp = write_config()
    (cfgp.parent / "config").mkdir()
    (cfgp.parent / "config/bad.yaml").write_text("builder: {dedupe_tiou: 0.123456}\nmodels: {x: secret-value}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_config(cfgp, overlay="config/bad.yaml")
    assert "models" in str(info.value) and "secret-value" not in str(info.value) and "0.123456" not in str(info.value)


def test_overlay_hash_is_recorded_only_for_overlay_runs(v1cfg, v2cfg):
    assert "overlay_sha256" not in fingerprints(v1cfg) and "overlay_path" not in fingerprints(v1cfg)
    record = fingerprints(v2cfg)
    assert record["overlay_path"] == "config/v2.yaml"
    assert record["overlay_sha256"] == hashlib.sha256((ROOT / "config/v2.yaml").read_bytes()).hexdigest()
    deleted = v2cfg.model_copy(deep=True)
    for name in ("score_formula.yaml", "eval_order.yaml", "baseline.yaml"):   # so the required check reaches the overlay
        shutil.copy2(ROOT / "config" / name, deleted.root / "config" / name)
    assert fingerprints(deleted, required=True)["overlay_sha256"] == record["overlay_sha256"]
    (deleted.root / "config/v2.yaml").unlink()
    assert fingerprints(deleted)["overlay_sha256"] is None
    from promo_finder.understanding_common import UnderstandingError
    with pytest.raises(UnderstandingError, match="overlay missing"):
        fingerprints(deleted, required=True)


def test_cli_overlay_flag_on_build_rank_run_only(write_config, monkeypatch, capsys):
    cfgp = write_config()
    (cfgp.parent / "config").mkdir()
    shutil.copy2(ROOT / "config/v2.yaml", cfgp.parent / "config/v2.yaml")
    (cfgp.parent / "config/bad.yaml").write_text("models: {x: 1}\n", encoding="utf-8")
    monkeypatch.setenv("KUKU_CONFIG", str(cfgp))
    seen = []
    monkeypatch.setattr(builder, "cmd_build", lambda cfg, args: seen.append(cfg) or 0)
    assert cli.main(["build", "--eps", "5", "--config-overlay", "config/v2.yaml"]) == 0
    assert seen[0].builder.too_short_mode == "extend" and seen[0].builder.resolution_mode == "flag_unless_end"
    assert cli.main(["build", "--eps", "5"]) == 0 and seen[1].builder.too_short_mode == "drop"
    assert cli.main(["build", "--eps", "5", "--config-overlay", "config/bad.yaml"]) == 2
    assert "config error: overlay key not allowed: models" in capsys.readouterr().err
    for command in ("rank", "run"):
        # accepted by the parser (the run then stops for an unrelated reason or succeeds); never an argparse error
        try:
            cli.main([command, "--eps", "5", "--config-overlay", "config/v2.yaml", "--dry-run"] if command == "run"
                     else [command, "--eps", "5", "--config-overlay", "config/v2.yaml"])
        except SystemExit as exc:  # pragma: no cover - would mean argparse rejected the flag
            pytest.fail(f"{command} rejected --config-overlay: {exc}")
    for command in ("understand", "find", "judge", "baseline"):
        with pytest.raises(SystemExit):
            cli.main([command, "--eps", "5", "--config-overlay", "config/v2.yaml"])


# ── v1 is byte-identical with the switches off ──────────────────────────


@pytest.mark.parametrize("mode", ["flag", "block"])
def test_switches_off_reproduce_the_pre_change_builder_byte_for_byte(v1cfg, mode):
    v1cfg.spoiler.reveal_mode = mode
    for seed in range(30):
        output, summary = build(random_bundle(5 if seed % 7 else 47, seed), v1cfg)
        blob = json.dumps({"candidates": output["candidates"], "summary": summary}, sort_keys=True)
        assert hashlib.sha256(blob.encode()).hexdigest() == GOLDEN[f"{mode}:{seed}"], f"{mode}:{seed}"


def test_v1_outputs_gain_no_v2_keys(v1cfg):
    for seed in range(10):
        output, summary = build(random_bundle(5, seed), v1cfg)
        assert not {"extended_generated", "resolution_flagged_generated"} & set(summary)
        for promo in output["candidates"]:
            assert not {"extended", "contains_blocking_resolution"} & set(promo["flags"])
            assert not any(key.startswith("_") for key in promo)


# ── F2: extend a too-short clip ─────────────────────────────────────────


def test_f2_extends_to_the_first_boundary_at_20s_and_flags_it(v1cfg, v2cfg, episode_factory):
    data = short_bundle(episode_factory)                      # L001..L003 = 9 s
    assert build(data, v1cfg)[0]["candidates"] == []
    output, summary = build(data, v2cfg)
    (promo,) = output["candidates"]
    assert promo["duration_s"] == 21 and promo["segments"][0]["last_line_id"] == data[0].lines[6].id
    assert promo["flags"]["extended"] is True and not promo["montage"]
    assert summary["extended_generated"] == 1 and summary["kept"] == 1
    assert summary["generated"] == sum(summary["dropped"].values()) + summary["kept"]
    # no penalty for extending: only the existing recap penalty (hook inside the first 5 s) applies
    assert promo["pre_score"] == pytest.approx(3 + 2 + 0.4 - 0.5)
    assert build(data, v1cfg)[1]["checker_errors"] == {"TOO_SHORT": 1}


def test_f2_stops_before_resolution_and_at_the_next_cliff_line(v2cfg, episode_factory):
    blocked = short_bundle(episode_factory)
    mark(blocked, 4, confidence="medium")                     # a medium resolution line inside the window
    output, summary = build(blocked, v2cfg)
    assert output["candidates"] == [] and summary["checker_errors"] == {"TOO_SHORT": 1} and summary["extended_generated"] == 0
    low = short_bundle(episode_factory)
    mark(low, 4, confidence="low")                            # a low-confidence mark does not block
    assert build(low, v2cfg)[0]["candidates"][0]["flags"]["extended"] is True
    early_cliff = short_bundle(episode_factory)
    add_cliff(early_cliff, 5)                                 # a second cliff line at 18 s, still short
    output, summary = build(early_cliff, v2cfg)
    # the L003 pair stops at that cliff line (18 s) and is dropped; the L006 pair is itself 18 s and extends past
    # its own cliff line, which is allowed (only the NEXT cliff line after a pair's own cliff stops it)
    assert [p["cliff"]["line_id"] for p in output["candidates"]] == [early_cliff[0].lines[5].id]
    assert summary["extended_generated"] == 1 and summary["checker_errors"] == {"TOO_SHORT": 1}
    on_cliff = short_bundle(episode_factory)
    add_cliff(on_cliff, 6)                                    # next cliff line at 21 s: may end on it
    (promo,) = build(on_cliff, v2cfg)[0]["candidates"]
    assert promo["segments"][0]["last_line_id"] == on_cliff[0].lines[6].id


def test_f2_fails_when_the_episode_ends_and_ignores_other_errors(v2cfg, episode_factory):
    assert build(short_bundle(episode_factory, n=6), v2cfg)[0]["candidates"] == []
    long_data = bundle(episode_factory, cliff=17)             # TOO_LONG still goes to the montage path
    (promo,) = build(long_data, v2cfg)[0]["candidates"]
    assert promo["montage"] and "extended" not in promo["flags"]


# ── F5b: flag a resolution unless it is at the end ──────────────────────


def test_f5b_keeps_flags_and_penalises_an_earlier_resolution(v1cfg, v2cfg, episode_factory):
    clean = end_bundle(episode_factory)
    base = build(clean, v2cfg)[0]["candidates"][0]["pre_score"]
    earlier = end_bundle(episode_factory)
    mark(earlier, 9)                                          # L010 ends 4 s before the clip end
    assert build(earlier, v1cfg)[0]["candidates"] == []       # v1 drops it
    output, summary = build(earlier, v2cfg)
    (promo,) = output["candidates"]
    assert promo["flags"]["contains_blocking_resolution"] is True
    assert promo["pre_score"] == pytest.approx(base - 0.5)
    assert summary["resolution_flagged_generated"] == 1 and summary["dropped"]["resolution"] == 0
    assert summary["resolution_drops_by_confidence"] == {"low": 0, "medium": 0, "high": 0}
    assert summary["resolution_intersections_by_confidence"]["high"] == 1
    assert summary["generated"] == sum(summary["dropped"].values()) + summary["kept"]


def test_f5b_drops_a_resolution_at_the_end(v2cfg, episode_factory):
    final = end_bundle(episode_factory)
    mark(final, 11)                                           # the final line
    output, summary = build(final, v2cfg)
    assert output["candidates"] == [] and summary["dropped"]["resolution"] == 1
    assert summary["resolution_drops_by_confidence"]["high"] == 1 and summary["resolution_flagged_generated"] == 0
    window = end_bundle(episode_factory)
    mark(window, 10, confidence="medium")                     # L011 ends inside the last 3 s (overlap reading)
    assert build(window, v2cfg)[0]["candidates"] == []
    edge = end_bundle(episode_factory)
    mark(edge, 9)                                             # L010 ends exactly 4 s before the end: kept
    assert len(build(edge, v2cfg)[0]["candidates"]) == 1


def test_f5b_window_is_fixed_at_three_seconds(v2cfg, episode_factory):
    assert builder.RESOLUTION_END_WINDOW_MS == 3000 and builder.RESOLUTION_FLAG_PENALTY == 0.5
    # clip L001..L008 = 24 s; L007 ends at 21 s, exactly 3.0 s before the end: outside the window, so kept
    data = bundle(episode_factory, n=10, step=3000, cliff=7)
    mark(data, 6)
    (promo,) = build(data, v2cfg)[0]["candidates"]
    assert promo["flags"]["contains_blocking_resolution"] is True
    final = bundle(episode_factory, n=10, step=3000, cliff=7)
    mark(final, 7)                                            # the final line L008: dropped
    assert build(final, v2cfg)[0]["candidates"] == []


def test_f5b_resolution_in_a_montage_first_piece_is_earlier(v2cfg, episode_factory):
    data = bundle(episode_factory, cliff=17)
    mark(data, 1, confidence="medium")
    (promo,) = build(data, v2cfg)[0]["candidates"]
    assert promo["montage"] and promo["flags"]["contains_blocking_resolution"] is True
    last = bundle(episode_factory, cliff=17)
    mark(last, 17)
    assert build(last, v2cfg)[0]["candidates"] == []


def test_f5b_low_confidence_marks_are_not_blocking(v2cfg, episode_factory):
    data = end_bundle(episode_factory)
    mark(data, 9, confidence="low")
    (promo,) = build(data, v2cfg)[0]["candidates"]
    assert "contains_blocking_resolution" not in promo["flags"]
    assert promo["flags"]["contains_low_conf_resolution"] is True      # the existing flag is untouched


# ── the implementation equals the diagnostic what-if I reported ─────────


@pytest.mark.parametrize("mode", ["flag", "block"])
def test_builder_v2_equals_the_diagnostic_replay_on_random_episodes(v2cfg, v1cfg, mode):
    v2cfg.spoiler.reveal_mode = v1cfg.spoiler.reveal_mode = mode
    extended = flagged = res_drops = 0
    for seed in range(60):
        data = random_bundle(5 if seed % 7 else 47, seed)
        output, summary = build(data, v2cfg)
        trace = D.trace_episode(*data, v1cfg, None, too_short_mode="extend", resolution_mode="flag_unless_end")
        assert D.same_as_builder(trace, output["candidates"], summary) == [], f"seed {seed}"
        extended += sum(bool(p["flags"].get("extended")) for p in output["candidates"])
        flagged += sum(bool(p["flags"].get("contains_blocking_resolution")) for p in output["candidates"])
        res_drops += summary["dropped"]["resolution"]
    assert extended > 0 and flagged > 0 and res_drops > 0


def test_v2_candidates_pass_the_final_checker_invariant(v2cfg):
    # build_episode re-checks every kept promo and raises if a time is not checker-derived
    for seed in range(40):
        build(random_bundle(5, seed), v2cfg)


def test_devcheck_tool_excludes_the_fresh_set_and_its_recap_neighbour():
    import importlib.util
    spec = importlib.util.spec_from_file_location("p08b_devcheck", ROOT / "tools/p08b_devcheck.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    eps = tool.eps_list()
    # sealed blocks A (31-34) and B (15-17, 35) are excluded; 35 was already left out as a recap neighbour of 34
    assert not set(eps) & {31, 32, 33, 34, 35, 15, 16, 17} and len(eps) == 42
    assert set(tool.DEV) == {5, 6, 7, 8, 19, 20, 21, 22} <= set(eps)
    assert set(tool.DEV).isdisjoint(builder.HELD_OUT)
    tool.EPS.append(32)                                       # even a mistaken edit cannot reach a fresh episode
    try:
        assert 32 not in tool.eps_list()
    finally:
        tool.EPS.remove(32)


# ── lane routing (label only) ───────────────────────────────────────────


def formula():
    import yaml
    return yaml.safe_load((ROOT / "config/score_formula.yaml").read_text())


def test_review_reasons_route_flagged_promos_without_touching_v1_reasons():
    plain = {"episode": 1, "flags": {}, "policy": {}, "montage": False}
    flagged = {**plain, "flags": {"contains_blocking_resolution": True}}
    from test_ranking import pair
    promo, judged = pair()
    values = ranking.components(promo, judged, formula())
    assert ranking.review_reasons(promo, judged, values, formula()) == []
    promo["flags"]["contains_blocking_resolution"] = True
    assert ranking.review_reasons(promo, judged, values, formula()) == ["blocking_resolution"]
    assert ranking.review_reasons(plain, judged, None, formula()) == ["missing_evidence"]
    assert ranking.review_reasons(flagged, judged, None, formula()) == ["missing_evidence", "blocking_resolution"]
    values_policy = dict(values, P=1.0)
    assert ranking.review_reasons(promo, judged, values_policy, formula()) == ["policy", "blocking_resolution"]


def test_flagged_rows_leave_the_launch_batch_but_keep_their_rank():
    rows = [{"promo_id": "P-A", "S": .9, "line_ids": ["a"], "hook_type": "H1", "needs_human_reasons": ["blocking_resolution"]},
            {"promo_id": "P-B", "S": .8, "line_ids": ["b"], "hook_type": "H2", "needs_human_reasons": []}]
    assert ranking.launch_batch(rows)["promo_ids"] == ["P-B"]
    order = lambda rs: [r["promo_id"] for r in ranking.evaluation_order([{**r, "pre_score": 1.0} for r in rs])]
    unflagged = [{**r, "needs_human_reasons": []} for r in rows]
    assert order(rows) == order(unflagged) == ["P-A", "P-B"]  # evaluation order ignores lanes (D66)


def test_rank_run_labels_the_lane_and_counts_flagged_rows(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    path = jcfg.root / "outputs/runs/dev/promos/candidates_E05.json"
    data = json.loads(path.read_text())
    data["candidates"][0]["flags"]["contains_blocking_resolution"] = True
    path.write_text(json.dumps(data))
    judging.run(jcfg, [ep], client(jcfg, Provider()))
    shutil.copy2(ROOT / "config/score_formula.yaml", jcfg.root / "config/score_formula.yaml")
    summary = ranking.run(jcfg, [ep])
    ranked = json.loads((jcfg.root / "outputs/runs/dev/ranked/promos_dev.json").read_text())
    row = ranked["promos"][0]
    assert row["lane"] == "needs_human" and row["needs_human_reasons"] == ["blocking_resolution"]
    assert row["S"] is not None and ranked["evaluation_order"] == [row["promo_id"]]
    assert summary["lane_counts"]["needs_human"] == 1 and summary["blocking_resolution_rows"] == 1
    assert summary["launch_batch"]["promo_ids"] == []


def test_rank_summary_has_no_v2_key_for_v1_candidates(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    judging.run(jcfg, [ep], client(jcfg, Provider()))
    shutil.copy2(ROOT / "config/score_formula.yaml", jcfg.root / "config/score_formula.yaml")
    assert "blocking_resolution_rows" not in ranking.run(jcfg, [ep])
