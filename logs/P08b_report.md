# P08b report: v2 and two separately scored fresh blocks

9 November 2026. Prepared for Hariom at the commit gate.

## Plain summary

The approved F2+F5b version completed its live run and was scored once on each fresh block. It did not improve primary Recall@K over v1 in either block. On block A, both versions recalled 2/8 (25%); on block B, both recalled 1/4 (25%). The matched gold IDs are identical within each block, so neither paired comparison has a discordant pair. This describes the observed labels; it does not establish equivalence between versions.

The baseline recalled 4/8 on A and 3/4 on B. Its negative-hit rate was 1/2 on A and 1/1 on B, compared with v2's 0/2 and 0/1 respectively. These very small negative sets provide weak evidence about safety or quality.

Held-out v2 Recall@32 was 3/16, equal to official v1's count. It gained A02 and lost D16. This is **post-hoc (after seeing v1 results)**, not a fresh result. Official P08 files remain unchanged.

Block A and block B are reported separately throughout. There is no pooled metric, paired test, or ledger.

## Required disclosures and limits

- **Duplicate HASHES row:** `eval/gold_fresh.csv` appears twice, recorded at 2026-11-09T02:11:59Z and 02:45:21Z (commits `350b7e5` and `db93018`). Both rows contain sha256 `40db75a8ffd04cb4d274f44f77415470cbf1e95b066ca448166922f10611a0e7`, 1,321 LF bytes, and both match the file. All 16 HASHES rows, representing 15 distinct files, verified before scoring and were rechecked during each scoring command. The duplicate was left untouched.
- **Pilot exposure in block B:** episodes 15-17 were pilot episodes. Only counts and a few promo IDs were ever seen; no spans or content were seen. This user-supplied clarification qualifies the fresh-block history. No script text, dialogue or character names were inspected for this report.
- **Selection bias:** B consists of episodes 15, 16, 17 and 35, selected before its gold existed by the greatest symmetric difference between v1/v2 kept-candidate sets (ties: lower episode). Counts were E17=6, E35=4, E15=3, E16=3. The selection favours episodes changed by v2; it is not a random sample and cannot estimate an effect across the show.
- **Actual block B size:** 4 positives and 1 negative, so **K=8** and **one gold changes recall by 25 percentage points**. The frozen rule's approximate planning prose mentions about 8 positives; actual counts and K=2|G| govern this run. The validator's warning about 4 positives being outside 6-10 was retained as a warning, with zero errors.
- Block A has 8 positives and 2 negatives, K=16; one gold changes recall by 12.5 points. Its v1/v2 lists differ at only position 31 of 32, outside K, so its primary contrast is null by construction.
- **Ten what-ifs were tried on the already-seen held-out set.** Fresh blocks are the tests of the resulting version; held-out improvement cannot validate the choice. No new window sizes or what-ifs were tried in this scoring session.
- The single labeller had read the entire show. Gold is one person's incomplete editorial judgement. Samples are small and every result is descriptive. The zero-width paired bootstrap intervals when vectors are identical reflect only these observed vectors and are not proof of zero population effect.

## What changed in v2

Only `builder.too_short_mode: extend` and `builder.resolution_mode: flag_unless_end` are enabled by `config/v2.yaml`; defaults preserve v1.

- F2 extends only the end of a too-short clip, to the first line boundary reaching 20 seconds. It may include the next cliff line but never pass it; it stops before medium/high resolution. If it cannot reach minimum duration it is dropped. `extended` is a flag with no penalty.
- F5b still drops a clip when a medium/high resolution line is final or ends within the last 3 seconds of the final segment. Earlier resolution is retained with `contains_blocking_resolution`, a fixed 0.5 pre-score penalty and the `needs_human` lane. The 3-second window is fixed.
- Final score S, prompts, models, judge quota (top 4), temperatures and frozen evaluation order are unchanged. Lane labels do not reorder evaluation. F1, F3 and F4 were excluded.
- Fresh/fresh_b labelling commands, count-only diagnostics, list generation and sealing, v1 regression fixtures, run reporting and the score-once tool are included in the pending change. All label CSVs remain ignored and guard-blocked.

