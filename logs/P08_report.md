# P08 report: score once vs the sealed gold set

## PLAIN SUMMARY

- **What happened.** The tool and the single-prompt baseline were scored **once** against the sealed gold set using `eval/match_rule.md` v1. The run started at 2026-11-08T23:52:07Z and finished with `scoring_runs = 1` and no aborts. All 7 input hashes matched, and every built-in check passed.
- **Headline (τ = 0.5, K = 32, n = 16 positive gold promos).** The **tool recalled 3/16 (18.8%)** gold promos and the **baseline recalled 6/16 (37.5%)**. The tool's top 10 contained 1 match and the baseline's top 10 contained 3.
  - **Hook-hit:** tool 1/16, baseline 0/16.
  - **Negatives (promos the gold marks as bad):** the tool hit **0/6** and the baseline hit **5/6**.
  - **Paired comparison on G:** 2 gold promos were found only by the tool and 5 only by the baseline. Exact McNemar p = 0.453. Bootstrap mean(tool − baseline) = −0.19, 95% CI [−0.50, +0.13].
- **What it means.** With n = 16, every result is descriptive (match rule §5, §8): the intervals are about ±25 points wide, and the tool-vs-baseline difference is not distinguishable from zero.
  - The tool is more conservative: it never picks a promo the gold marks as bad, but it finds fewer good ones.
  - The baseline's higher recall comes with picking mostly episode openings, which the gold marks as negatives.
- **Main weakness found.** Candidate coverage, not judging.
  - The builder kept **0 candidates in held-out episodes 14, 43 and 45**, so 3 gold promos (B12, D12, D23) were unreachable.
  - One correct tool promo for D07 (tIoU 0.89) was ranked **33rd**, one place outside K. Under the pre-declared S_no_funnel order it lands at 32 and matches, which gives 4/16.
  - The tool's top 10 is dominated by episodes 28 and 29: 6 of 10 slots, none of which match a gold promo at τ 0.5.
- **AI labels vs Hariom's gold** (positives only, τ 0.5): match F1 was 0.56 for claude_v1 and 0.31 for gpt_v1, and 0.44 between the two AI labellers. Every κ comes from 5–9 matched pairs, so the κ values are weak evidence. Raw agreement is shown next to each κ.
- **Not done in P08 (by design).** No pipeline, prompt, config or frozen file changed. No LLM calls were made, nothing was pushed, and eval/gold.csv is not committed (D88).

---

## SELF-AUDIT

### Steps done

| Step | Status | Evidence |
|---|---|---|
| A1: clean tree, HEAD = origin/main = 21a995b, tests, guard | done, with one finding | `git rev-parse HEAD origin/main` → both `21a995b8…`. Tests: 598 passed. `tools/guard.py` clean. The tree was **not** clean: there was an untracked `src/promo_finder/scoring.py` (see Decisions). |
| A2: hashes | done, 5/5 match + L hashes recorded | see "Numbers" |
| A3: read match rule, L schema (field names only), checker | done | `eval/match_rule.md` read in full. L files: only `K`, `count`, `order_source` and field names read before scoring. Checker: `checker.check_promo`. tIoU: `tiou.set_tiou`. |
| A4: plan and questions | done, APPROVED | Q1–Q4 answered by Hariom |
| B1: scorer per match rule | done | `src/promo_finder/scoring.py`, `tools/score_p08.py` |
| B2: tests on invented fixtures | done | `tests/test_scoring.py`: 38 tests. Full suite 636 passed. |
| B3: stop for APPROVED - score once | done | |
| Pre-run: sha256 of unhashed inputs | done | see "Numbers" |
| C1: one run, `outputs/eval/metrics.json` with `scoring_runs: 1` | done | `python tools/score_p08.py score` → "hashes: 7/7 match; wrote outputs/eval/metrics.json (scoring_runs=1, label=result)", exit 0 |
| C2: `results/metrics.json` | done | numbers, definitions, n, promo/gold IDs only |
| C3: tables | done | Part C below |
| D1: failure catalogue (≥ 5 cases) | done, 8 cases | Part D below |
| D2: known-weakness counts | done | Part D below |
| D3: name check on gold rationale | done, 0 flagged | `gold.name_patterns` / `has_name` over `eval/gold.csv` rationale; count only, rationale never printed |
| E1: this report | done | |
| E2: stage allowed files; status / diff --stat / guard | done at the commit gate | see the commit-gate message |

