from __future__ import annotations

import json

import pytest

from promo_finder.run_context import SCORE_SHA256, STAGES, digest, fingerprints, for_run, manifest, migrate_dev
from promo_finder.understanding_common import UnderstandingError


@pytest.mark.parametrize("name", ["../other", "a/b", "a\\b", "", ".", "CON", "LPT1", "a" * 65])
def test_run_name_refuses_escape(p07_cfg, name):
    with pytest.raises(UnderstandingError): for_run(p07_cfg, name)


def test_manifest_layout_and_actual_hashes(p07_cfg):
    cfg = for_run(p07_cfg, "invented_run")
    value = manifest(cfg, [10, 9], status="running")
    assert value["episodes"] == [9, 10] and value["run"] == "invented_run"
    assert value["score_formula_sha256"] == SCORE_SHA256
    assert value["config_sha256"] == digest(cfg.root / "config.yaml")
    assert all((cfg.output_root / stage).is_dir() for stage in STAGES)
    for rel, sha in value["frozen_config_sha256"].items(): assert sha == digest(cfg.root / rel)
    assert cfg.root == p07_cfg.root


def test_copy_preserves_originals_and_hashes(p07_cfg):
    for stage in STAGES[:-1]:
        source = p07_cfg.root / "outputs" / stage / "nested" / "invented.json"
        source.parent.mkdir(parents=True)
        source.write_text('{"invented": 1}', encoding="utf-8")
    result = migrate_dev(p07_cfg)
    assert result == {"copied_files": 5, "already_migrated": False}
    for stage in STAGES[:-1]:
        original = p07_cfg.root / "outputs" / stage / "nested/invented.json"
        assert original.exists() and digest(original) == digest(p07_cfg.output_root / stage / "nested/invented.json")
    assert migrate_dev(p07_cfg)["already_migrated"]
    (p07_cfg.output_root / "judge/nested/invented.json").write_text("new run", encoding="utf-8")
    assert migrate_dev(p07_cfg)["already_migrated"]
    assert (p07_cfg.output_root / "judge/nested/invented.json").read_text() == "new run"


def test_copy_conflict_refused_before_any_source_copy(p07_cfg):
    source = p07_cfg.root / "outputs/judge/invented.json"
    source.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")
    target = p07_cfg.output_root / "judge/invented.json"
    target.parent.mkdir(parents=True)
    target.write_text("different", encoding="utf-8")
    with pytest.raises(UnderstandingError, match="conflict"): migrate_dev(p07_cfg)
    assert source.read_text() == "original" and target.read_text() == "different"


def test_frozen_formula_bytes_required(p07_cfg):
    assert fingerprints(p07_cfg, required=True)["score_formula_sha256"] == SCORE_SHA256
    path = p07_cfg.root / "config/score_formula.yaml"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(UnderstandingError, match="hash"): fingerprints(p07_cfg, required=True)