## Verification and scoring procedure

Approval was the user's explicit `APPROVED - score once`, including A=8/2 and B=4/1, separate ledgers, and held-out v2 post-hoc. No further approval was needed for these runs.

Before reading labels as CSV or lists as JSON, `tools/score_p08b.py` checked every HASHES row, both duplicate rows, the exact L_seal bytes, all seven new list hashes, both original P08 lists (raw and LF-normalized hashes), their sealed source inputs, the block B rule, the previous seal copy, the completed run manifest and its overlay, and the original P08 metrics hash. Any mismatch stops the tool without scoring. Nothing was repaired or resealed.

`L_seal.json` sha256: `b5ed3ab3a7e62a90302f0a806aba6a641abf146220945a0e566825a8e4ea9bbb`. Previous seal copy: `df19752c14f0be932312c5193de7c36751399e4bf6c916054ad9cc7cea6ff04f`.

The scorer reuses `promo_finder.scoring` without changing it. Gold validation and rationale-name checks passed in all three splits. Tool timestamps were reconstructed with the existing line-ID checker and required to equal stored milliseconds; every prediction had to lie fully in its split. Each tool list was rebuilt from stored ranking and compared with its sealed order; baseline lists were rebuilt from the frozen round-robin order. Sensitivity uses stored baseline outputs with the 20-60 second check disabled. No LLM or network requests were made by scoring.

Each block reserves a ledger with `scoring_runs=1` before reading gold labels or matching. Completed or aborted attempts prevent another primary run. There were no aborts or dev runs. Inputs were verified again before metrics were written. Source-code fingerprints are recorded in each ledger and metrics file.

Commands, run exactly once each after the final 804-test pass:

```text
.venv/Scripts/python.exe -B tools/score_p08b.py score --block a
.venv/Scripts/python.exe -B tools/score_p08b.py score --block b
.venv/Scripts/python.exe -B tools/score_p08b.py held-out
```

Held-out v1 and baseline numbers were loaded from the unchanged official P08 metrics, not rescored. Original P08 `scoring_runs` remains 1.

## Metric definitions

Set tIoU uses exact integer milliseconds per episode, merging interval overlaps. Greedy matching visits ranks 1..K and takes the unmatched gold with highest tIoU at or above tau, ties to lowest gold ID. Primary tau is 0.5; sensitivities are 0.3 and 0.7. Recall is matches/positive gold. Hook-hit requires a primary match plus first-segment start within 2,000 ms in the same episode; hook-found is a hook-only greedy diagnostic. Negative-hit is the share of negative labels overlapping any top-K prediction at tau>=0.5, without one-to-one matching. Grade recall uses each grade's positive count.

P@10 is the matches from that same top-K matching with position<=10, divided by min(10,|L|). For B, K=8 stays fixed: positions 9-10 cannot add matches, and the denominator is still 10. This follows the frozen rule and original scorer; K was not increased for P@10.

Tables give k/n, the share and Wilson 95% interval (z=1.959964). Zero denominators are n/a. Exact McNemar is two-sided. Paired bootstrap uses 10,000 resamples, seed 12345, linear percentile 95%; differences below are fractions, not percentage points. Only fresh v2 Recall@K and the paired v2-vs-v1 contrasts are primary; all other figures are descriptive. The held-out rows are all post-hoc.

## Fresh block A: episodes 31-34

G=8, negatives=2, K=16. Source: `outputs/eval/p08b_fresh_a/metrics.json`; public copy: `results/p08b_a.json`.

