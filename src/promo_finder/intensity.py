"""Text-free, deterministic per-line intensity profiles."""

from __future__ import annotations

import re

from .config import IntensityCfg
from .models import Episode
from .policy import PolicyScanner, normalize, term_pattern

WORDS = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)


def profile(episode: Episode, cfg: IntensityCfg | None = None, scanner: PolicyScanner | None = None) -> list[dict]:
    cfg = cfg or IntensityCfg()
    scanner = scanner or PolicyScanner()
    allowed = set(scanner.categories["violence"]) | set(scanner.categories["shock_fear"])
    if not set(cfg.action_terms) <= allowed:
        raise ValueError("intensity action terms must come from violence/shock policy terms")
    patterns = [term_pattern(term) for term in cfg.action_terms]
    emotions = {tag.strip().lower() for tag in cfg.strong_emotions}
    rows, raw_scores = [], []
    previous_speaker = None
    for line in episode.lines:
        words = WORDS.findall(line.text)
        dialogue = line.kind == "dialogue"
        features = {
            "exclamations": line.text.count("!"),
            "questions": line.text.count("?"),
            "all_caps_words": sum(sum(c.isalpha() for c in w) >= 2 and w.isupper() for w in words),
            "strong_emotion": int(dialogue and (line.emotion or "").strip().lower() in emotions),
            "sfx": int(line.kind == "sfx"),
            "action_violence_shock": int(line.kind == "action" and any(p.search(normalize(line.text)) for p in patterns)),
            "speaker_change": int(dialogue and previous_speaker is not None and line.speaker != previous_speaker),
            "short_dialogue": int(dialogue and 1 <= len(words) <= 4),
        }
        if dialogue:
            previous_speaker = line.speaker
        raw_scores.append(sum(cfg.weights[name] * value for name, value in features.items()))
        rows.append({"line_id": line.id, "score": 0.0, "smooth": 0.0, "features": features})
    if not rows:
        return rows
    low, high = min(raw_scores), max(raw_scores)
    for row, raw in zip(rows, raw_scores):
        row["score"] = (raw - low) / (high - low) if high != low else 0.0
    for i, row in enumerate(rows):
        neighbors = rows[max(0, i - 1):i + 2]
        row["smooth"] = sum(n["score"] for n in neighbors) / len(neighbors)
    return rows
