#!/usr/bin/env python
"""Record sha256 hashes of the frozen eval files in eval/HASHES.md.

  python tools/hash_eval.py init          hash the 3 frozen files, check them against the
                                          approved values, write eval/HASHES.md
  python tools/hash_eval.py add <file>    append one row (e.g. eval/gold.csv); refuses CRLF or BOM

Hashes are of the exact file bytes (LF line endings, no BOM). Prints hashes and paths only.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
HASHES = "eval/HASHES.md"

# Approved values (P01b prompt, Part A3). A change here = a new version + DECISION_LOG entry.
EXPECTED = {
    "eval/match_rule.md": "d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2",
    "eval/gold_rubric.md": "6f7b5161a66d857e913e5f73715f6b36c129d4cd57b69cd7d618e2b53f5550c0",
    "eval/gold_template.csv": "bb794d8a826bbc62288c30d16010e162c647ae5bdd19673dc22ebaf422bd8391",
}
NOTE_FROZEN = "frozen before labelling"
NOTE_GOLD = "gold labels, hash only (file committed at P08)"

HEADER = (
    "# EVAL HASHES (sha256 of file bytes, LF line endings)\n"
    "Frozen BEFORE any gold label exists. A changed file = a new version + a new DECISION_LOG entry.\n"
    "\n"
    "| File | sha256 | Bytes | Recorded (UTC) | Note |\n"
    "|---|---|---|---|---|\n"
)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(rel: str, data: bytes, note: str) -> str:
    return f"| {rel} | {sha256_bytes(data)} | {len(data)} | {_now()} | {note} |\n"


def byte_problems(data: bytes) -> list[str]:
    probs = []
    if data.startswith(b"\xef\xbb\xbf"):
        probs.append("has a UTF-8 BOM: re-save as 'UTF-8' (not 'UTF-8 with BOM')")
    if b"\r" in data:
        probs.append("has CRLF/CR line endings: re-save with LF line endings "
                     "(e.g. VS Code status bar CRLF -> LF, then save)")
    return probs


def cmd_init(root: Path, expected: dict[str, str]) -> int:
    out = root / HASHES
    if out.exists():
        print(f"refused: {HASHES} already exists (never overwritten; use 'add' for new files)", file=sys.stderr)
        return 1
    rows, bad = [], False
    for rel, exp in expected.items():
        p = root / rel
        if not p.is_file():
            print(f"MISSING {rel}", file=sys.stderr)
            bad = True
            continue
        data = p.read_bytes()
        got = sha256_bytes(data)
        if got != exp:
            crlf, bom = b"\r\n" in data, data.startswith(b"\xef\xbb\xbf")
            print(f"MISMATCH {rel}\n  expected {exp}\n  on disk  {got}\n  bytes    {len(data)}"
                  f"  crlf={crlf}  bom={bom}", file=sys.stderr)
            bad = True
            continue
        print(f"OK {rel} {got} {len(data)} bytes")
        rows.append(_row(rel, data, NOTE_FROZEN))
    if bad:
        print(f"FAILED: {HASHES} not written", file=sys.stderr)
        return 1
    out.write_bytes((HEADER + "".join(rows)).encode("utf-8"))
    print(f"wrote {HASHES}")
    return 0


def cmd_add(root: Path, file: str, note: Optional[str]) -> int:
    out = root / HASHES
    if not out.is_file():
        print(f"refused: {HASHES} not found (run init first)", file=sys.stderr)
        return 1
    p = Path(file)
    p = p if p.is_absolute() else (root / p)
    if not p.is_file():
        print(f"file not found: {file}", file=sys.stderr)
        return 1
    try:
        rel = p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        print("refused: file must be inside the repo", file=sys.stderr)
        return 1
    data = p.read_bytes()
    probs = byte_problems(data)
    if probs:
        for msg in probs:
            print(f"refused: {rel} {msg}", file=sys.stderr)
        return 1
    existing = out.read_bytes()
    if b"\r" in existing:
        print(f"refused: {HASHES} has CRLF line endings", file=sys.stderr)
        return 1
    if note is None:
        is_gold = any(fnmatch.fnmatchcase(rel, g) for g in ("eval/gold.csv", "eval/gold_v*.csv"))
        note = NOTE_GOLD if is_gold else ""
    if not existing.endswith(b"\n"):
        existing += b"\n"
    line = _row(rel, data, note)
    out.write_bytes(existing + line.encode("utf-8"))
    print(f"added {rel} {sha256_bytes(data)} {len(data)} bytes")
    return 0


def main(argv: Optional[list[str]] = None, expected: Optional[dict[str, str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="hash the 3 frozen eval files and write eval/HASHES.md")
    a = sub.add_parser("add", help="append one file's hash")
    a.add_argument("file")
    a.add_argument("--note", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.cmd == "init":
        return cmd_init(root, expected or EXPECTED)
    return cmd_add(root, args.file, args.note)


if __name__ == "__main__":
    sys.exit(main())
