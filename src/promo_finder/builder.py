"""Code-only promo construction. All exported times come from the checker."""

from __future__ import annotations

import json
import math
import statistics
import sys
from difflib import SequenceMatcher

from . import moments, reveals
from .checker import build_index, check_promo
from .config import Config, PromoCfg
from .finding import HeldOutRefused, check_selection, read_json
from .labelling import HELD_OUT, parse_eps
from .models import Episode
from .parser import FILENAME_RE, find_episode_files, parse_file
from .policy import PolicyScanner
from .tiou import set_tiou
from .understanding import DEV_SPEC, load_requested, validate_inputs
from .understanding_common import UnderstandingError, validate, write_json

RULES = ("checker", "J2", "J4", "speakers", "resolution", "reveal", "late_series", "dedupe", "cap")


def normalized_recap(text: str) -> str:
    return " ".join("".join(char for char in text.lower() if char.isalnum() or char.isspace()).split())


def previous_episode(cfg: Config, episode: Episode, selected: dict[int, Episode]) -> Episode | None:
    number = episode.ep - 1
    # This check precedes any source discovery or parsing for the predecessor.
    if number < 1 or number in HELD_OUT:
        return None
    if number in selected:
        return selected[number]
    paths = [path for path in find_episode_files(cfg.data_dir)
             if (match := FILENAME_RE.match(path.name)) and int(match.group(1)) == number]
    if not paths:
        return None
    if len(paths) != 1:
        raise UnderstandingError("duplicate recap predecessor")
    previous = parse_file(paths[0])
    validate_inputs([previous])
    if previous.ep != number:
        raise UnderstandingError("recap predecessor episode mismatch")
    return previous


def recap_lines(episode: Episode, previous: Episode | None, cfg: Config) -> tuple[set[str], str]:
    if episode.ep <= 1 or previous is None or previous.ep in HELD_OUT:
        return {line.id for line in episode.lines if 0 <= line.start_ms < cfg.builder.recap_fallback_s * 1000}, "fallback"
    if previous.ep != episode.ep - 1:
        raise UnderstandingError("recap predecessor episode mismatch")
    tail = [normalized_recap(line.text) for line in previous.lines[-cfg.builder.recap_prev_tail_lines:]]
    ids = {line.id for line in episode.lines[:cfg.builder.recap_scan_lines]
           if any(SequenceMatcher(None, normalized_recap(line.text), text).ratio() >= cfg.builder.recap_similarity
                  for text in tail)}
    return ids, "similarity"


def _provenance(data: dict) -> dict:
    meta = data.get("metadata", {})
    if not all(isinstance(meta.get(key), str) and meta[key] for key in ("model_string", "cache_key")):
        raise UnderstandingError("missing call provenance")
    return {key: meta[key] for key in ("model_string", "cache_key")}


def validate_artifacts(episode: Episode, moment_data: dict, reveal_data: dict,
                       intensity: list, policy: list) -> None:
    if moment_data.get("episode") != episode.ep or reveal_data.get("episode") != episode.ep:
        raise UnderstandingError("artifact episode mismatch")
    if reveal_data.get("metadata", {}).get("version") != 2:
        raise UnderstandingError("build requires reveals v2")
    _provenance(moment_data)
    _provenance(reveal_data)
    raw = {"hook_starts": moment_data["hook_starts"], "cliff_ends": []}
    for item in moment_data["cliff_ends"]:
        if item.get("source") not in ("model", "episode_end"):
            raise UnderstandingError("invalid cliff source")
        raw["cliff_ends"].append({key: value for key, value in item.items() if key != "source"})
    validate(raw, moments.schema(episode))
    validate({"marks": reveal_data["marks"]}, reveals.schema(episode))
    ids = {line.id for line in episode.lines}
    if not isinstance(intensity, list) or len(intensity) != len(ids):
        raise UnderstandingError("intensity coverage mismatch")
    seen = set()
    for row in intensity:
        value = row.get("smooth")
        if row.get("line_id") not in ids or row["line_id"] in seen or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise UnderstandingError("invalid intensity artifact")
        seen.add(row["line_id"])
    if not isinstance(policy, list) or any(not isinstance(row, dict) or row.get("line_id") not in ids or
            not all(isinstance(row.get(key), str) for key in ("category", "term")) for row in policy):
        raise UnderstandingError("invalid policy artifact")


def _limits(cfg: Config) -> PromoCfg:
    return cfg.promo.model_copy(update={"max_segments": min(cfg.promo.max_segments, cfg.builder.max_segments)})


def _measure(spans, index, cfg: Config):
    return check_promo(spans, index, PromoCfg(min_s=0, max_s=cfg.promo.max_s, max_segments=2))