| Metric | v2 | v1 | baseline | baseline_sensitivity_no_20_60 |
|---|---|---|---|---|
| L size / K used | 32 / 16 | 32 / 16 | 14 / 14 | 14 / 14 |
| recall_at_K | 2/8 = 0.250 [0.071, 0.591] | 2/8 = 0.250 [0.071, 0.591] | 4/8 = 0.500 [0.215, 0.785] | 4/8 = 0.500 [0.215, 0.785] |
| hook_hit | 1/8 = 0.125 [0.022, 0.471] | 1/8 = 0.125 [0.022, 0.471] | 2/8 = 0.250 [0.071, 0.591] | 2/8 = 0.250 [0.071, 0.591] |
| hook_found | 3/8 = 0.375 [0.137, 0.694] | 3/8 = 0.375 [0.137, 0.694] | 2/8 = 0.250 [0.071, 0.591] | 2/8 = 0.250 [0.071, 0.591] |
| precision_at_10 | 1/10 = 0.100 [0.018, 0.404] | 1/10 = 0.100 [0.018, 0.404] | 2/10 = 0.200 [0.057, 0.510] | 2/10 = 0.200 [0.057, 0.510] |
| negative_hit_rate | 0/2 = 0.000 [0.000, 0.658] | 0/2 = 0.000 [0.000, 0.658] | 1/2 = 0.500 [0.095, 0.905] | 1/2 = 0.500 [0.095, 0.905] |
| Recall grade 3 | 2/8 = 0.250 [0.071, 0.591] | 2/8 = 0.250 [0.071, 0.591] | 4/8 = 0.500 [0.215, 0.785] | 4/8 = 0.500 [0.215, 0.785] |
| Recall grade 2 | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| Recall grade 1 | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) |

Threshold sensitivity (each threshold uses its own frozen greedy matching):

| tau | system | Recall@K [Wilson 95%] | P@10 [Wilson 95%] |
|---|---|---|---|
| 0.3 | v2 | 2/8 = 0.250 [0.071, 0.591] | 1/10 = 0.100 [0.018, 0.404] |
| 0.3 | v1 | 2/8 = 0.250 [0.071, 0.591] | 1/10 = 0.100 [0.018, 0.404] |
| 0.3 | baseline | 6/8 = 0.750 [0.409, 0.929] | 3/10 = 0.300 [0.108, 0.603] |
| 0.3 | baseline_sensitivity_no_20_60 | 6/8 = 0.750 [0.409, 0.929] | 3/10 = 0.300 [0.108, 0.603] |
| 0.5 | v2 | 2/8 = 0.250 [0.071, 0.591] | 1/10 = 0.100 [0.018, 0.404] |
| 0.5 | v1 | 2/8 = 0.250 [0.071, 0.591] | 1/10 = 0.100 [0.018, 0.404] |
| 0.5 | baseline | 4/8 = 0.500 [0.215, 0.785] | 2/10 = 0.200 [0.057, 0.510] |
| 0.5 | baseline_sensitivity_no_20_60 | 4/8 = 0.500 [0.215, 0.785] | 2/10 = 0.200 [0.057, 0.510] |
| 0.7 | v2 | 1/8 = 0.125 [0.022, 0.471] | 0/10 = 0.000 [0.000, 0.278] |
| 0.7 | v1 | 1/8 = 0.125 [0.022, 0.471] | 0/10 = 0.000 [0.000, 0.278] |
| 0.7 | baseline | 2/8 = 0.250 [0.071, 0.591] | 1/10 = 0.100 [0.018, 0.404] |
| 0.7 | baseline_sensitivity_no_20_60 | 2/8 = 0.250 [0.071, 0.591] | 1/10 = 0.100 [0.018, 0.404] |

Paired comparisons on the positive labels of this block only:

| Comparison | n | v2-only / comparator-only | McNemar p | Mean difference [bootstrap 95%] |
|---|---|---|---|---|
| v2_vs_v1 | 8 | 0 / 0 | 1 | 0.0000 [0.000, 0.000] |
| v2_vs_baseline | 8 | 0 / 2 | 0.5 | -0.2500 [-0.625, 0.000] |

Matched positive gold at tau=0.5:

- v2: F05, F06.
- v1: F05, F06.
- baseline: F03, F05, F06, F07.
- baseline_sensitivity_no_20_60: F03, F05, F06, F07.

Baseline context: 0 invented timestamps; 0 dropped predictions; drop reasons {}; 0 sensitivity drops. With no duration-related drops in this block, the 20-60-off row equals its primary baseline metrics. Validation: zero errors, zero rationale-name hits. Warnings: none.

## Fresh block B: episodes 15-17,35

