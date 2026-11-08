from __future__ import annotations

import importlib.util
from pathlib import Path

from promo_finder.run_context import SCORE_SHA256, fingerprints


def test_offline_tool_has_only_offline_actions():
    path = Path(__file__).resolve().parents[1] / "tools/p07_offline.py"
    spec = importlib.util.spec_from_file_location("p07_offline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.EXISTING_FROZEN == ("eval/match_rule.md", "eval/gold_rubric.md", "eval/gold_template.csv", "eval/HASHES.md", "config/score_formula.yaml")


def test_formula_hash_is_exactly_frozen(p07_cfg):
    assert fingerprints(p07_cfg, required=True)["score_formula_sha256"] == SCORE_SHA256
