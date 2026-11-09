"""Export privacy and usage tests using invented source rows only."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("export_app_results", Path(__file__).resolve().parents[1] / "tools/export_app_results.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
CANARY = "eight invented private words should never enter this export"


@pytest.fixture
def source_tree(tmp_path):
    first = {"episode": 23, "start_ms": 0, "end_ms": 20000, "speaker": CANARY}
    row = {"segments": [first], "hook_type": "H1", "cliff_type": "C2", "S": 1.5, "lane": "launch_batch", "rank": 1,
           "why": CANARY, "rationale": CANARY, "transcript": CANARY, "name": CANARY,
           "judge": {"private": CANARY}, "line_ids": [CANARY]}
    second = copy.deepcopy(row)
    second.update(rank=2, S=None, lane="needs_human", segments=[
        {"episode": 24, "start_ms": 25950, "end_ms": 40050},
        {"episode": 24, "start_ms": 45000, "end_ms": 55000}])
    provider = {"azure": {"calls": 2, "http_requests": 3, "input_tokens": 20, "output_tokens": 5, "usd": .125,
                           "private": CANARY}}
    manifest = {"status": "complete", "episodes": list(range(1, 51)), "wall_time_s": 8.0, "llm": {"providers": provider},
                "stages": {name: {"status": "complete", "wall_time_s": 1.0, "llm": {"providers": provider if name == "understand" else {}}}
                           for name in exporter.STAGES}, "private": CANARY}
    for relative, data in zip(exporter.SOURCES, ({"promos": [second, row]}, manifest, manifest)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def test_export_has_only_metadata_and_no_text_fields(source_tree):
    data = exporter.build_export(source_tree)
    assert CANARY not in json.dumps(data)
    assert all(set(row) == exporter.PROMO_FIELDS for row in data["promos"])
    assert [row["rank"] for row in data["promos"]] == [1, 2]
    row = data["promos"][1]
    assert row["start"] == "00:26.0 + 00:45.0" and row["end"] == "00:40.1 + 00:55.0"
    assert row["duration"] == 24.1 and row["S"] is None
    assert data["azure_totals"]["calls"] == 2 and data["azure_totals"]["http_requests"] == 3
    assert data["azure_totals"]["tokens"] == 25 and data["azure_totals"]["usd"] == .125
    assert data["v2_cost_usd"] == .125
    assert len(data["azure_stages"]) == 7
    assert data["launch_batch"] == [data["promos"][0]]
    scale = data["cost_at_scale"]
    assert scale["shows_per_month"] == 150
    assert scale["monthly_usd"] == .125 * 150
    assert scale["monthly_minutes"] == 8 / 60 * 150


def test_export_passes_content_guard_on_invented_private_source(source_tree, tmp_path):
    from test_guard import guard
    scripts = tmp_path / "invented_input"
    scripts.mkdir()
    (scripts / "invented.txt").write_text(CANARY, encoding="utf-8")
    text = json.dumps(exporter.build_export(source_tree))
    assert guard.scan_text(text, guard.build_shingles(scripts)) == []


@pytest.mark.parametrize("field,value", [("hook_type", CANARY), ("cliff_type", CANARY), ("lane", CANARY),
                                        ("S", CANARY), ("rank", CANARY)])
def test_export_refuses_text_in_allowed_fields(source_tree, field, value):
    path = source_tree / exporter.SOURCES[0]
    data = json.loads(path.read_text())
    data["promos"][0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        exporter.build_export(source_tree)


def test_usage_mismatch_is_not_silently_exported(source_tree):
    path = source_tree / exporter.SOURCES[1]
    data = json.loads(path.read_text())
    data["llm"]["providers"]["azure"]["calls"] = 10
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="disagree"):
        exporter.build_export(source_tree)


def test_saved_public_app_asset_has_no_extra_promo_fields():
    data = json.loads((exporter.ROOT / exporter.TARGET).read_text(encoding="utf-8"))
    assert all(set(row) == exporter.PROMO_FIELDS for row in data["promos"])