G=4, negatives=1, K=8. Source: `outputs/eval/p08b_fresh_b/metrics.json`; public copy: `results/p08b_b.json`.

| Metric | v2 | v1 | baseline | baseline_sensitivity_no_20_60 |
|---|---|---|---|---|
| L size / K used | 26 / 8 | 14 / 8 | 12 / 8 | 12 / 8 |
| recall_at_K | 1/4 = 0.250 [0.046, 0.699] | 1/4 = 0.250 [0.046, 0.699] | 3/4 = 0.750 [0.301, 0.954] | 3/4 = 0.750 [0.301, 0.954] |
| hook_hit | 0/4 = 0.000 [0.000, 0.490] | 0/4 = 0.000 [0.000, 0.490] | 1/4 = 0.250 [0.046, 0.699] | 1/4 = 0.250 [0.046, 0.699] |
| hook_found | 0/4 = 0.000 [0.000, 0.490] | 0/4 = 0.000 [0.000, 0.490] | 1/4 = 0.250 [0.046, 0.699] | 1/4 = 0.250 [0.046, 0.699] |
| precision_at_10 | 1/10 = 0.100 [0.018, 0.404] | 1/10 = 0.100 [0.018, 0.404] | 3/10 = 0.300 [0.108, 0.603] | 3/10 = 0.300 [0.108, 0.603] |
| negative_hit_rate | 0/1 = 0.000 [0.000, 0.793] | 0/1 = 0.000 [0.000, 0.793] | 1/1 = 1.000 [0.207, 1.000] | 1/1 = 1.000 [0.207, 1.000] |
| Recall grade 3 | 1/3 = 0.333 [0.061, 0.792] | 1/3 = 0.333 [0.061, 0.792] | 2/3 = 0.667 [0.208, 0.939] | 2/3 = 0.667 [0.208, 0.939] |
| Recall grade 2 | 0/1 = 0.000 [0.000, 0.793] | 0/1 = 0.000 [0.000, 0.793] | 1/1 = 1.000 [0.207, 1.000] | 1/1 = 1.000 [0.207, 1.000] |
| Recall grade 1 | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) |

Threshold sensitivity (each threshold uses its own frozen greedy matching):

| tau | system | Recall@K [Wilson 95%] | P@10 [Wilson 95%] |
|---|---|---|---|
| 0.3 | v2 | 1/4 = 0.250 [0.046, 0.699] | 1/10 = 0.100 [0.018, 0.404] |
| 0.3 | v1 | 2/4 = 0.500 [0.150, 0.850] | 2/10 = 0.200 [0.057, 0.510] |
| 0.3 | baseline | 3/4 = 0.750 [0.301, 0.954] | 3/10 = 0.300 [0.108, 0.603] |
| 0.3 | baseline_sensitivity_no_20_60 | 3/4 = 0.750 [0.301, 0.954] | 3/10 = 0.300 [0.108, 0.603] |
| 0.5 | v2 | 1/4 = 0.250 [0.046, 0.699] | 1/10 = 0.100 [0.018, 0.404] |
| 0.5 | v1 | 1/4 = 0.250 [0.046, 0.699] | 1/10 = 0.100 [0.018, 0.404] |
| 0.5 | baseline | 3/4 = 0.750 [0.301, 0.954] | 3/10 = 0.300 [0.108, 0.603] |
| 0.5 | baseline_sensitivity_no_20_60 | 3/4 = 0.750 [0.301, 0.954] | 3/10 = 0.300 [0.108, 0.603] |
| 0.7 | v2 | 0/4 = 0.000 [0.000, 0.490] | 0/10 = 0.000 [0.000, 0.278] |
| 0.7 | v1 | 0/4 = 0.000 [0.000, 0.490] | 0/10 = 0.000 [0.000, 0.278] |
| 0.7 | baseline | 1/4 = 0.250 [0.046, 0.699] | 1/10 = 0.100 [0.018, 0.404] |
| 0.7 | baseline_sensitivity_no_20_60 | 1/4 = 0.250 [0.046, 0.699] | 1/10 = 0.100 [0.018, 0.404] |

Paired comparisons on the positive labels of this block only:

