"""Byte regression for official v1/v2 plans, captured before D100 with invented episodes."""
import json
import shutil
from pathlib import Path

from conftest import make_episode
from promo_finder import pipeline

ROOT = Path(__file__).resolve().parents[1]


def official_plans(cfg):
    # Canonical newlines in this disposable fake config make the fixture portable.
    path = cfg._config_path
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    shutil.copy2(ROOT / "config/v2.yaml", cfg.root / "config/v2.yaml")
    episodes = [make_episode(number, [(i * 5000, (i + 1) * 5000) for i in range(20)]) for number in (5, 9, 47)]
    v2 = cfg.model_copy(deep=True)
    v2.builder.too_short_mode = "extend"
    v2.builder.resolution_mode = "flag_unless_end"
    v2._overlay_path = cfg.root / "config/v2.yaml"
    return {"v1": pipeline.dry_run(cfg, episodes), "v2": pipeline.dry_run(v2, episodes)}


def canonical(plans):
    return (json.dumps(plans, sort_keys=True, indent=2) + "\n").encode("utf-8")


def test_official_plans_are_byte_identical_to_pre_d100(p07_cfg):
    assert canonical(official_plans(p07_cfg)) == (ROOT / "tests/fixtures/p09_official_plans.json").read_bytes()
