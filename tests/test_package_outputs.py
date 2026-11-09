"""Invented package trees, labels and caches only."""
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("package_outputs", Path(__file__).resolve().parents[1] / "tools/package_outputs.py")
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


def write(root, path, text="invented"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


@pytest.fixture
def source_tree(tmp_path, episode_factory):
    for name in ("full", "full_v2", "free_demo"):
        base = f"outputs/runs/{name}"
        write(tmp_path, base + "/run_manifest.json", json.dumps({"status": "complete", "episodes": [23, 24] if name == "free_demo" else list(range(1, 51))}))
        for folder in pack.RUN_DIRS:
            if name == "free_demo" and folder in {"baseline", "evaluation"}:
                continue
            write(tmp_path, base + f"/{folder}/invented.json")
        write(tmp_path, base + "/.llm_cache/excluded.json", "invented-cache-canary")
        write(tmp_path, base + "/judge/.llm_cache/excluded.json", "invented-cache-canary")
    for part in pack.EVAL_DIRS:
        for name in ("metrics.json", "scoring_ledger.json"):
            write(tmp_path, f"outputs/eval/{part}/{name}", "{}")
    for name in pack.GOLD_FILES:
        write(tmp_path, f"eval/{name}", "gold_id,grade\nINVENTED,3\n")
    for name in pack.AI_FILES:
        write(tmp_path, f"outputs/ai_labels/{name}", 'gold_id,rationale,grade\nINVENTED,"invented-rationale-canary,\ncontinued",3\n')
    write(tmp_path, "outputs/gold_sealed/original.csv", "invented-sealed-canary")
    episode = episode_factory(23, [(0, 10000), (10000, 20000)])
    write(tmp_path, "outputs/parsed/E23.json", episode.model_dump_json())
    row = {"rank": 1, "lane": "reserve", "S": 1.5, "hook_type": "H1", "cliff_type": "C2",
           "segments": [{"episode": 23, "start_ms": 0, "end_ms": 20000,
                         "first_line_id": episode.lines[0].id, "last_line_id": episode.lines[-1].id}],
           "line_ids": [line.id for line in episode.lines], "judge": {"aggregate": {"answers": {"standalone": "yes"}}}}
    write(tmp_path, "outputs/runs/full/ranked/promos_dev.json", json.dumps({"promos": [row]}))
    return tmp_path


def test_package_excludes_cache_and_sealed_originals_and_redacts_ai(source_tree):
    root = source_tree
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    result = pack.package(root)
    destination = root / "outputs/package" / pack.PACKAGE
    files = [p for p in destination.rglob("*") if p.is_file()]
    assert result["files"] == len(files)
    assert result["total_bytes"] == sum(p.stat().st_size for p in files)
    assert result["review_promos"] == 1
    review = (destination / "review/top_promos_by_episode.md").read_text()
    assert "Transcript:" in review and "invented line 1" in review and "standalone: yes" in review
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == sha for p, sha in before.items())
    with zipfile.ZipFile(destination.with_suffix(".zip")) as archive:
        assert len(archive.namelist()) == len(files)
        assert not any(".llm_cache" in name or "gold_sealed" in name for name in archive.namelist())
        raw = b"".join(archive.read(name) for name in archive.namelist() if name.endswith(".csv"))
        assert b"invented-rationale-canary" not in raw and b"invented-sealed-canary" not in raw
        assert archive.read(f"{pack.PACKAGE}/ai_labels_redacted/gpt_v1.csv") == b"gold_id,grade\nINVENTED,3\n"
    with pytest.raises(ValueError, match="already exists"):
        pack.package(root)


def test_incomplete_free_demo_refuses_before_writing_package(source_tree):
    write(source_tree, "outputs/runs/free_demo/run_manifest.json", '{"status":"failed"}')
    with pytest.raises(ValueError, match="completed"):
        pack.package(source_tree)
    assert not (source_tree / "outputs/package").exists()


def test_malformed_ai_labels_refuse_before_writing_package(source_tree):
    write(source_tree, "outputs/ai_labels/gpt_v1.csv", "gold_id,grade\nINVENTED,3\n")
    with pytest.raises(ValueError, match="rationale"):
        pack.package(source_tree)
    assert not (source_tree / "outputs/package").exists()


def test_missing_source_refuses_without_package_creation(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        pack.package(tmp_path)
    assert not (tmp_path / "outputs/package").exists()


def test_review_path_is_guard_blocked_without_reading(monkeypatch, tmp_path):
    from test_guard import guard
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(guard, "in_git_repo", lambda *a: True)
    monkeypatch.setattr(guard, "staged_files", lambda *a: ["review/top_promos_by_episode.md"])
    monkeypatch.setattr(guard, "read_staged", lambda *a: pytest.fail("private transcript opened"))
    assert guard.main(["--root", str(tmp_path), "--data-dir", str(data)]) == 1


def test_packager_accepts_completed_isolated_retry_preserving_partial(source_tree):
    import shutil
    source = source_tree / "outputs/runs/free_demo"
    shutil.copytree(source, source_tree / "outputs/runs/free_demo_d104")
    write(source_tree, "outputs/runs/free_demo/run_manifest.json", json.dumps({"status": "failed", "episodes": [23, 24]}))
    pack.package(source_tree, free_run="free_demo_d104")
    destination = source_tree / "outputs/package" / pack.PACKAGE
    assert json.loads((destination / "outputs/runs/free_demo/run_manifest.json").read_text())["status"] == "failed"
    assert json.loads((destination / "outputs/runs/free_demo_d104/run_manifest.json").read_text())["status"] == "complete"