def montage_spans(episode: Episode, hook: str, cliff: str, index, cfg: Config):
    lines = episode.lines
    positions = {line.id: i for i, line in enumerate(lines)}
    a, c = positions[hook], positions[cliff]
    first = None
    for end in range(a, c):
        if lines[end].scene != lines[a].scene:
            break
        measured = _measure([(hook, lines[end].id)], index, cfg)
        if not measured.ok or measured.total_ms > cfg.builder.montage_first_max_s * 1000:
            break
        if measured.total_ms >= cfg.builder.montage_first_min_s * 1000:
            first = (hook, lines[end].id)
            break
    if first is None:
        return None
    first_end = positions[first[1]]
    for start in range(c, first_end, -1):
        if lines[start].start_ms < index[first[1]].end_ms:
            break
        spans = [first, (lines[start].id, cliff)]
        measured = _measure(spans, index, cfg)
        if not measured.ok:
            return None
        if measured.total_ms >= cfg.promo.min_ms:
            return spans if check_promo(spans, index, _limits(cfg)).ok else None
    return None


def include_reactions(episode: Episode, spans, index, cfg: Config):
    spans = list(spans)
    positions = {line.id: i for i, line in enumerate(episode.lines)}
    cut, included = False, 0
    for number, (first, last) in enumerate(list(spans)):
        pos = positions[last] + 1
        if pos >= len(episode.lines) or episode.lines[pos].kind not in ("action", "camera"):
            continue
        reaction = episode.lines[pos]
        proposed = list(spans)
        proposed[number] = first, reaction.id
        checked = check_promo(proposed, index, _limits(cfg))
        allowed = checked.ok
        if len(spans) == 2:
            allowed = allowed and reaction.scene == index[last].scene
            if number == 0:
                allowed = allowed and reaction.scene == index[first].scene
                allowed = allowed and reaction.end_ms - index[first].start_ms <= cfg.builder.montage_first_max_s * 1000
            if checked.segments and len(checked.segments) == 2:
                p, q = checked.segments
                allowed = allowed and p.end_ms <= q.start_ms
        if allowed:
            spans = proposed
            included += 1
        else:
            cut = True
    return spans, cut, included


def answers_question(episode: Episode, spans, index) -> bool:
    for first, _ in spans:
        line = index[first]
        if line.kind != "dialogue" or not line.speaker:
            continue
        previous = next((old for old in reversed(episode.lines) if old.idx < line.idx and old.kind == "dialogue"), None)
        if previous and previous.speaker and previous.speaker != line.speaker and previous.text.rstrip().endswith("?"):
            return True
    return False


def _speakers(segment, index) -> set[str]:
    return {index[key].speaker for key in segment.line_ids if index[key].kind == "dialogue" and index[key].speaker}


def _sort_key(promo: dict):
    return (-promo["pre_score"], promo["montage"], promo["_hook_order"], promo["_cliff_order"],
            tuple((seg["first_line_id"], seg["last_line_id"]) for seg in promo["segments"]))


def dedupe_cap(candidates: list[dict], cfg: Config) -> tuple[list[dict], dict]:
    def times(promo):
        return [(seg["episode"], seg["start_ms"], seg["end_ms"]) for seg in promo["segments"]]
    kept, dropped = [], {"dedupe": 0, "cap": 0}
    for promo in sorted(candidates, key=_sort_key):
        if any(set_tiou(times(promo), times(old)) > cfg.builder.dedupe_tiou for old in kept):
            dropped["dedupe"] += 1
        else:
            kept.append(promo)
    dropped["cap"] = max(0, len(kept) - cfg.builder.max_per_episode)
    return kept[:cfg.builder.max_per_episode], dropped


