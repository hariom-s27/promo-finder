#!/usr/bin/env python
"""Leak guard. Run before every commit.

Fails (exit 1) if:
  * a staged path is under data/, outputs/, .cache/ or .venv/, or is any .env file;
  * a staged file contains 8+ consecutive words that also appear in any file in data_dir
    (lower-cased, whitespace collapsed, 8-word shingle set).
On a hit it prints only path:line, never the matched text. .env files are never opened.

Modes:
  default   staged files (git index) if inside a git repo, else every file under the repo
  --all     every file under the repo (skipping ignored dirs and .env files)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
SHINGLE = 8
BLOCKED_TOP = ("data", "outputs", ".cache", ".venv")
WALK_SKIP = {".git", ".venv", "outputs", ".cache", "data", "__pycache__", ".pytest_cache", "build", "dist"}
# Windows containing a time token (e.g. 00:04.80) are format, not content: skip them so
# the shared screenplay layout of invented fixtures does not trigger false hits.
TIME_TOKEN = re.compile(r"\d+:\d+")
# Windows made ONLY of layout words (markers, field labels, numbers) are format, not content.
FORMAT_WORDS = {
    "---", "|", "script", "start", "end", "scene", "heading:", "start:", "end:", "actions", "and",
    "dialogue:", "episode", "number:", "logline:", "continuity", "notes:",
    "**camera:**", "**action:**", "**sound", "fx:**", "int.", "ext.", "int./ext.", "–", "-",
}


def _is_format(tok: str) -> bool:
    return tok in FORMAT_WORDS or tok.isdigit()


def is_env_file(path: str) -> bool:
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    return name == ".env" or name.endswith(".env") or name.startswith(".env.")


def path_problems(paths: Iterable[str]) -> list[str]:
    bad = []
    for p in paths:
        parts = PurePosixPath(p.replace("\\", "/")).parts
        if parts and parts[0] in BLOCKED_TOP:
            bad.append(f"{p}: blocked path ({parts[0]}/)")
        elif is_env_file(p):
            bad.append(f"{p}: env file")
    return bad


def _windows(tokens: list[str]) -> Iterable[tuple[int, str]]:
    for i in range(len(tokens) - SHINGLE + 1):
        w = tokens[i:i + SHINGLE]
        if any(TIME_TOKEN.search(t) for t in w) or all(_is_format(t) for t in w):
            continue
        yield i, " ".join(w)


def build_shingles(data_dir: Path) -> set[str]:
    shingles: set[str] = set()
    for f in sorted(Path(data_dir).rglob("*")):
        if not f.is_file() or is_env_file(f.name):
            continue
        try:
            text = f.read_bytes().decode("utf-8", errors="ignore")
        except OSError:
            continue
        for _, s in _windows(text.lower().split()):
            shingles.add(s)
    return shingles


def scan_text(text: str, shingles: set[str]) -> list[int]:
    """Return sorted line numbers where a shared 8-word run starts."""
    toks: list[str] = []
    line_of: list[int] = []
    for ln, line in enumerate(text.splitlines(), 1):
        for t in line.lower().split():
            toks.append(t)
            line_of.append(ln)
    hits = {line_of[i] for i, s in _windows(toks) if s in shingles}
    return sorted(hits)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True)


def in_git_repo(root: Path) -> bool:
    try:
        r = _git(root, "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        return False
    return r.returncode == 0 and Path(r.stdout.decode().strip()).resolve() == root.resolve()


def staged_files(root: Path) -> list[str]:
    r = _git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    return [p for p in r.stdout.decode("utf-8", errors="replace").split("\0") if p]


def read_staged(root: Path, path: str) -> Optional[bytes]:
    r = _git(root, "show", f":{path}")
    return r.stdout if r.returncode == 0 else None


def walk_files(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in WALK_SKIP and not d.endswith(".egg-info")]
        for fn in filenames:
            rel = Path(dirpath, fn).relative_to(root).as_posix()
            out.append(rel)
    return sorted(out)


def resolve_data_dir(root: Path, arg: Optional[str]) -> Optional[Path]:
    val = arg or os.environ.get("KUKU_DATA_DIR")
    if not val:
        cfg = root / "config.yaml"
        if cfg.is_file():
            import yaml

            val = (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("data_dir")
    if not val:
        return None
    p = Path(val)
    return p if p.is_absolute() else (root / p)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--data-dir")
    ap.add_argument("--all", action="store_true", help="scan every repo file instead of staged files")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    staged_mode = not args.all and in_git_repo(root)
    paths = staged_files(root) if staged_mode else walk_files(root)

    problems = path_problems(paths) if staged_mode else []
    data_dir = resolve_data_dir(root, args.data_dir)
    if data_dir is None or not data_dir.is_dir():
        print("guard: data_dir not found; cannot run the content check", file=sys.stderr)
        return 2
    shingles = build_shingles(data_dir)

    hits: list[str] = []
    checked = 0
    for p in paths:
        if is_env_file(p) or PurePosixPath(p).parts[:1] and PurePosixPath(p).parts[0] in BLOCKED_TOP:
            continue  # never opened; blocked paths are reported above
        raw = read_staged(root, p) if staged_mode else (root / p).read_bytes()
        if raw is None or b"\x00" in raw[:8000]:
            continue
        checked += 1
        for ln in scan_text(raw.decode("utf-8", errors="ignore"), shingles):
            hits.append(f"{p}:{ln}")

    for line in problems + hits:
        print(line)
    mode = "staged" if staged_mode else "all files"
    if problems or hits:
        print(f"guard: FAILED ({len(problems)} path problems, {len(hits)} text hits; {checked} files checked, mode={mode})")
        return 1
    print(f"guard: clean ({checked} files checked, mode={mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
