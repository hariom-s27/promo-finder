# MATCH RULE (frozen), version 1, 5 Nov 2026

This file fixes how tool and baseline promos are scored against the gold set.
It is hashed (sha256 of its LF bytes, recorded in `eval/HASHES.md`) and committed BEFORE any gold label exists.
Any change after hashing = a new version, a new entry in `decisions/DECISION_LOG.md`, and the change is reported in the write-up.
Sources: decisions D04, D05 and H1-1 to H1-11; research DR09.

## 1. What a promo is
- A promo is an ordered list of segments `(episode, start_ms, end_ms)`.
- Gold and tool segments are both produced from line IDs (`E##-L###`) by the SAME P01 timestamp checker function. No timestamp is typed by hand.
- The baseline is the only exception (free timestamps); see Section 6.
- The time set of a promo in episode e = the union of its segments in e (overlaps merged).

## 2. Overlap measure (set tIoU)
- tIoU(p, g) = Σ_e |P_e ∩ G_e| / Σ_e |P_e ∪ G_e|, summed over episodes e.
- Computed in milliseconds with exact interval arithmetic. Episodes are compared separately; time never crosses an episode boundary.

## 3. The evaluation set
- Held-out episodes: 1–4, 11–14, 26–29, 42–45.
- G = the positive gold promos (grade 1–3). Negatives (grade 0) are not in G.
- L = the tool's ranked output, keeping only promos whose segments ALL lie in held-out episodes, in the tool's rank order. Ties are broken by output order.
- K = 2 × |G|, fixed when the gold file is hashed. If L has fewer than K promos, all of L is used and |L| is reported.

## 4. Matching
- Threshold τ: primary 0.5; sensitivity 0.3 and 0.7 (each a separate matching run).
- Greedy by rank: for i = 1..K, prediction p_i takes the unmatched gold promo with the highest tIoU ≥ τ (ties: lowest gold_id).
- Each gold promo is matched at most once; each prediction matches at most one gold promo.

## 5. Metrics (every number reported with its definition and n)
- **Primary: Recall@K** = matched gold promos / |G|, at τ = 0.5. Wilson 95% interval.
- **Hook-hit (the pre-named hook metric):** gold g counts if it is matched at τ = 0.5 AND the matched prediction's first segment is in the same episode as g's first segment AND |Δstart| ≤ 2,000 ms. Reported as a share of |G|, Wilson 95%.
- **Hook-found (diagnostic only):** gold g counts if some prediction in the top K has its first segment in the same episode as g's first segment with |Δstart| ≤ 2,000 ms, whatever the tIoU. Greedy one-to-one by rank, like Section 4. Share of |G|, Wilson 95%.
- **Precision@10:** matches (from the τ = 0.5 matching of Section 4) among ranks 1–10 of L, divided by min(10, |L|). |L| reported.
- **Recall by grade (descriptive):** Recall@K split by grade 3 / 2 / 1.
- **Negative-hit rate:** share of negatives that have tIoU ≥ 0.5 with ANY prediction in the top K (not one-to-one). Wilson 95%. Computed only at P08.
- **Tool vs baseline (paired, on G):** a_i = 1 if the tool matched gold i, b_i = 1 if the baseline did.
  - Exact McNemar test, two-sided, on the discordant pairs.
  - Paired bootstrap of mean(a − b): B = 10,000 resamples, seed 12345, percentile 95% interval.
- With n ≈ 15, all results are descriptive (95% intervals are about ±25 points). The write-up says so.

## 6. Baseline
- The baseline returns free timestamps.
- Before snapping, any timestamp outside the episode's length is counted as an "invented timestamp" (reported).
- Snapping: each segment start → the nearest line START in that episode; each segment end → the nearest line END in that episode (line start/end as defined by the P01 timestamp checker; ties → the earlier line).
- After snapping, the same P01 timestamp checker runs. Promos that are still invalid (unknown episode, end ≤ start, outside 20–60 s, segments out of order) are dropped and count as misses. The count of drops and the reasons are reported.
- Sensitivity row: the baseline scored with the 20–60 s check turned off.
- The baseline's ranked list = its output order. L and K for the baseline follow Section 3.

## 7. Score once
- Held-out tool and baseline outputs are opened for the first time at P08.
- One scoring run. Any re-run is counted and reported; numbers from a run after any change are labelled "dev", not results.

## 8. Statement
- The single labeller (Hariom) read the whole show before labelling. Gold reflects one person's editor judgement and is incomplete; equally good promos may exist outside it.