def build_episode(episode: Episode, moment_data: dict, reveal_data: dict, intensity: list,
                  policy: list, cfg: Config, previous: Episode | None = None) -> tuple[dict, dict]:
    validate_artifacts(episode, moment_data, reveal_data, intensity, policy)
    index = build_index([episode])
    recap_ids, recap_method = recap_lines(episode, previous, cfg)
    scanner = PolicyScanner()
    scanner.flags = policy
    smooth = {row["line_id"]: row["smooth"] for row in intensity}
    reveal_ids = {mark["line_id"] for mark in reveal_data["marks"] if mark["type"] == "reveal"}
    resolution_ids = {mark["line_id"] for mark in reveal_data["marks"] if mark["type"] == "resolution"}
    summary = {"generated": 0, "dropped": {rule: 0 for rule in RULES}, "kept": 0,
               "checker_errors": {}, "reactions_included": 0, "reaction_cut_candidates": 0,
               "recap": {"method": recap_method, "recap_lines": len(recap_ids),
                         "flagged_generated": {"similarity": 0, "fallback": 0},
                         "flagged_kept": {"similarity": 0, "fallback": 0}}}
    survivors = []
    for hook in moment_data["hook_starts"]:
        for cliff in moment_data["cliff_ends"]:
            if index[hook["line_id"]].idx >= index[cliff["line_id"]].idx:
                continue
            summary["generated"] += 1
            spans = [(hook["line_id"], cliff["line_id"])]
            checked = check_promo(spans, index, _limits(cfg))
            if checked.errors == ["TOO_LONG"]:
                spans = montage_spans(episode, hook["line_id"], cliff["line_id"], index, cfg)
                if spans is None:
                    summary["dropped"]["checker"] += 1
                    summary["checker_errors"]["MONTAGE_CONSTRUCTION"] = summary["checker_errors"].get("MONTAGE_CONSTRUCTION", 0) + 1
                    continue
            elif not checked.ok:
                summary["dropped"]["checker"] += 1
                for error in checked.errors:
                    summary["checker_errors"][error] = summary["checker_errors"].get(error, 0) + 1
                continue
            spans, reaction_cut, reactions = include_reactions(episode, spans, index, cfg)
            checked = check_promo(spans, index, _limits(cfg))
            if not checked.ok:
                summary["dropped"]["checker"] += 1
                for error in checked.errors:
                    summary["checker_errors"][error] = summary["checker_errors"].get(error, 0) + 1
                continue
            summary["reactions_included"] += reactions
            summary["reaction_cut_candidates"] += reaction_cut
            if answers_question(episode, spans, index):
                summary["dropped"]["J2"] += 1
                continue
            speakers = [_speakers(seg, index) for seg in checked.segments]
            if len(speakers) == 2 and not speakers[0] & speakers[1]:
                summary["dropped"]["J4"] += 1
                continue
            if len(set().union(*speakers)) > cfg.builder.max_speakers:
                summary["dropped"]["speakers"] += 1
                continue
            ids = [key for seg in checked.segments for key in seg.line_ids]
            recap = ids[0] in recap_ids
            if recap:
                summary["recap"]["flagged_generated"][recap_method] += 1
            flags = {"possible_recap": recap, "reaction_cut": reaction_cut, "contains_reveal": bool(set(ids) & reveal_ids)}
            montage = len(spans) == 2
            score = int(hook["strength"]) + int(cliff["strength"]) + sum(smooth[key] for key in ids) / len(ids)
            score -= sum(getattr(cfg.builder.penalties, flag) for flag in ("possible_recap", "reaction_cut") if flags[flag])
            score -= cfg.builder.penalties.montage if montage else 0
            survivors.append({"episode": episode.ep, "segments": [
                {"episode": seg.ep, "start_ms": seg.start_ms, "end_ms": seg.end_ms,
                 "first_line_id": seg.line_ids[0], "last_line_id": seg.line_ids[-1]} for seg in checked.segments],
                "line_ids": ids, "duration_s": checked.total_ms / 1000,
                "hook": {"line_id": hook["line_id"], "type": hook["hook_type"], "strength": hook["strength"]},
                "cliff": {"line_id": cliff["line_id"], "type": cliff["cliff_type"], "strength": cliff["strength"], "source": cliff["source"]},
                "pre_score": score, "flags": flags, "policy": scanner.promo_flags(ids), "montage": montage,
                "provenance": {"moments": _provenance(moment_data), "reveals": _provenance(reveal_data)},
                "_hook_order": index[hook["line_id"]].idx, "_cliff_order": index[cliff["line_id"]].idx})
    branches = {}
    for mode in ("block", "flag"):
        pool = []
        drops = dict(summary["dropped"])
        for promo in survivors:
            if set(promo["line_ids"]) & resolution_ids:
                drops["resolution"] += 1
            elif episode.ep >= cfg.spoiler.late_series_start:
                drops["late_series"] += 1
            elif mode == "block" and promo["flags"]["contains_reveal"]:
                drops["reveal"] += 1
            else:
                pool.append(promo)
        kept, end_drops = dedupe_cap(pool, cfg)
        drops.update(end_drops)
        branches[mode] = {"pre_dedupe_kept": len(pool), "kept": kept, "dropped": drops}
    chosen = branches[cfg.spoiler.reveal_mode]
    summary.update(dropped=chosen["dropped"], kept=len(chosen["kept"]), reveal_mode=cfg.spoiler.reveal_mode,
                   reveal_mode_comparison={mode: {"pre_dedupe_kept": branch["pre_dedupe_kept"], "kept": len(branch["kept"])}
                                           for mode, branch in branches.items()})
    result = []
    for number, promo in enumerate(chosen["kept"], 1):
        spans = [(seg["first_line_id"], seg["last_line_id"]) for seg in promo["segments"]]
        if not check_promo(spans, index, _limits(cfg)).ok:
            raise UnderstandingError("final checker invariant failed")
        summary["recap"]["flagged_kept"][recap_method] += promo["flags"]["possible_recap"]
        result.append({"promo_id": f"P03-E{episode.ep:02d}-{number:03d}",
                       **{key: value for key, value in promo.items() if not key.startswith("_")}})
    if summary["generated"] != sum(summary["dropped"].values()) + summary["kept"]:
        raise UnderstandingError("builder accounting invariant failed")
    return {"episode": episode.ep, "candidates": result}, summary