### Decisions I made that the prompt did not specify

1. **The match rule's "rank i" means position in L.** P@10 and greedy order use the 1-based position in the L file, not the stored global `rank` field. The alternative, using the stored rank, would make "ranks 1–10 of L" refer to non-held-out promos.
2. **Hook-found greedy** (approved): each prediction takes the unmatched gold with the smallest |Δstart|. Ties go to the lowest gold_id.
3. **Bootstrap** (approved): `random.Random(12345).choices`, B = 10,000, numpy "linear" percentile.
4. **Wilson z** (approved): 1.959964. n = 0 is reported as "n/a (n=0)".
5. **Gold/AI rows.** Unresolvable line IDs or half-filled spans stop scoring. The 20–60 s and segment-count checks are not applied to labels; they are labels, not predictions.
6. **Undefined κ.** When expected agreement = 1, κ is reported as null with a note, beside the raw agreement. The alternative of reporting 1.0 would be misleading.
7. **Label-agreement ties.** Hariom specified "ties lower gold_id, then lower AI row id". For claude_v1 vs gpt_v1 this is generalised to the A side's gold_id, then the B side's row number.
8. **Score-once guard.** The tool refuses to run if `outputs/eval/metrics.json` exists. Every run, including aborted ones, is logged in `outputs/eval/scoring_ledger.json`. `--dev` would write `metrics_dev_N.json`; it was never used.
9. **The draft `scoring.py`** found untracked at Step 0 (dated 2026-11-09 05:08 local; never committed, never run: no `outputs/eval/` or `results/` existed) was **copied** to `.cache/tmp/scoring_draft_antigravity.py` (sha256 `e1b05fa3…`, identical). `scoring.py` was then rewritten fresh (Hariom Q1). Two of its defects were not carried over:
   - the label hook agreement ignored the episode;
   - rows without spans were dropped silently.

### Deviations from the prompt

1. **Pre-run code change.** Hariom's "score once" approval asked for aborts to be logged in the ledger, and the Part B tool did not do that yet. **Before** the run I added an abort handler (`Abort` → ledger entry "aborted, no metrics") and recorded the unhashed input sha256 values inside metrics.json. I also extended the hash-mismatch test to check the ledger entry. The full suite was re-run: 636 passed. No metric code changed.
2. **Wilson intervals added after the run.** `metrics.json` stores P@10, the exploratory long-list count and hook-within-2 s agreement as k/n without a Wilson interval. The prompt asks for "Wilson 95% for every share", so the intervals in this report's tables for those rows were **computed after the run from the stored k/n** with the same `scoring.wilson` function. No number was changed and nothing was re-scored. They are marked † below.
3. **Failure reasons are structural.** Reasons use timings, episode structure, builder drop counters, lanes and codes. I did not read script lines for the reasons, so as not to bring text into console output. Reasons therefore say *where* and *why structurally*, not what happens in the story.

### Numbers (each with its source file)

Input hashes (sha256 of LF bytes; matched `eval/HASHES.md` before the run and re-checked by the tool in-run):