| Comparison | n | v2-only / comparator-only | McNemar p | Mean difference [bootstrap 95%] |
|---|---|---|---|---|
| v2_vs_v1 | 4 | 0 / 0 | 1 | 0.0000 [0.000, 0.000] |
| v2_vs_baseline | 4 | 0 / 2 | 0.5 | -0.5000 [-1.000, 0.000] |

Matched positive gold at tau=0.5:

- v2: FB01.
- v1: FB01.
- baseline: FB01, FB02, FB03.
- baseline_sensitivity_no_20_60: FB01, FB02, FB03.

Baseline context: 0 invented timestamps; 0 dropped predictions; drop reasons {}; 0 sensitivity drops. With no duration-related drops in this block, the 20-60-off row equals its primary baseline metrics. Validation: zero errors, zero rationale-name hits. Warnings: WARNING total positives 4 outside 6-10 (~8).

## Held-out v2: post-hoc (after seeing v1 results)

G=16, negatives=6, K=32. Source: `outputs/eval/p08b_held_out_posthoc/metrics.json`; public copy: `results/p08b_held_out.json`.

| Metric | v2 | v1_official | baseline_official |
|---|---|---|---|
| L size / K used | 79 / 32 | 55 / 32 | 45 / 32 |
| recall_at_K | 3/16 = 0.188 [0.066, 0.430] | 3/16 = 0.188 [0.066, 0.430] | 6/16 = 0.375 [0.185, 0.614] |
| hook_hit | 1/16 = 0.062 [0.011, 0.283] | 1/16 = 0.062 [0.011, 0.283] | 0/16 = 0.000 [0.000, 0.194] |
| hook_found | 3/16 = 0.188 [0.066, 0.430] | 2/16 = 0.125 [0.035, 0.360] | 0/16 = 0.000 [0.000, 0.194] |
| precision_at_10 | 2/10 = 0.200 [0.057, 0.510] | 1/10 = 0.100 [0.018, 0.404] | 3/10 = 0.300 [0.108, 0.603] |
| negative_hit_rate | 0/6 = 0.000 [0.000, 0.390] | 0/6 = 0.000 [0.000, 0.390] | 5/6 = 0.833 [0.436, 0.970] |
| Recall grade 3 | 3/15 = 0.200 [0.070, 0.452] | 3/15 = 0.200 [0.070, 0.452] | 6/15 = 0.400 [0.198, 0.643] |
| Recall grade 2 | 0/1 = 0.000 [0.000, 0.793] | 0/1 = 0.000 [0.000, 0.793] | 0/1 = 0.000 [0.000, 0.793] |
| Recall grade 1 | n/a (n=0) | n/a (n=0) | n/a (n=0) |

Threshold sensitivity (each threshold uses its own frozen greedy matching):

| tau | system | Recall@K [Wilson 95%] | P@10 [Wilson 95%] |
|---|---|---|---|
| 0.3 | v2 | 5/16 = 0.312 [0.142, 0.556] | 3/10 = 0.300 [0.108, 0.603] |
| 0.3 | v1_official | 5/16 = 0.312 [0.142, 0.556] | 2/10 = 0.200 [0.057, 0.510] |
| 0.3 | baseline_official | 9/16 = 0.562 [0.332, 0.769] | 5/10 = 0.500 [0.237, 0.763] |
| 0.5 | v2 | 3/16 = 0.188 [0.066, 0.430] | 2/10 = 0.200 [0.057, 0.510] |
| 0.5 | v1_official | 3/16 = 0.188 [0.066, 0.430] | 1/10 = 0.100 [0.018, 0.404] |
| 0.5 | baseline_official | 6/16 = 0.375 [0.185, 0.614] | 3/10 = 0.300 [0.108, 0.603] |
| 0.7 | v2 | 1/16 = 0.062 [0.011, 0.283] | 0/10 = 0.000 [0.000, 0.278] |
| 0.7 | v1_official | 1/16 = 0.062 [0.011, 0.283] | 0/10 = 0.000 [0.000, 0.278] |
| 0.7 | baseline_official | 4/16 = 0.250 [0.102, 0.495] | 2/10 = 0.200 [0.057, 0.510] |

