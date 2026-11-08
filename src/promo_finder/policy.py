"""Deterministic policy flags. Flags annotate; they never suppress lines."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import PROJECT_ROOT
from .models import Line


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").split())


def term_pattern(term: str) -> re.Pattern:
    phrase = r"\s+".join(re.escape(part) for part in normalize(term).split())
    return re.compile(r"(?<!\w)" + phrase + r"(?!\w)", re.UNICODE)


class PolicyScanner:
    def __init__(self, path: Path | None = None):
        raw = yaml.safe_load((path or PROJECT_ROOT / "config/policy_terms.yaml").read_text(encoding="utf-8"))
        self.categories = raw["categories"]
        self.combos = raw["combos"]
        self.patterns = {term: term_pattern(term) for terms in self.categories.values() for term in terms}
        for combo in self.combos.values():
            self.patterns.update({term: term_pattern(term) for side in combo.values() for term in side})
        self.flags: list[dict] = []

    def scan(self, lines: list[Line]) -> list[dict]:
        flags = []
        for line in lines:
            text = normalize(line.text)
            for category, terms in self.categories.items():
                for term in terms:
                    if self.patterns[term].search(text):
                        flags.append({"line_id": line.id, "category": category, "term": term})
            for category, combo in self.combos.items():
                left = [term for term in combo["left"] if self.patterns[term].search(text)]
                right = [term for term in combo["right"] if self.patterns[term].search(text)]
                for a in left:
                    for b in right:
                        flags.append({"line_id": line.id, "category": category, "term": f"{a} + {b}"})
        self.flags = list({(f["line_id"], f["category"], f["term"]): f for f in flags}.values())
        return self.flags

    def promo_flags(self, line_ids: list[str]) -> dict[str, list[str]]:
        selected = set(line_ids)
        result: dict[str, list[str]] = {}
        for flag in self.flags:
            ids = result.setdefault(flag["category"], []) if flag["line_id"] in selected else None
            if ids is not None and flag["line_id"] not in ids:
                ids.append(flag["line_id"])
        return result


def scan(lines: list[Line]) -> list[dict]:
    return PolicyScanner().scan(lines)