| File | sha256 |
|---|---|
| eval/match_rule.md | d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2 |
| eval/gold.csv | e1a2287d724e7a46d2606c79562b6414d3d0a55324a276e189c5c183ef5bbdd4 |
| outputs/gold_sealed/gold_longlist_v1.csv | df6d7be38839630dcbf61cd66eb97346658fb46a27c1db52249d65edf7c2d03e |
| outputs/ai_labels/claude_v1.csv | fafdcc025d1154deed6571e5efa7d724d880933266d3eb4650f713942b7c7acb |
| outputs/ai_labels/gpt_v1.csv | 9229fa4625a4740fdb313184110084dce9f89e8e8d83e0f5ff9f00feb3c08573 |
| tool_held_out_L.json (recorded at Part A, before scoring) | 0b97d2aacca7ea69283a9efec0f76ff175d4eea11582ef5bc33ad8337f47d424 |
| baseline_held_out_L.json (recorded at Part A, before scoring) | 81d314bfa02df3f8d33da71766f4ee8113a43a1de982726049a1912062c24b1e |
| outputs/runs/full/ranked/promos_dev.json (not in HASHES.md; recorded pre-run) | b184587be24ca6c94c76024937768994f742be48b51dc134cac76c0ced8ffdf9 |
| outputs/runs/full/baseline/baseline_order.json (not in HASHES.md; recorded pre-run) | a96d1e707ce17e9031c4182db73d536fd290fdef3a70901642dd172bcbd0f9b2 |

Output hashes:
- `outputs/eval/metrics.json` 23f5aa90e8c691633da71f3aaf7e17bc64b10dd37f6e8891d9b5155a2cd1f927
- `results/metrics.json` c2edddbf49e9c5ba00b339b68879a108b10ff9883c4664e930ff395994aa0adb
- `outputs/eval/scoring_ledger.json` 53d2d614930d2ee2fa74c340e0b446d2c7195144557ef00068b676490c5a8940

All metric numbers in Part C come from `outputs/eval/metrics.json` (mirrored in `results/metrics.json`), except the † intervals (deviation 2). The Part D sources are named in each table.

### Tests

598 before + 38 new = **636 passed, 0 failures**. Each run used a fresh `--basetemp` under `.cache/tmp`, the last being `.cache/tmp/p08_c_pre3_*`.

### Frozen items

The following were untouched, with hashes re-checked after the run at the commit gate:
- `eval/match_rule.md`, `eval/gold_rubric.md`, `eval/gold.csv`, `eval/HASHES.md`
- `config/score_formula.yaml`, `config/eval_order.yaml`, `config/baseline.yaml`
- the line-ID format `E##-L###`

The `eval/HASHES.md` note for gold.csv says "file committed at P08". Per D88 it is **not** committed, and the note is left unchanged because the file is frozen (Hariom Q3).

### Held-out seal

- Before Part C, only the L files' field names and their `K` / `count` / `order_source` values were read. The tool and baseline L contents were first opened by the scoring run at 2026-11-08T23:52:07Z.
- Part D diagnostics read them afterwards.
- **Scoring runs: 1** (`outputs/eval/scoring_ledger.json`: one entry, status "completed"). There were no aborted or dev runs.

### Safety

- No push.
- No keys printed; `.env` was never opened (`load_config` reads only `config.yaml`).
- `guard.py` clean.
- No script text, dialogue or character names in the console, this report, `results/` or the commit. Gold/AI rationale fields were never printed.
- An extra speaker-name pattern scan was run over the 5 staged files. Its only hits are generic English words that match speaker-label patterns (cap, gold, high, judge, off, the, with). These are false positives, not character names.

### LLM calls

**0.** The scorer and diagnostics only read local files.

### Risks and open items for P09

