"""Run paths, immutable-input fingerprints, and copy-only DEV migration."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .understanding_common import UnderstandingError, write_json

SCORE_SHA256 = "8f76ddf50855441a2b9dfc1e60b7f4f0db3cca308a8a37f22c7f25374b5638f3"
FROZEN = ("config/eval_order.yaml", "config/baseline.yaml")
FROZEN_SHA256 = {
    "config/eval_order.yaml": "71d0a4042e95ec90a5ec509f28eac447721d3e951ecb0259cb376520db734ab8",
    "config/baseline.yaml": "57ccd891e430926d0b2bc2766b4488759a32f3408def2bfdab684b8e37ca7cef",
}
STAGES = ("understanding", "moments", "promos", "judge", "ranked", "baseline")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def for_run(cfg: Config, name: str) -> Config:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name or ""):
        raise UnderstandingError("invalid run name")
    if name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                        *(f"LPT{i}" for i in range(1, 10))}:
        raise UnderstandingError("invalid run name")
    result = cfg.model_copy(deep=True)
    result._run_name = name
    result.output_root.resolve().relative_to((cfg.root / "outputs/runs").resolve())
    return result


def fingerprints(cfg: Config, *, required=False) -> dict:
    formula = cfg.root / "config/score_formula.yaml"
    sha = digest(formula) if formula.is_file() else None
    if (required or sha is not None) and sha != SCORE_SHA256:
        raise UnderstandingError("score formula hash mismatch")
    frozen = {}
    for rel in FROZEN:
        path = cfg.root / rel
        if required and not path.is_file():
            raise UnderstandingError("frozen config missing")
        frozen[rel] = digest(path) if path.is_file() else None
        if required and frozen[rel] != FROZEN_SHA256[rel]:
            raise UnderstandingError("frozen config hash mismatch; stop for Hariom")
    config_path = cfg._config_path or cfg.root / "config.yaml"
    return {"config_sha256": digest(config_path) if config_path.is_file() else None,
            "score_formula_sha256": sha, "frozen_config_sha256": frozen}


def manifest(cfg: Config, episodes: list[int], **updates) -> dict:
    path = cfg.output_root / "run_manifest.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cfg.root, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=cfg.root, capture_output=True)
    value = {**previous, "run": cfg.run_name, "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
             "working_tree_dirty": bool(dirty.stdout),
             **fingerprints(cfg), "episodes": sorted(set(episodes)), "max_calls_per_run": cfg.max_calls_per_run,
             **updates}
    for stage in STAGES:
        (cfg.output_root / stage).mkdir(parents=True, exist_ok=True)
    write_json(path, value)
    return value


def migrate_dev(cfg: Config) -> dict:
    target = for_run(cfg, "dev").output_root
    marker = target / "migration_manifest.json"
    if marker.exists():
        previous = json.loads(marker.read_text(encoding="utf-8"))
        # Later DEV phases may legitimately replace copied files. Verify originals
        # against the migration record, never overwrite the new run with old results.
        for rel, sha in previous["source_sha256"].items():
            if digest(cfg.root / "outputs" / rel) != sha:
                raise UnderstandingError("DEV migration source changed")
        return {"copied_files": len(previous["source_sha256"]), "already_migrated": True}
    sources = []
    for stage in STAGES[:-1]:
        source = cfg.root / "outputs" / stage
        if source.exists():
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise UnderstandingError("migration refuses symbolic links")
                if path.is_file():
                    path.resolve().relative_to(source.resolve())
                    sources.append((path, path.relative_to(cfg.root / "outputs")))
    # Check the whole copy before writing any destination.
    for source, rel in sources:
        destination = target / rel
        if destination.exists() and digest(source) != digest(destination):
            raise UnderstandingError("DEV migration destination conflict")
    hashes = {}
    for source, rel in sources:
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)
        hashes[rel.as_posix()] = digest(source)
        if digest(destination) != hashes[rel.as_posix()]:
            raise UnderstandingError("DEV migration verification failed")
    write_json(marker, {"source_sha256": hashes, "copy_not_move": True})
    return {"copied_files": len(hashes), "already_migrated": False}