def _time(ms: int) -> str:
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def review(episodes: list[Episode], outputs: dict[int, dict]) -> str:
    lines = ["# DEV review", ""]
    dev = set(parse_eps(DEV_SPEC))
    for episode in episodes:
        if episode.ep not in dev:
            continue
        index = build_index([episode])
        promos = outputs[episode.ep]["candidates"][:2]
        lines.extend([f"## E{episode.ep:02d}: {len(promos)} promos shown", ""])
        for promo in promos:
            lines.extend([f"### {promo['promo_id']} — {promo['hook']['type']} / {promo['cliff']['type']}", ""])
            for seg in promo["segments"]:
                lines.extend([f"{_time(seg['start_ms'])}–{_time(seg['end_ms'])}", ""])
            for key in promo["line_ids"]:
                line = index[key]
                text = " ".join(line.text.split())
                lines.append(f"- {key} | {line.kind} | {line.speaker or ''} | {text}")
            lines.append("")
    return "\n".join(lines) + "\n"


def run(cfg: Config, episodes: list[Episode], *, allow_held_out: bool = False) -> dict:
    check_selection([episode.ep for episode in episodes], allow_held_out)
    validate_inputs(episodes)
    selected = {episode.ep: episode for episode in episodes}
    prepared = []
    for episode in episodes:
        number = f"E{episode.ep:02d}"
        moment_data = read_json(cfg.root / f"outputs/moments/moments_{number}.json")
        reveal_data = read_json(cfg.root / f"outputs/understanding/reveals_{number}.json")
        intensity = read_json(cfg.root / f"outputs/understanding/intensity_{number}.json")
        policy = read_json(cfg.root / f"outputs/understanding/policy_{number}.json")
        validate_artifacts(episode, moment_data, reveal_data, intensity, policy)
        prepared.append((episode, moment_data, reveal_data, intensity, policy, previous_episode(cfg, episode, selected)))
    outputs, summaries = {}, {}
    for episode, moment_data, reveal_data, intensity, policy, previous in prepared:
        outputs[episode.ep], summaries[f"E{episode.ep:02d}"] = build_episode(
            episode, moment_data, reveal_data, intensity, policy, cfg, previous)
    all_promos = [promo for data in outputs.values() for promo in data["candidates"]]
    durations = [promo["duration_s"] for promo in all_promos]
    recap = {method: sum(s["recap"]["flagged_kept"][method] for s in summaries.values()) for method in ("similarity", "fallback")}
    summary = {"episodes": summaries, "kept": len(all_promos),
               "duration_s": {"min": min(durations) if durations else None,
                              "median": statistics.median(durations) if durations else None,
                              "max": max(durations) if durations else None},
               "montage_count": sum(p["montage"] for p in all_promos),
               "montage_share": sum(p["montage"] for p in all_promos) / len(all_promos) if all_promos else 0,
               "recap_flagged_kept_by_method": recap,
               "reveal_mode_comparison": {mode: sum(s["reveal_mode_comparison"][mode]["kept"] for s in summaries.values())
                                          for mode in ("block", "flag")}}
    # All requested artifacts and results are validated before replacing outputs.
    for episode in episodes:
        write_json(cfg.root / f"outputs/promos/candidates_E{episode.ep:02d}.json", outputs[episode.ep])
    write_json(cfg.root / "outputs/promos/build_summary.json", summary)
    path = cfg.root / "outputs/promos/dev_review.md"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(review(episodes, outputs), encoding="utf-8")
    temporary.replace(path)
    return summary


def cmd_build(cfg: Config, args) -> int:
    try:
        eps = parse_eps(args.eps)
        check_selection(eps, args.allow_held_out)
        episodes = load_requested(cfg, eps, args.allow_held_out)
        print(json.dumps(run(cfg, episodes, allow_held_out=args.allow_held_out), sort_keys=True))
        return 0
    except HeldOutRefused as exc:
        print(f"build: {exc}; error={exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print("build: failed; error=" + getattr(exc, "code", type(exc).__name__), file=sys.stderr)
        return 1