Paired comparisons on the positive labels of this block only:

| Comparison | n | v2-only / comparator-only | McNemar p | Mean difference [bootstrap 95%] |
|---|---|---|---|---|
| v2_vs_v1 | 16 | 1 / 1 | 1 | 0.0000 [-0.188, 0.188] |
| v2_vs_baseline | 16 | 2 / 5 | 0.453125 | -0.1875 [-0.500, 0.125] |

Matched positive gold at tau=0.5:

- v2: A02, A07, B05.
- v1_official: A07, B05, D16.
- baseline_official: A17, B05, B08, C02, C08, D07.

## Structural cases from the saved scoring diagnostics

These cases use IDs, positions and overlap values only. Best overlaps refer to the scored top K, not the entire candidate pool; zero-overlap ties do not identify a meaningful best promo. No script content or gold rationale was used to infer story-level causes.

| Case | Observation | Implication |
|---|---|---|
| A: F02 | Best v2 top-16 tIoU=0.292339 at position 5 | Still below even tau=0.3; no primary match. |
| A: F03 and F07 | v2 best overlaps 0.194836 and 0.200675; baseline matches both at 0.5 | These account for the two baseline-only gold positives. |
| A: F05 | v2 match at position 6, tIoU=0.676329; its matched start fails the 2-second hook test | Recall can succeed while hook-hit fails. |
| A: F06 | v2 exact match at position 13, tIoU=1.0 | Counts in Recall@16 and hook-hit, outside the P@10 numerator. |
| B: FB01 | v2 matches at position 2, tIoU=0.683594; v1 at position 6, tIoU=0.529412 | Better overlap and earlier position do not change the matched-gold vector. Neither passes the hook test. |
| B: FB02 and FB03 | v2 best top-8 overlap=0.145791 and 0.0; baseline matches both | Candidate growth did not turn these labels into primary top-K matches. |
| B: FB04 | v1 best top-8 overlap=0.441860, v2=0.065041 | At tau=0.3 v1 recalls 2/4 and v2 1/4; this is a descriptive sensitivity difference. |
| A: F10 / B: FB05 (negative labels) | Baseline overlaps=0.676020 and 0.681159; tool versions miss these negatives | Higher baseline positive recall comes with these negative hits. The negative samples are too small for broad claims. |
| Held-out: A02 versus D16 | v2 adds A02 (tIoU=0.5 at rank 3), loses the official v1 match D16 | Total recall stays 3/16 despite changed matched IDs; paired discordance is 1 versus 1. |

## Interpretation

The builder changes increased overall kept candidates from 195 to 263 and judged/scored candidates from 132 to 166. Held-out kept candidates rose 55 to 79 and empty episodes fell from 3 to 0. These are coverage counts, not recall improvements. Block B has 26 v2 candidates versus 14 v1 candidates, but only the first 8 of either list count at K=8. At primary tau, both find the same one gold. Extra candidates and better overlap for FB01 did not produce a measured fresh recall gain.

The earlier held-out what-if pool recall of 7/16 was an in-sample, any-kept-candidate diagnostic, not a prediction of top-32 recall. The actual post-hoc top-32 recall is 3/16. Do not substitute the pool number for the measured result.

On these labelled blocks v2 remains more conservative than the baseline, with fewer good labels found and fewer bad labels hit. Tiny samples, incomplete single-labeller gold, B's selection bias and pilot history prevent stronger generalisation. No further fixes, prompt changes, threshold changes or tuning were performed after scoring.

## Live run and cache history

The already-approved v2 run finished all 7 stages in 1,091 seconds, with 631 logical calls, 240 HTTP requests out of a 791 cap, and 391 cache hits. Reported-usage list-price cost was USD 0.25884782 (about 0.259) versus the USD 6.805 ceiling. There were zero HTTP errors and zero content filters. Baseline, understand and find reused the copied v1 cache; the copy was hash-verified and the source left intact. The earlier offline probe directory `outputs/runs/c3_probe` was never opened in this session.

