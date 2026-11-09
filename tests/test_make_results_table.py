"""Rendering tests use invented metrics, never labels."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("make_results_table", Path(__file__).resolve().parents[1] / "tools/make_results_table.py")
table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(table)


def invented_sources(root):
    measure = {"k": 1, "n": 4, "value": .25}
    metrics = {m: dict(measure) for m in table.METRICS}
    metrics["recall_by_grade"] = {str(g): dict(measure) for g in (1, 2, 3)}
    metrics.update(L_size=12, K_used=8)
    pair = {"n": 4, "mcnemar": {"tool_only": 1, "baseline_only": 0, "p_two_sided": 1},
            "bootstrap": {"mean_diff": .25, "ci95": [0, .5]}}
    defs = dict.fromkeys((*table.METRICS, "recall_by_grade", "matching"), "invented definition")
    official = {"counts": {"G": 4, "negatives": 4, "K": 8}, "tool": metrics, "baseline": metrics,
                "paired_tool_vs_baseline": pair, "definitions": defs}
    fresh = {"G": 4, "negatives": 4, "K": 8, "definitions": defs,
             "systems": {key: {"primary": metrics, "L_size": 12, "K_used": 8} for key in ("v2", "v1")}, "paired": {"v2_vs_v1": pair}}
    (root / "results").mkdir()
    for index, source in enumerate(table.SOURCES):
        (root / source).write_text(json.dumps(official if index == 0 else fresh), encoding="utf-8")


def test_table_uses_saved_values_and_separates_blocks(tmp_path):
    invented_sources(tmp_path)
    text = table.render(tmp_path)
    assert text.count("fresh block A") == 1 and text.count("fresh block B") == 1
    assert "post-hoc (after seeing v1 results)" in text and "1/4 = 0.250" in text
    path = tmp_path / table.SOURCES[1]
    data = json.loads(path.read_text())
    data["systems"]["v2"]["primary"]["recall_at_K"] = {"k": 3, "n": 4, "value": .75}
    path.write_text(json.dumps(data))
    changed = table.render(tmp_path)
    assert "3/4 = 0.750" in changed and changed != text


@pytest.mark.parametrize("value", [{"k": 0, "n": 0, "value": None}, {"k": 0, "n": 3, "value": 0}])
def test_undefined_and_zero_are_distinct(value):
    text = table.ratio(value)
    assert ("n/a" in text) == (value["n"] == 0)


@pytest.mark.parametrize("row", [{"k": 1, "n": 4, "value": .5}, {"k": 1, "n": 0, "value": None}, {"k": 0, "n": 0, "value": 0}])
def test_inconsistent_metrics_fail(row):
    with pytest.raises(ValueError):
        table.ratio(row)


def test_missing_metric_fails_instead_of_inventing_number(tmp_path):
    invented_sources(tmp_path)
    path = tmp_path / table.SOURCES[0]
    data = json.loads(path.read_text())
    del data["tool"]["hook_hit"]
    path.write_text(json.dumps(data))
    with pytest.raises(KeyError):
        table.render(tmp_path)


def test_generated_document_matches_public_saved_metrics():
    assert (table.ROOT / "docs/RESULTS.md").read_text(encoding="utf-8") == table.render(table.ROOT)


def test_readme_glance_is_five_generated_lines_and_updates_without_duplicates(tmp_path):
    invented_sources(tmp_path)
    (tmp_path / "README.md").write_text("# Invented project\n")
    table.update_readme(tmp_path)
    first = (tmp_path / "README.md").read_text()
    assert first.startswith(table.GLANCE_START) and sum(line.startswith("- ") for line in first.splitlines()) == 5
    assert "Official held-out Recall@8: v1 1/4; baseline 1/4" in first
    table.update_readme(tmp_path)
    assert (tmp_path / "README.md").read_text() == first


def test_readme_glance_matches_generated_sources():
    assert (table.ROOT / "README.md").read_text(encoding="utf-8").startswith(table.readme_glance())