1. **Candidate coverage.** The builder kept 0 candidates in 9 of 50 episodes: E14, E16, E43, E45 and E46–E50. Three of these are held-out, which cost 3 of 16 gold promos outright. The drops come mainly from J4 (two-segment promos whose segments share no speaker), `resolution` and TOO_SHORT. This needs a decision on whether to relax the rules or add a single-segment fallback. Any such change is a new version, and the held-out set is now spent.
2. **Episode concentration in ranking.** E28 and E29 take 6 of the top 10 slots. A per-episode cap or a diversity rule at ranking time is worth testing, on dev episodes only.
3. **Judge questions barely discriminate** (#40/#49): `spoils_ending` = no in 214/214 runs and `ends_unresolved` = yes in 210/214.
4. **The baseline's apparent recall leans on episode openings** (5/6 negatives hit). Any future comparison should report negative-hit next to recall.
5. **n = 16** (15 of them grade 3). Every comparison is descriptive.
6. **Decision log.** `decisions/DECISION_LOG.md`, which the match rule references, is not in the repo; P09 copies it in (Hariom Q4).

---

## Part A: Step 0 (summary)

- HEAD = origin/main = `21a995b`. Tests: 598 passed. Guard clean.
- One untracked draft `scoring.py` (handled as Decision 9).
- All 5 reference hashes matched `eval/HASHES.md`, as did the 4 other frozen files (rubric, formula, eval_order, baseline).
- Gold: 16 positives (15 grade 3, 1 grade 2) and 6 negatives.
- K = 2 × 16 = 32. Tool |L| = 55, baseline |L| = 45, both ≥ K.

## Part B: scorer

- `scoring.py` is pure computation; `tools/score_p08.py` handles I/O and the checks.
- Built-in stop checks, all of which passed:
  - tool ms rebuilt from line IDs with the P01 checker equal the stored ms;
  - every promo in both L files lies fully in held-out episodes;
  - K in both files = 2|G|;
  - the baseline L rebuilt from `baseline_order.json` equals the sealed baseline L;
  - the stored `sensitivity_order_S_no_funnel` (held-out only) equals the independent re-implementation and equals the tool L promo set.

## Part C: results (scored once; n = 16; descriptive only, match rule §5, §8)

### C1. Tool vs baseline at τ = 0.5 (K = 32)

| Metric (definition in results/metrics.json) | Tool | Baseline |
|---|---|---|
| \|L\| / K used | 55 / 32 | 45 / 32 |
| **Recall@32** | **3/16 = 0.188** [0.066, 0.430] | **6/16 = 0.375** [0.185, 0.614] |
| Hook-hit | 1/16 = 0.062 [0.011, 0.283] | 0/16 = 0.000 [0.000, 0.194] |
| Hook-found (diagnostic) | 2/16 = 0.125 [0.035, 0.360] | 0/16 = 0.000 [0.000, 0.194] |
| P@10 (denominator min(10, \|L\|) = 10) | 1/10 = 0.10 [0.018, 0.404]† | 3/10 = 0.30 [0.108, 0.603]† |
| Negative-hit rate (n = 6) | 0/6 = 0.000 [0.000, 0.390] | 5/6 = 0.833 [0.436, 0.970] |
| Recall, grade 3 | 3/15 = 0.200 [0.070, 0.452] | 6/15 = 0.400 [0.198, 0.643] |
| Recall, grade 2 | 0/1 = 0.000 [0.000, 0.793] | 0/1 = 0.000 [0.000, 0.793] |
| Recall, grade 1 | n/a (n=0) | n/a (n=0) |

Matches at τ 0.5 (position in L, promo, gold, tIoU):
- **Tool:** (1, P05-E02-003, A07, 0.690), (21, P05-E12-001, B05, 0.771), (23, P05-E44-001, D16, 0.669)
- **Baseline:** (3, BL-E04-1, A17, 0.547), (6, BL-E13-1, B08, 0.716), (8, BL-E26-1, C02, 0.730), (20, BL-E12-2, B05, 0.647), (24, BL-E27-2, C08, 0.772), (27, BL-E42-2, D07, 0.926)

### C2. Sensitivity τ = 0.3 / 0.7

| | Tool Recall@32 | Tool P@10 | Baseline Recall@32 | Baseline P@10 |
|---|---|---|---|---|
| τ 0.3 | 5/16 = 0.312 [0.142, 0.556] | 2/10 [0.057, 0.510]† | 9/16 = 0.562 [0.332, 0.769] | 5/10 [0.237, 0.763]† |
| τ 0.5 | 3/16 = 0.188 [0.066, 0.430] | 1/10 [0.018, 0.404]† | 6/16 = 0.375 [0.185, 0.614] | 3/10 [0.108, 0.603]† |
| τ 0.7 | 1/16 = 0.062 [0.011, 0.283] | 0/10 [0.000, 0.278]† | 4/16 = 0.250 [0.102, 0.495] | 2/10 [0.057, 0.510]† |

### C3. Baseline sensitivity row (20–60 s check off; §6)

|L| = 52, K used 32.
- Recall@32: 6/16 = 0.375 [0.185, 0.614]
- Hook-hit: 0/16
- Hook-found: 0/16
- P@10: 3/10†
- Negative-hit: 4/6 = 0.667 [0.300, 0.903]
- Grade 3: 6/15
- τ 0.3: 9/16; τ 0.7: 4/16

It matches the same 6 gold promos as the primary baseline. Each moves down one or two positions because the extra (formerly dropped) promos are inserted ahead of them.

### C4. S_no_funnel order (D62; frozen `sensitivity_order_S_no_funnel`, verified against the re-implementation)

- Recall@32: 4/16 = 0.250 [0.102, 0.495]
- Hook-hit: 2/16 = 0.125 [0.035, 0.360]
- Hook-found: 3/16 = 0.188 [0.066, 0.430]
- P@10: 1/10†
- Negative-hit: 0/6
- Grade 3: 4/15
- τ 0.3: 6/16; τ 0.7: 2/16

Compared with the primary order, D07 is added (P05-E42-001 moves from position 33 to 32, tIoU 0.891, hook-hit).

### C5. Paired tool vs baseline on G (τ 0.5, n = 16)

| | |
|---|---|
| Tool-only matches / baseline-only matches / discordant | 2 / 5 / 7 |
| Exact McNemar, two-sided | p = 0.453 |
| Paired bootstrap mean(a − b) | −0.1875, 95% CI [−0.500, +0.125] (B = 10,000, seed 12345) |

### C6. EXPLORATORY (D46): tool top 10 vs the long list

5 of the tool's top 10 reach tIoU ≥ 0.5 with **any** of the 44 long-list positives (5/10 [0.237, 0.763]†). This compares with 1/10 against the 16-promo gold. It is exploratory only: the long list is a broader, ungraded pool and is not the evaluation set.

### C7. AI-label agreement (D43; positives only; global greedy; |A| = |B| = 16 in every pair)

| Pair | F1 τ 0.3 | F1 τ 0.5 | F1 τ 0.7 | Pairs @0.5 | Hook ±2 s | hook_type κ (raw) | cliff_type κ (raw) | grade wκ-linear (raw) |
|---|---|---|---|---|---|---|---|---|
| gold vs claude_v1 | 0.562 (9) | 0.562 (9) | 0.375 (6) | 9 | 2/9 [0.063, 0.547]† | 0.169 (0.333) | 0.735 (0.778) | −0.174 (0.667) |
| gold vs gpt_v1 | 0.375 (6) | 0.312 (5) | 0.062 (1) | 5 | 2/5 [0.118, 0.769]† | 0.211 (0.400) | 0.348 (0.400) | 0.000 (0.800) |
| claude_v1 vs gpt_v1 | 0.562 (9) | 0.438 (7) | 0.375 (6) | 7 | 4/7 [0.250, 0.842]† | 0.533 (0.714) | 0.641 (0.714) | 0.000 (0.429) |

- No pair has n < 5, so none is labelled "too small to interpret". All pairs are still small (5–9).
- The grade κ values are near 0 or negative even where raw agreement is high, because almost every grade is 3. Read the raw % instead.
- The claude_v1 vs gpt_v1 grade κ came out as 3.9e-16, which is floating-point zero, so the table shows 0.000.

## Part D: where the tool picks badly (held-out opened after scoring)

### D1. Failure catalogue

Sources: `outputs/eval/metrics.json` (diagnostics), the tool and baseline L files, `outputs/runs/full/promos/build_summary.json` and `outputs/runs/full/ranked/promos_dev.json`.

| # | ID(s) | Line IDs | Failure type | Reason (structural, own words) |
|---|---|---|---|---|
| 1 | gold B12 (grade 3), D12 (grade 3), D23 (grade 2) | B12: E14-L007..E14-L019 + E14-L047..E14-L050; D12: E43-L057..E43-L087; D23: E45-L060..E45-L074 | gold missed: **no candidate at all** | The builder kept 0 of 16 / 22 / 35 generated candidates in E14 / E43 / E45. E14 lost 11 to TOO_SHORT, 3 to J4 and 2 to resolution. E43 lost 12 to J4, 7 to resolution and 3 to TOO_SHORT. E45 lost 28 to J4 and 7 to resolution. Hook and cliff moments existed in all three episodes (5 hooks each), but no assembled promo survived the rules. |
| 2 | gold D07 (grade 3); tool P05-E42-001 | gold E42-L021..E42-L037; tool E42-L021..E42-L034 | gold missed: **ranked just outside K** | The tool built an almost exact promo (tIoU 0.891, same start) but ranked it 33rd of 55 (S = 0.508, needs_human: flip_rate), one place past K = 32. The baseline caught this one (0.926). |
| 3 | tool P05-E28-004 (pos 2), P05-E28-002 (pos 5), P05-E28-003 (pos 7) | E28-L053..E28-L057 + E28-L090..E28-L096; E28-L071..E28-L096; E28-L071..E28-L087 | tool top-10 promo matching **no gold** (tIoU 0 with every gold) | All three come from the second half of episode 28 (from 70.8 s). The gold promo for E28 (C11, E28-L028..E28-L051, 34.9–70.2 s) sits entirely before them. They are three near-duplicate cuts of the same late stretch, together taking 3 top-10 slots. |
| 4 | tool P05-E29-004 (pos 8), P05-E29-002 (pos 4) | E29-L013..E29-L034; E29-L032..E29-L044 | top-10 no match / **near miss** | E29 has four promos in the top 8. Pos 4 overlaps gold C17 (E29-L036..E29-L056) at tIoU 0.380: it ends at 71.4 s, while the gold runs to 88.8 s, so the tool cuts off before the gold's ending. Pos 8 sits earlier still (21.0–56.5 s) and overlaps no gold. |
| 5 | gold C02 (grade 3); tool P05-E26-001 (pos 29) | gold E26-L037..E26-L051; tool E26-L015..E26-L016 + E26-L042..E26-L049 | **near miss** (0.3 ≤ tIoU < 0.5) | tIoU 0.380. The tool's second segment lies inside the gold span, but its first segment is a short insert from much earlier (30.8–40.2 s) and it drops the gold's opening 10 s. The baseline matched this gold (0.730). |
| 6 | gold A07 (grade 3); tool P05-E02-003 (pos 1) and gold B05; tool P05-E12-001 (pos 21) | A07 E02-L052..E02-L074 vs tool E02-L055..E02-L071; B05 E12-L024..E12-L045 vs tool E12-L016..E12-L043 | **wrong hook start** (matched, no hook-hit) | Both are matched at τ 0.5. The tool's first line starts 5.0 s after the gold hook for A07 and 5.6 s before it for B05, so the opening beat differs from the editor's choice by more than the 2 s tolerance. |
| 7 | gold B08 (grade 3); tool P05-E13-004 (pos 24) | gold E13-L005..E13-L025; tool E13-L004..E13-L007 + E13-L062..E13-L065 | **hook-found but not matched** | The tool opens on the same beat (within 2 s), but after 9 s it jumps to a late-episode payoff (89.2–103.0 s), so the overlap is only 0.16. Gold keeps the continuous early scene. |
| 8 | baseline BL-E02-1, BL-E43-2, BL-E45-1, BL-E02-3, BL-E13-2 hitting negatives A09, D14, D25, A10, B11 | e.g. BL-E02-1 E02-L001..E02-L022 vs neg A09 E02-L001..E02-L021 (tIoU 0.941) | **baseline negatives hit** | The baseline's first promo in many episodes starts at 0.0 s (episode opening). The gold marks openings as negatives (codes N1 and N6), so 5/6 negatives are hit. Some of its recall comes from broad early-episode coverage. |

Baseline invented timestamps and drops (held-out episodes; source: `outputs/runs/full/baseline/baseline_E##.json`, also in metrics.json `baseline_context`):
- 4 timestamps outside the episode length before snapping;
- 7 promos dropped after snapping (TOO_SHORT 6, TOO_LONG 1);
- 0 drops with the duration check off.

### D2. Counts for known weaknesses (full run unless stated)

Sources: `outputs/runs/full/ranked/promos_dev.json` (195 promos: all 50 episodes; 55 held-out), `outputs/runs/full/understanding/reveals_E##.json`, `outputs/runs/full/promos/build_summary.json`, `outputs/runs/full/p07b_live_results.json` and `outputs/runs/pilot/d82_judge_only.json`.

**needs_human lane by reason (#55).** Each row has exactly one reason.

| Reason | All 50 eps (81 rows) | Held-out (27 rows) |
|---|---|---|
| policy flag | 7 | 3 |
| flip rate | 11 | 6 |
| spoiler | 0 | 0 |
| unjudged tail (`missing_evidence`, judge not selected) | 63 | 18 |
| other | 0 | 0 |

- Lanes, all 50 episodes: launch_batch 5, reserve 109, needs_human 81.
- Lanes, held-out: launch_batch 4, reserve 24, needs_human 27.

**Judge answers (#40/#49).** 214 successful judge runs over 132 judged promos. Held-out: 63 runs over 37 promos.

| Question | Per run (all) | Per run (held-out) | Aggregate per promo (all) |
|---|---|---|---|
| ends_unresolved | yes 210 / no 4 | yes 61 / no 2 | yes 130 / no 2 |
| spoils_ending | no 214 / yes 0 | no 63 / yes 0 | no 132 / yes 0 |

- Flip rate, judged promos: 0.0 ×12, 0.2 ×18, 0.4 ×11.

**Resolution confidence (#39)** (`reveals_E##.json` marks, 50 episodes):
- resolution: high 63, medium 8, low 0;
- reveal: high 106, medium 6.
- Held-out, all types: high 53, medium 7.
- Promos flagged `contains_low_conf_resolution`: 0/195.
- Builder resolution drops, held-out: 66 of 405 generated.

**Content-filtered:**
- **0** in the P07b full run (`p07b_live_results.json`: `CONTENT_FILTERED_requests` = 0);
- **7** in the pilot (`outputs/runs/pilot/d82_judge_only.json`: `content_filtered_requests` = 7).

**Builder funnel, held-out** (`build_summary.json`): 405 generated, 55 kept. Dropped:
- J4 171
- resolution 66
- dedupe 49
- checker 41 (TOO_SHORT 36, MONTAGE_CONSTRUCTION 5)
- speakers 14
- cap 9

Episodes with 0 kept, all 50: E14, E16, E43, E45, E46, E47, E48, E49, E50.

### D3. Name check on eval/gold.csv rationale (#13)

Out of 22 rows, the existing name guard (`promo_finder.gold.name_patterns` + `has_name`, speaker set from the parsed scripts) flagged **0**. Count only; the rationale was not printed. gold.csv is not committed (D88).