The live run used uncommitted implementation code; its manifest records a dirty working tree and its earlier `code_fingerprint.json` records 53 source files. Each scoring ledger additionally records the actual scoring/source-code fingerprints. This report does not retroactively claim that the run used committed code.

## E4-E5: report, checks and commit gate

- Added the fresh scorer and 16 invented-fixture tests. The final full suite passed **804 tests** (636 original + 168 P08b tests), zero failures, in 28.25 seconds. The tests cover conflicting duplicate hashes, changed sealed files and sources, exact seal pinning, independent ledgers, repeated-run refusal, aborted-run refusal, timestamps, split membership, K<10, baseline context counts and reuse of official results. All pytest runs used fresh basetemp/cache directories inside `.cache/tmp`, with TEMP/TMP set there; `.cache/pytest-tmp` was untouched.
- All three scoring ledgers completed with `scoring_runs=1`. A and B have separate metrics, public result files and ledgers; held-out has its own explicitly post-hoc output. No scoring command was repeated and the original official P08 outputs were preserved.
- Gold validation found zero errors and zero names in rationales across A, B and held-out (counts only). B's low-positive warning is disclosed above. No label, script, workbook, cache or secret is included in the commit scope.
- Frozen match rules, rubric, template, score formula, ranking order, baseline configuration and HASHES were not edited. No code used for scoring was changed after the run.
- The pending scope includes the earlier approved P08b implementation, its tests and rule files, this scorer/test, the report and the three results JSON files. Gate verification passed: all-file guard clean (146 files), staged guard clean (35 files), staged whitespace check clean, all 16 HASHES rows and seals still match, and every saved metrics/public-result hash and source fingerprint verifies. Exactly 35 allowed files are staged; no unstaged changes remain. HEAD remains `db93018`. **Stopped at the commit gate; no commit or push was performed.**

## Artifact hashes

Metrics and ledgers below live under git-ignored `outputs/`. Public results contain metric values, IDs, definitions and provenance; gold CSVs and script content are excluded. Each ledger records its own completed metrics hash and public-result hash.

| Artifact | sha256 |
|---|---|
| `outputs/eval/p08b_fresh_a/metrics.json` | `0345f0751ad52584a2ac1e0f7dae7c1b217bcd75d881c54130c1ca3aaa72a510` |
| `outputs/eval/p08b_fresh_a/scoring_ledger.json` | `e7b491d9f0f403f523e47470b6b2558782efd789d4098b6b3f785f6e14083e2b` |
| `results/p08b_a.json` | `c628d47444b594cc5bfbfbaae1c297dd21e0fb3efe4c7d3405c4f4fda9b414ff` |
| `outputs/eval/p08b_fresh_b/metrics.json` | `1898ca71fa41e8e6cff6987e65800690c4a19397106b6183d88b409810a41103` |
| `outputs/eval/p08b_fresh_b/scoring_ledger.json` | `43155fe7a3b7f03e8690ff1a138d46919af929bf5b9d10b4f2ba19a0af32618f` |
| `results/p08b_b.json` | `42fb75af15976932aa64cbe4687b96700ff07fdab8847b4acb1f010d54dcb0bd` |
| `outputs/eval/p08b_held_out_posthoc/metrics.json` | `1789da8ec3b92519109e49ba05d3fe21aebef208d6818341145c22fea8d5346f` |
| `outputs/eval/p08b_held_out_posthoc/scoring_ledger.json` | `cc72200a9227c4b3c836ff6c7b4633f60724fd69443aa697043a95a6204e43c9` |
| `results/p08b_held_out.json` | `e5bb4a108e56130d9afa0b0ca158ffe1f103b9c43200085c0d796c623be76459` |

Preserved official P08 hashes: `outputs/eval/metrics.json` = `23f5aa90e8c691633da71f3aaf7e17bc64b10dd37f6e8891d9b5155a2cd1f927`; `results/metrics.json` = `c2edddbf49e9c5ba00b339b68879a108b10ff9883c4664e930ff395994aa0adb`; original `outputs/eval/scoring_ledger.json` = `53d2d614930d2ee2fa74c340e0b446d2c7195144557ef00068b676490c5a8940`.
