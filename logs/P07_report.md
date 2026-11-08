PLAIN SUMMARY

- What happened: D82 implemented nested provider-filter metadata and `CONTENT_FILTERED` classification, passed **598 tests**, then ran only pilot judge/rank with upstream cache enforcement. Coverage remains **12/16 selected** (12/20 retained). Source: `outputs/runs/pilot/d82_judge_only.json` and `d82_final_tests.xml`.
- What it means: Of **8** fresh requests, **7** were `CONTENT_FILTERED`, all labelled `MultiSeverity_ViolenceScore`; one new cold sample succeeded. **D82 outcome = guardrail change did not recover the 7 filtered requests; accepted as CONTENT_FILTERED (D82 b).** This disposition is Hariom's approval; the request counts come from `d82_judge_only.json` and canonical metadata after the `d82_rerun_context.json` offset. No filtered sample was retried. Five answer keys, eighteen cold samples and twelve fidelity calls were cache hits. All upstream file hashes remained unchanged.
- Problems: Four selected items remain unscored. One has a successful third planned cold sample, but its first cold sample was filtered, so the unchanged fidelity dependency rule skips fidelity; it remains unscored. Hariom reports setting output violence to block High only; the application did not inspect or change the provider policy and does not infer why these requests still blocked. Source: pilot judge/rank artifacts and `d82_judge_only.json`.
- Decision needed (options + your pick): None for this commit: Hariom approved committing the accumulated P07 worktree plus both byte-unchanged frozen configurations after hash and guard verification. The earlier restriction meant do not MODIFY frozen files; adding the already-approved files is authorized. The final approved gate is recorded below. No push is authorized.
- Exact next message for Hariom to send to the chat: Record both approved config hashes in eval/HASHES.md using the printed hash_eval commands, then verify them.

SELF-AUDIT

1. Steps done: Copied/verified the previous D80 pilot arm; added nested choice/prompt filter parsing, label-only extraction and permanent filtered-failure classification; ran fake-response tests; reran only pilot judge/rank from cache; reported coverage, remaining failures, distributions, lanes and launch; prepared the commit gate and recorded Hariom's D82 b acceptance and corrected approval to add the frozen configs. Sources: `d82_judge_only.json`, `d82_final_tests.xml`, `d82_commit_gate.json`, and the approved commit gate below.
2. Decisions I made that the prompt did not specify: Also classify a successful-HTTP response with explicit nested blocked-filter metadata before JSON parsing/caching, preventing empty-response retries. Retain HTTP status alongside the classification. Reset the consecutive-429 streak on a filtered non-429 response. Cached successful D80 judgments remain usable; only missing cold results needed live requests.
3. Deviations from the prompt: None in the authorized stage scope. The same D80 task-local wrapper, renamed for D82 artifacts, enforced cached keys and unchanged upstream hashes. The frozen schedule still has independent shuffled samples for repeated items; each failed sample was sent once, with no transport/validation retry. The earlier gate excluded two untracked frozen configs; Hariom corrected that wording and explicitly approved staging both with their approved bytes unchanged.
4. Numbers: Current coverage, distributions, lanes, launch IDs, request counts, caches, tokens and reported-usage cost are sourced to `outputs/runs/pilot/d82_judge_only.json`. Reported-usage cost is **USD 0.00109056**; unreported failed-request usage remains unknown. No inferred usage or billing value was fabricated.
5. Tests: **598 passed, 0 failures/errors** (**583 existing + 15 D82**), source `outputs/runs/pilot/d82_final_tests.xml`. Fake tests cover nested choice/prompt errors, whitelist-only labels, malformed/safe flags, no retry/cache on blocking, HTTP 200 blocking and unscored items. All pytest attempts used fresh basetemps under `.cache/tmp`; `.cache/pytest-tmp` was untouched. One initial shell-option invocation collected no tests; the corrected full invocations passed.
6. Frozen items: Formula, eval order, baseline, eval documents and HASHES remain unchanged; D80's adopted standalone line remains active. No other prompt, schema, temperature, purpose cap, formula or ranking rule changed. The approved 20K TPM/20 RPM limits and 85% pacing remain configured. Final proof: `d82_final_verification.json`.
7. Held-out seal: Only pilot 9,10,15,16,17 was judged/ranked. No upstream generation, held-out understanding/judging, gold labels or 50-episode execution occurred. No script/dialogue/name/AI free text was copied into report or console. Existing historical D81 guarded provider diagnostics remain historical.
8. Safety: No real `.env` inspection or secret output; application code alone loaded credentials. No application endpoint/filter setting change. Raw bodies and error-message text are not logged by the fix; only known label names, codes and existing category flags are retained. Old Groq/llama_v1 arms remain preserved; D80 pilot copy verifies **156 files**, inventory `6b4ba61866f2fc9a478aebfc003eb1130be19a4d445604f61a9e66923a690440`.
9. LLM calls: D82 made **8** fresh Foundry requests under retained cap **88**, no picker HTTP requests, and **7** filtered failures without retry. The remaining calls were cache hits. Returned Foundry model: `llama70`; fixed `json_object` and `max_completion_tokens` protocol stayed in use. Source: `d82_judge_only.json`, `llm` and `http_error_metadata`.
10. Risks and open items: Coverage remains 12/16 and launch shortfall remains one. D82 b accepts the seven remaining requests as CONTENT_FILTERED; no further attempt to resolve them was made. Both frozen configs are included under Hariom's corrected approval, with approved hashes required in the worktree and index. Only Hariom will append their hashes to eval/HASHES.md using the commands printed after the commit. No push, further live request, held-out work or 50-episode execution is authorized.

# P07

This section reconstructs the prior P07 work from on-disk evidence. It does not claim that the pilot or full run completed.

- DEV selection: episodes 5–8 and 19–22; physical-request cap 168. Source: `outputs/runs/dev/arms/groq/p07/run_manifest.json`, `episodes` and `max_calls_per_run`. Historical manifest citations below use the preserved Groq snapshot because the current manifest also records the later Azure ping.
- Copy-only DEV migration recorded 219 files. Source: `outputs/runs/dev/migration_manifest.json`, count of `source_sha256` entries.
- Preflight passed with 39 current items, 6 references, 140 logical calls, recommended request cap 168, and 8 valid answer-key cache hits. Source: `outputs/runs/dev/arms/groq/p07/judge/p07_preflight.json`, `status` and `plan`.
- Saved offline verification: 495 tests, 0 failures and 0 errors, including 84 additions over the recorded 411-test baseline. Source: `outputs/runs/dev/arms/groq/p07/judge/p07_offline_verification.json`; corresponding cases: `outputs/runs/dev/arms/groq/p07/judge/p07_offline_tests.xml`. Later D70 tests are present in source but are not covered by that saved result.
- Groq ping succeeded and returned `qwen/qwen3.8-27b`; the Featherless ping stage failed without a physical HTTP request. Source: `outputs/runs/dev/arms/groq/p07/run_manifest.json`, `stages.ping:groq_qwen` and `stages.ping:featherless_llama`.
- The Groq DEV judge attempt failed as `BUDGET_EXCEEDED`. Its 168 HTTP requests included 83 HTTP 429s and 2 HTTP 503s; 7 answer-key cache hits made no Azure HTTP requests. Source: `outputs/runs/dev/arms/groq/p07/judge/judge_summary.json`, `error_code` and `llm`. The stage wall time was 2309.4725218999956 seconds. Source: `outputs/runs/dev/arms/groq/p07/run_manifest.json`, `stages.judge.wall_time_s`.
- First P07 DEV HTTP 429: **2026-11-08 06:48:58 UTC**, physical request 34. Source: `outputs/runs/dev/arms/groq/p07/logs/llm_calls.jsonl`, earliest Groq `http_attempt_failed` / `HTTP_429` event.
- Last successful response before the terminal error streak: **2026-11-08 06:59:37 UTC**, request 85. The streak ran from **06:59:38 to 07:21:11 UTC**, spanning **1293 seconds (21 minutes 33 seconds)**, with **81 HTTP 429s and 1 HTTP 503**. Source: `outputs/runs/dev/arms/groq/p07/logs/llm_calls.jsonl`, physical failure events after that last successful response. These are physical events; terminal summary rows are not counted again.

## Groq daily-token diagnostic

UTC date: **2026-11-08**. Sum logged input plus output usage, including rejected response usage and excluding cache hits and dry runs.

| Canonical log | Input tokens | Output tokens | Total tokens |
|---|---:|---:|---:|
| `outputs/runs/dev/arms/groq/p05/logs/llm_calls.jsonl` (P05, including ping) | 53,056 | 11,185 | 64,241 |
| `outputs/runs/dev/arms/groq/p07/logs/llm_calls.jsonl` (P07, including ping) | 107,759 | 13,310 | 121,069 |
| Sum of the two source logs | 160,815 | 24,495 | 185,310 |

P07 judging alone used 107,703 input and 13,304 output tokens; its ping added 56 input and 6 output tokens. Sources: `outputs/runs/dev/arms/groq/p07/judge/judge_summary.json`, `llm.providers.groq`; `outputs/runs/dev/arms/groq/p07/run_manifest.json`, `stages.ping:groq_qwen.llm`.

The supplied Groq limits are 30 RPM, 1K RPD, 8K TPM and 200K TPD; these are Hariom's diagnostic context, not a newly verified web result. Historical observations retained only the daily-request budget, not a daily-token balance; see `src/promo_finder/budget.py`, `observe`, and the source logs above.

**INFERENCE:** the 34 failed HTTP 400 requests in P05 may have consumed Groq tokens absent from our usage logs. The count is recorded in `outputs/runs/dev/arms/groq/p05/judge/p05_validation.json`, `http_errors.groq.HTTP_400`, and independently in `outputs/runs/dev/arms/groq/p05/logs/llm_calls.jsonl`, physical failure events. Reported usage is 14,690 below the supplied 200,000-token daily limit. Unreported error usage and the long terminal error streak make TPD exhaustion plausible, but the logs do not prove it. The Groq guard is unchanged; its token-accounting amendment is deferred to P09 by Hariom.

# P07a

Historical P07a stage status: **DEV acceptance passed; pilot dry run completed and stopped there**. The later D78 authorization and live-pilot results follow below.

D74 official cold/fidelity judge: `azure_llama`, Foundry deployment `llama70`, family meta. Hariom identifies the deployment as Llama-3.3-70B-Instruct; the returned API model string is `llama70`. Picker remains Azure mini, family openai; Groq-Qwen remains the configured free-path judge, family alibaba. The runtime family checks pass. No automatic judge switch occurred.

## Ping protocol and credential set

Source: `outputs/runs/dev/judge/p07a_live_results.json`, `ping`; immutable successful snapshot: `outputs/runs/dev/judge/p07a_live_attempts/02_resumed_ping/`. The earlier local missing-name attempt is preserved under `01_missing_credentials/` and cost USD 0 without HTTP; its stage wall time was 5.323861300013959 seconds, sourced to that snapshot's `run_manifest.json`.

| Field | Verified value |
|---|---|
| Credential set | azure_foundry |
| Variable names only | AZURE_FOUNDRY_API_KEY, AZURE_FOUNDRY_ENDPOINT |
| Endpoint form / client path | .cognitiveservices.azure.com / v1 OpenAI client |
| Output mode, fixed | json_object |
| Token-cap parameter | max_completion_tokens |
| Returned model string | llama70 |
| Ping temperature / output cap | 0.7 / 800 |
| Thinking controls | Not applicable to Llama |

Only the configured endpoint was used. Generic think-block stripping remains a parser safeguard. Protocol fallbacks, if any, are counted in the request/accounting tables; no per-call JSON-mode re-probing is permitted after settlement. The resumed ping used its accepted separate request cap of 5; DEV retained cap 168. Source: `p07a_dev_dry_run.json`, `ping` and `plan`.

## Coverage, launch batch and lanes

Source: `outputs/runs/dev/judge/p07a_live_results.json`, `coverage`, `launch_batch`, `launch_rows`, `lane_counts`; underlying ranking: `outputs/runs/dev/arms/llama_v1/ranked/promos_dev.json`.

Current items scored: **39/39**. Required acceptance: **38/39**; passed. Lane counts: **{"launch_batch": 5, "needs_human": 7, "reserve": 27}**. References are excluded from launch selection.

| Promo ID | Role | Hook family | S | H | C | A | F | P |
|---|---|---|---:|---:|---:|---:|---:|---:|
| P05-E07-001 | control | H2 | 0.796088 | 0.750000 | 0.916667 | 0.500000 | 0.938776 | 0.000000 |
| P05-E21-002 | challenger | H5 | 0.650850 | 0.916667 | 0.750000 | 0.333333 | 0.295918 | 0.000000 |
| P05-E05-001 | challenger | H3 | 0.636837 | 0.750000 | 0.666667 | 0.333333 | 0.709184 | 0.300000 |
| P05-E19-003 | challenger | H8 | 0.588265 | 0.750000 | 0.250000 | 0.500000 | 0.566327 | 0.000000 |
| P05-E22-002 | challenger | H1 | 0.548810 | 0.583333 | 0.750000 | 0.333333 | 0.285714 | 0.000000 |

Launch selection details (identifiers/counts only): `{"family_relaxed_fill": [], "promo_ids": ["P05-E07-001", "P05-E21-002", "P05-E05-001", "P05-E19-003", "P05-E22-002"], "shortfall": 0}`.

Frozen ranking sensitivity diagnostics, source `outputs/runs/dev/judge/p07a_live_results.json`, `ranking_sensitivity`: S versus equal weighting tau-b **0.737772**; S versus S_no_funnel tau-b **0.874501**, both on **39** scored current items. These did not change official S order or launch selection.

## Actual usage, errors, retries and wall time

All values in these tables are sourced to `outputs/runs/dev/judge/p07a_live_results.json`, `ping_llm`, `dev_llm`, `combined_providers` and `stage_wall_time_s`. Raw canonical metadata is `outputs/runs/dev/logs/llm_calls.jsonl`. Costs use actual reported input/output tokens at the supplied list price, not output caps. The koreacentral meter remains unconfirmed.

| Part / provider | Logical calls | HTTP requests | Cache hits | Input tokens | Output tokens | USD | Response retries | Transport retries | HTTP errors by code |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ping:azure_foundry | 1 | 1 | 0 | 74 | 6 | 0.00005680 | 0 | 0 | {} |
| answer_key:azure | 8 | 0 | 8 | 0 | 0 | 0.00000000 | 0 | 0 | {} |
| cold_judge:azure_foundry | 87 | 87 | 0 | 119132 | 12557 | 0.09349919 | 0 | 0 | {} |
| fidelity:azure_foundry | 45 | 45 | 0 | 13810 | 920 | 0.01045830 | 0 | 0 | {} |

Provider totals include resumed ping plus DEV; earlier local missing-name failure added no HTTP/token cost.

| Provider | HTTP requests | Input tokens | Output tokens | USD |
|---|---:|---:|---:|---:|
| azure_foundry | 133 | 133016 | 13483 | 0.10401429 |
| azure | 0 | 0 | 0 | 0.00000000 |

Combined resumed total: **USD 0.10401429**. Unknown-usage HTTP errors are counted separately in the accounting artifacts. Metadata-only routing records are nonbillable and do not make a configured model's price unknown. The original raw resumed-ping snapshot is preserved; corrected usage accounting is in `outputs/runs/dev/judge/p07a_ping_actual_accounting.json`.

| Stage | Actual recorded wall time, seconds |
|---|---:|
| ping:azure_llama | 3.975498 |
| judge | 747.226494 |
| rank | 0.181782 |
| Sum of recorded live/rank stages | 751.383774 |

These are measured stage durations, including stage-local preparation/waits, not elapsed offline report work. Reasoning-token fields were present in **0** DEV responses; reported reasoning-token sum is **0**. An absent field is unreported usage, not evidence of a measured zero. Rate metadata was captured on **132/132** charged DEV responses. Source: `outputs/runs/dev/judge/p07a_live_results.json`, `reasoning_usage` and `header_capture`.

## Retry shares and flip rates

Source: `outputs/runs/dev/judge/p07a_live_results.json`, `retry_diagnostics` and `reliability`; definitions are unchanged in `src/promo_finder/judging.py`. A flip is a repeated item with differing successful answers. At least two successful samples are required to measure a flip. Counts include current items and DEV references; exclusion removes final samples produced by the validation retry at temperature 0.3. Official aggregates are not altered by this descriptive exclusion.

| Question | Retried final samples / successful final samples | Retried share | With retries: flipped / measured | Flip rate | Excluding retries: flipped / measured | Flip rate |
|---|---:|---:|---:|---:|---:|---:|
| hook_now | 0/87 | 0.000000 | 3/21 | 0.142857 | 3/21 | 0.142857 |
| ends_unresolved | 0/87 | 0.000000 | 2/21 | 0.095238 | 2/21 | 0.095238 |
| standalone | 0/87 | 0.000000 | 1/21 | 0.047619 | 1/21 | 0.047619 |
| orphan_line | 0/87 | 0.000000 | 1/21 | 0.047619 | 1/21 | 0.047619 |
| spoils_ending | 0/87 | 0.000000 | 0/21 | 0.000000 | 0/21 | 0.000000 |

## Part E human agreement

Source for Azure: `outputs/runs/dev/judge/p07a_live_results.json`, `human_agreement.questions`. P05 reference source: `outputs/judge/judge_summary.json`, `human_agreement.questions`. These are descriptive comparisons, not tuning targets.

| Question | Azure-Llama agree / expected | Assessed | P05 Groq-Qwen |
|---|---:|---:|---:|
| Q1 | 5/6 | 6/6 | 6/6 |
| Q2 | 1/6 | 6/6 | 5/6 |
| Q3 | 3/6 | 6/6 | 4/6 |

## Judge-swap agreement: Groq-Qwen versus Azure-Llama

Sources: `outputs/runs/dev/judge/judge_swap_agreement.json` and `outputs/runs/dev/judge/p07a_live_results.json`, `judge_swap` and `swap_source_arm_counts`. This is a model-and-host change, not a same-model host comparison.

Matched candidates: **43**, comprising **37 current items and 6 references**. Question-arm source counts: `{"p05": 21, "p07_cache": 22}`. The full source arm per promo is recorded in `groq_source_by_item`. Question comparisons prefer valid P07 cached aggregates, then available completed P07 evidence, otherwise P05; samples from different attempts are not pooled. S comparisons use the latest complete scoring evidence for each candidate and exclude references. Missing/tied question answers are excluded from the corresponding assessed denominator.

| Question | Agree / assessed | Agreement | Assessed Groq source arms |
|---|---:|---:|---|
| hook_now | 31/42 | 0.738095 | {"p05": 20, "p07_cache": 22} |
| ends_unresolved | 38/43 | 0.883721 | {"p05": 21, "p07_cache": 22} |
| standalone | 1/43 | 0.023256 | {"p05": 21, "p07_cache": 22} |
| orphan_line | 39/43 | 0.906977 | {"p05": 21, "p07_cache": 22} |
| spoils_ending | 41/43 | 0.953488 | {"p05": 21, "p07_cache": 22} |

Azure aggregate answer distribution across **45** current/reference items: `{"ends_unresolved": {"no": 1, "yes": 44}, "hook_now": {"no": 13, "yes": 32}, "orphan_line": {"no": 43, "yes": 2}, "spoils_ending": {"no": 45}, "standalone": {"no": 45}}`. Source: `outputs/runs/dev/judge/p07a_live_results.json`, `azure_answer_distribution`. In particular, standalone=no was unanimous across all items; no prompt, threshold or judge change was made in response.

S-order **Kendall tau-b = 0.240397, n = 29 common scored current promos**. Source-arm counts for S: `{"p05": 11, "p07_cache": 18}`. Full tie and pair counts are in `kendall_S`; matched IDs are in `common_scored_current_ids`.

## Groq preservation and frozen inputs

The copy-only Groq archive verifies **332 files**: **125 P05 and 207 P07**. Source: `outputs/runs/dev/arms/groq/archive_manifest.json`. Inventory SHA-256: **`dc06cabdeceea1e3560be2d521ec3dd594d1222cba98b8cc5a48730dd6eabc90`**. Every individual hash and the file count were rechecked; no archive file was deleted.

The original Groq guard is unchanged and the TPD guard is deferred to P09. The historical TPD diagnostic remains in the P07 section above, including the explicitly labelled inference about unreported P05 HTTP 400 usage. Final code/content checks are in `outputs/runs/dev/judge/p07a_final_verification.json`.

All frozen hashes match. Source: `outputs/runs/dev/judge/p07a_live_results.json`, `frozen`, and the final verification artifact.

| File | SHA-256 |
|---|---|
| config/score_formula.yaml | `8f76ddf50855441a2b9dfc1e60b7f4f0db3cca308a8a37f22c7f25374b5638f3` |
| config/eval_order.yaml | `71d0a4042e95ec90a5ec509f28eac447721d3e951ecb0259cb376520db734ab8` |
| config/baseline.yaml | `57ccd891e430926d0b2bc2766b4488759a32f3408def2bfdab684b8e37ca7cef` |

## Pilot dry run and final STOP

Command: `run --eps 9,10,15,16,17 --run pilot --dry-run`. Every value below comes from `outputs/runs/pilot/dry_run.json`, `parts`, `providers`, `planned_calls`, `max_calls_per_run`, `judge_quota` and `estimated_judge_pacing_s`. No pilot HTTP requests were made. Estimates use candidate ceilings, full-episode cold-input upper bounds, dependency output allowances and output caps; retries are excluded from the base token/USD estimate.

| Part | Provider | Calls | Estimated input tokens | Output-token budget | Estimated USD |
|---|---|---:|---:|---:|---:|
| answer_key | azure | 5 | 105486 | 30000 | 0.08637150 |
| baseline | azure | 5 | 41251 | 30000 | 0.07031275 |
| build | code | 0 | 0 | 0 | 0.00000000 |
| characters | azure | 2 | 10940 | 12000 | 0.02673500 |
| cold_judge | azure_foundry | 30 | 89850 | 24000 | 0.08083350 |
| fidelity | azure_foundry | 20 | 15100 | 5120 | 0.01435620 |
| header | azure | 1 | 12461 | 6000 | 0.01511525 |
| moments | azure | 5 | 134772 | 30000 | 0.09369300 |
| rank | code | 0 | 0 | 0 | 0.00000000 |
| reveals | azure | 5 | 102127 | 30000 | 0.08553175 |
| snap/check | code | 0 | 0 | 0 | 0.00000000 |

| Provider | Calls | Estimated input tokens | Output-token budget | Estimated USD |
|---|---:|---:|---:|---:|
| azure | 23 | 407037 | 138000 | 0.37775925 |
| azure_foundry | 50 | 104950 | 29120 | 0.09518970 |
| code | 0 | 0 | 0 | 0.00000000 |

Pilot base schedule: **73 logical calls**, **USD 0.47294895**, with **physical-request cap 88**. Foundry judge pacing estimate: **495 seconds** at **17000 TPM and 17 RPM** (85% of the supplied deployment limits). This pacing estimate excludes provider latency, retries, header waits and upstream Azure-mini work; total wall time remains unmeasured. Source: the same dry-run artifact, `time_basis`. The D70 Groq guard-refresh ping is absent because the official judge is Foundry.

**Historical P07a STOP:** the live pilot and 50-episode estimate had not yet been authorized at that gate. D78 below records their later authorization; 50-episode execution, commit and push remain unperformed.

# D78 (b)

## Part 1: offline standalone diagnosis

Source for every count and hash comparison in this subsection: `outputs/runs/dev/judge/p07a_standalone_diagnosis.json`, `summary`, `samples`, `input_comparisons` and `owned_prompt_text`. The diagnostic made no LLM calls, blocked network connections, changed no pipeline code, and emitted no script or AI free text.

Decision: **NO_CODE_BUG_FOUND in the inspected raw/parsed and request-identity paths**. This does not establish judge quality or prove all application code correct. The raw categorical results already exhibit the standalone pattern; the parser did not invert them. D78 therefore authorizes Part 2 with the existing judge and frozen rules.

| Raw answer field | Exact raw value string | Count |
|---|---|---:|
| standalone | `no` | 86 |
| standalone | `yes` | 1 |
| ends_unresolved | `yes` | 84 |
| ends_unresolved | `no` | 3 |
| spoils_ending | `no` | 87 |

Case is preserved; the exact original JSON lexemes are `"no"` and `"yes"`, recorded separately in the JSON artifact. All 87 standalone samples match both cached parsed data and final parsed run data: **0 mismatches**. These are cold-response samples across 45 current/reference items; ping and fidelity outputs do not contain standalone.

Input identity: **110 paired cached requests** (63 P05, 47 P07), covering **81/87** Azure samples with an available Groq cache match. All **110/110 user/clip hashes match**, as do clip line counts and speaker-label presence. Speaker labels are present in **87/87** Azure cold inputs. All full cache identities and logged base-message hashes verify. Sent-system hashes match on **47/47 P07 pairs**. The **63 P05 differences** are system-only: P05 sent json_schema separately, whereas approved P07/P07a json_object inserts the same schema into the system prompt. There are **0 unexpected input differences**. Per-sample system/user hashes, line counts and label-presence booleans are in the JSON; no clip text or label names are included.

Our question lines, exactly as sent:

```text
standalone: a stranger can tell who is in conflict and what is at stake.
ends_unresolved: the clip ends before the conflict is answered.
```

For both questions, the object field and answer field have **no description key** in the sent schema; the absence is recorded explicitly, not replaced by invented description text. Their exact answer-field schema is:

```json
{"type":"string","enum":["yes","no"]}
```

Our shared evidence instruction, exactly as sent:

```text
Answer the five questions below. For each, return yes or no and one allowed line ID as evidence. Evidence must identify the line that best supports your answer.
```

Standalone evidence counts: **0 IDs: 0 samples; 1 ID: 87 samples; 2+ IDs: 0 samples**. All **87/87 cited IDs** are valid within the corresponding clip-local ID set. The JSON includes the per-sample validity counts. No code fix, prompt change or new judge call was made during Part 1.

## Part 2: completed live pilot

Command: `run --eps 9,10,15,16,17 --run pilot`. Source for every live table below: `outputs/runs/pilot/d78_pilot_results.json`, whose `sources` list points to the manifest, canonical call log, builder, judge, rank and baseline artifacts. Final status is `complete`; this is pipeline completion, not a claim that every selected item was scored.

Actual pilot: **61 logical calls**, **64/88 physical requests**, **353.795162 seconds**, **USD 0.07758629** reported-usage list-price cost. All cache-hit counts are zero. Failed HTTP usage was not reported, so its tokens/cost are unknown and excluded rather than guessed. Foundry pricing remains USD 0.71 per million input/output tokens, labelled list price (RESEARCH), koreacentral meter not confirmed. Azure-mini pricing is the configured USD 0.25 input / 2.00 output per million.

### Per-part accounting

The LLM wall column is the logged call elapsed time, including waits/retries. Stage wall times follow separately and include local stage processing. Returned-model sets contain only responses that returned a model string; failures are not assigned a fabricated returned model.

| Part / provider | Calls | HTTP requests | Errors by code | Cache hits | Returned models | Input tokens | Output tokens | USD | LLM wall s |
|---|---:|---:|---|---:|---|---:|---:|---:|---:|
| answer_key:azure | 5 | 6 | {"HTTP_429": 1} | 0 | gpt-5-mini-2025-08-07 | 17990 | 4300 | 0.01309750 | 44.010 |
| baseline:azure | 5 | 5 | {} | 0 | gpt-5-mini-2025-08-07 | 13696 | 5643 | 0.01471000 | 42.689 |
| characters:azure | 2 | 2 | {} | 0 | gpt-5-mini-2025-08-07 | 12211 | 1452 | 0.00595675 | 15.171 |
| cold_judge:azure_foundry | 26 | 26 | {"HTTP_400": 8} | 0 | llama70 | 22657 | 2608 | 0.01793815 | 164.246 |
| fidelity:azure_foundry | 12 | 12 | {} | 0 | llama70 | 3648 | 236 | 0.00275764 | 14.360 |
| header:azure | 1 | 1 | {} | 0 | gpt-5-mini-2025-08-07 | 1243 | 74 | 0.00045875 | 1.944 |
| moments:azure | 5 | 7 | {"HTTP_429": 2} | 0 | gpt-5-mini-2025-08-07 | 21730 | 4583 | 0.01459850 | 44.200 |
| reveals:azure | 5 | 5 | {} | 0 | gpt-5-mini-2025-08-07 | 14388 | 2236 | 0.00806900 | 24.293 |

Metadata-only routing rows have zero calls/requests/tokens/USD and are omitted from the table.

| Provider | Calls | HTTP requests | Input tokens | Output tokens | USD |
|---|---:|---:|---:|---:|---:|
| azure | 23 | 26 | 81258 | 18288 | 0.05689050 |
| azure_foundry | 38 | 38 | 26305 | 2844 | 0.02069579 |

| Stage | Actual wall s |
|---|---:|
| understand | 41.578919 |
| find | 44.396108 |
| build | 0.779512 |
| judge | 222.988967 |
| rank | 0.121560 |
| baseline | 42.763948 |
| snap/check | 0.105531 |

Build, rank and snap/check are code-only stages with zero LLM calls, HTTP requests, tokens and USD. No five-consecutive-429 stop occurred: the three 429s were separate recovered calls (moments E16/E17 and answer key E09). Foundry had eight cold HTTP 400 failures, zero transport retries for those failures, and no retained provider-specific code. Their cause is unverified; no additional probe, endpoint change or code fix was attempted.

### Candidates and judge coverage

| Episode | Candidates kept | Selected for judge | Scored |
|---|---:|---:|---:|
| E09 | 2 | 2 | 2 |
| E10 | 8 | 4 | 4 |
| E15 | 4 | 4 | 2 |
| E16 | 2 | 2 | 0 |
| E17 | 4 | 4 | 4 |

Total retained: **20**. The frozen top-four-per-episode selection judged **16**; **12/16 selected (75%)** and **12/20 retained (60%)** were scored. Four selected items lack cold evidence after HTTP 400 failures; the other four unscored retained candidates were outside the selection cap. The DEV-only 38/39 gate had already passed and is not misapplied to this pilot pool. Failed samples were excluded and missing evidence was not invented.

### Pilot Azure-Llama answer distributions

Counts below distinguish successful cold samples from item aggregates. There are **18 successful samples**, **16 selected items**, and **4 unmeasured item aggregates**.

| Question | Successful-sample values | Item-aggregate values |
|---|---|---|
| hook_now | {"no": 5, "yes": 13} | {"no": 3, "unmeasured": 4, "yes": 9} |
| ends_unresolved | {"no": 1, "yes": 17} | {"no": 1, "unmeasured": 4, "yes": 11} |
| standalone | {"no": 18} | {"no": 12, "unmeasured": 4} |
| orphan_line | {"no": 17, "yes": 1} | {"no": 11, "unmeasured": 4, "yes": 1} |
| spoils_ending | {"no": 18} | {"no": 12, "unmeasured": 4} |

Standalone remained no for all **18/18 successful pilot samples** and all **12/12 measured item aggregates**; four failed items are unmeasured, not no. No schema/response validation retries occurred.

### Frozen baseline results

Baseline kept **14**, dropped **0**, and recorded **1 invented timestamp boundary** before snapping. Drops by reason: `{}`. The unchanged code counts a proposed segment start/end below zero or after episode duration as invented; it does not count every non-boundary floating timestamp as invented. Sensitivity kept **14**, sensitivity drops by reason: `{}`. Failed baseline episodes: **0**. Source: `outputs/runs/pilot/d78_pilot_results.json`, `baseline`; implementation definition: `src/promo_finder/baseline.py`, `snap_promos`.

| Episode | Kept | Dropped | Invented boundaries |
|---|---:|---:|---:|
| E09 | 3 | 0 | 0 |
| E10 | 3 | 0 | 0 |
| E15 | 3 | 0 | 0 |
| E16 | 3 | 0 | 1 |
| E17 | 2 | 0 | 0 |

## 50-episode estimate only

Command: `tools/p07_offline.py estimate-50 --run pilot`. Sources: `outputs/runs/pilot/arms/llama_v1/estimate_50.json` and `outputs/runs/pilot/d78_estimate_summary.json`. The estimate reads completed pilot metadata only. No full-run episode content or held-out content was read, and no 50-episode execution occurred. Cold and fidelity estimate parts use **azure_llama / llama70**.

| Part / provider | Model key | Calls | HTTP requests | Input tokens | Output tokens | USD | Scaled request wall s |
|---|---|---:|---:|---:|---:|---:|---:|
| answer_key:azure | azure_mini | 45 | 54 | 161910 | 38700 | 0.11787750 | 396.090 |
| baseline:azure | azure_mini | 50 | 50 | 136960 | 56430 | 0.14710000 | 426.890 |
| characters:azure | azure_mini | 13 | 13 | 122110 | 9438 | 0.04940350 | 98.611 |
| cold_judge:azure_foundry | azure_llama | 234 | 234 | 203913 | 23472 | 0.16144335 | 1478.214 |
| fidelity:azure_foundry | azure_llama | 108 | 108 | 32832 | 2124 | 0.02481876 | 129.240 |
| header:azure | azure_mini | 1 | 1 | 12430 | 74 | 0.00325550 | 1.944 |
| moments:azure | azure_mini | 50 | 70 | 217300 | 45830 | 0.14598500 | 442.000 |
| reveals:azure | azure_mini | 50 | 50 | 143880 | 22360 | 0.08069000 | 242.930 |

| Provider | Calls | HTTP requests | Input tokens | Output tokens | USD |
|---|---:|---:|---:|---:|---:|
| azure | 209 | 238 | 794590 | 172832 | 0.54431150 |
| azure_foundry | 342 | 342 | 236745 | 25596 | 0.18626211 |

Observed-pattern projection: **551 logical calls**, **580 HTTP requests**, **1031335 input + 198428 output tokens**, **USD 0.73057361**, and **3215.919 seconds (53.60 minutes)** of scaled measured request time. This excludes code/manifest overhead and unreported failed-request usage. Foundry's scaled measured share is **1607.454 seconds**; its aggregate quota-throughput estimate is **1207.059 seconds** at the configured 85% per-minute limits. Source: the two estimate artifacts above.

This projection assumes the pilot's failure pattern continues, **not full-coverage scoring**: failed cold requests skipped fidelity, reducing observed call counts and cost. It also inherits a small five-episode sample, variable content density, retries and unconfirmed regional list-price metering. As a separate metadata-only planning ceiling, the frozen full-run selection/chunk/cutoff rules permit **659 logical calls** (209 Azure-mini + 450 Azure-Llama), or a hypothetical **791 request cap** with the same 20% reserve. Source: `d78_estimate_summary.json`, `complete_coverage_call_ceiling`; it is a derived ceiling, not a run authorization or cost guarantee.

## D78 final STOP

Both requested parts and the estimate are complete. No pipeline code was changed or fixed. Frozen files, judge prompts and Groq guard remain unchanged; the Groq archive was re-verified. Final proof is `outputs/runs/pilot/d78_final_verification.json`. No further live calls, 50-episode run, held-out work, commit or push were performed.

# D79 + D80

## D79: provider error metadata and eight-request replay

Sources: `outputs/runs/pilot/d79_replay_plan.json`, `d79_replay_results.json` and `logs/d79_replay_calls.jsonl`. Only HTTP status, error.code, innererror.code and whitelisted filter flags/severity are captured. Message text and arbitrary body fields are excluded. Eight targets were sent once each, within cap 10, with unchanged endpoint/filter settings. Original/current serializer JSON bodies match and each live body matched its recorded reconstruction hash. Original wire packets were not retained.

| Original sample | HTTP status | error.code | innererror.code | Category flags | Body hash matched |
|---|---:|---|---|---|---|
| p05.cold_judge.P05-E15-001.run1 | 400 | None | None | {} | True |
| p05.cold_judge.P05-E15-001.run2 | 400 | None | None | {} | True |
| p05.cold_judge.P05-E15-001.run3 | 400 | None | None | {} | True |
| p05.cold_judge.P05-E15-003.run1 | 400 | None | None | {} | True |
| p05.cold_judge.P05-E16-001.run1 | 400 | None | None | {} | True |
| p05.cold_judge.P05-E16-001.run2 | 400 | None | None | {} | True |
| p05.cold_judge.P05-E16-001.run3 | 400 | None | None | {} | True |
| p05.cold_judge.P05-E16-002.run1 | 400 | None | None | {} | True |

D79 wall time: **24.957176 seconds**. All eight HTTP 400 responses lacked the requested whitelisted code/flag values in the captured metadata; the cause is unconfirmed. No further resend was performed. Failed-request tokens and USD were unreported, not assumed zero.

## D80: single-line trial and pre-declared decision

Sources: `outputs/runs/dev/judge/d80_preflight.json`, `d80_results.json`, `d80_tests.xml`, and the `arms/llama_v1/archive_manifest.json` files under DEV and pilot. DEV v1 preserved **469 files**, inventory SHA-256 `f22e016956ae4f5f76236d1d67762fa0d3e7a24597839adeccc5f1280debf813`; pilot v1 preserved **121 files**, SHA-256 `1a516dc7e83af34c7cef5318269ee54a1fe88576bc320c85862a322b9cb385b1`. All counts and individual hashes verify.

Only this owned question line changed:

```text
standalone: someone who has never seen this show can follow the basic situation from this clip alone — who is in conflict and roughly what is at stake. Backstory and names are not required; answer "no" only if the clip is confusing without earlier episodes.
```

The preflight AST comparison and tests verify unchanged other prompt content, clip message, schema, temperatures, formula and frozen configuration.

Decision: **ADOPT**. Standalone item aggregates across exactly **45** current/reference items: **33 yes, 12 no, 0 unmeasured**. Minority = **12**, required minimum = **5**. Missing answers do not count as either binary answer. The declared threshold was not altered. The new line remains active.

| Question | Yes | No | Unmeasured |
|---|---:|---:|---:|
| hook_now | 25 | 20 | 0 |
| ends_unresolved | 43 | 2 | 0 |
| standalone | 33 | 12 | 0 |
| orphan_line | 1 | 44 | 0 |
| spoils_ending | 0 | 45 | 0 |

| Part E | D80 agree / expected | Assessed | llama_v1 | P05 |
|---|---:|---:|---:|---:|
| Q1 | 6/6 | 6/6 | 5/6 | 6/6 |
| Q2 | 3/6 | 6/6 | 1/6 | 5/6 |
| Q3 | 3/6 | 6/6 | 3/6 | 4/6 |

Trial coverage: **39/39 current items**. Lanes: `{"launch_batch": 5, "needs_human": 10, "reserve": 24}`. S-order Kendall tau-b versus llama_v1 = **0.573559**, **n=39** common scored current items. Tie/pair counts and IDs are in `d80_results.json`.

| Promo ID | Role | Hook | S | H | C | A | F | P |
|---|---|---|---:|---:|---:|---:|---:|---:|
| P05-E07-001 | control | H2 | 0.804422 | 0.666667 | 0.750000 | 0.833333 | 0.938776 | 0.000000 |
| P05-E22-001 | challenger | H3 | 0.715476 | 0.750000 | 0.750000 | 0.916667 | 0.285714 | 0.000000 |
| P05-E21-002 | challenger | H5 | 0.709184 | 0.833333 | 0.750000 | 0.750000 | 0.295918 | 0.000000 |
| P05-E19-002 | challenger | H8 | 0.679932 | 0.666667 | 0.583333 | 1.000000 | 0.566327 | 0.500000 |
| P05-E06-002 | challenger | H4 | 0.548129 | 0.250000 | 0.333333 | 0.833333 | 0.698980 | 0.000000 |

Launch selection: `{"family_relaxed_fill": [], "promo_ids": ["P05-E07-001", "P05-E22-001", "P05-E21-002", "P05-E19-002", "P05-E06-002"], "shortfall": 0}`. Trial DEV reported-usage cost: **USD 0.10553014**. Wall times: `{"judge": 757.2604223999952, "rank": 0.5098790999909397}` seconds. Source: `d80_results.json`.

| DEV part | Calls | HTTP requests | Cache hits | Input tokens | Output tokens | USD | Errors |
|---|---:|---:|---:|---:|---:|---:|---|
| answer_key:azure | 8 | 0 | 8 | 0 | 0 | 0.00000000 | {} |
| cold_judge:azure_foundry | 87 | 87 | 0 | 122264 | 12621 | 0.09576835 | {} |
| fidelity:azure_foundry | 45 | 42 | 3 | 12901 | 848 | 0.00976179 | {} |

## Adopted pilot judge/rank-only rerun

Source: `outputs/runs/pilot/d80_judge_only.json` and the preserved pilot judge/rank artifacts under `outputs/runs/pilot/arms/llama_d80/`. A task-local wrapper executed `run --eps 9,10,15,16,17 --run pilot` as judge/rank only; the ordinary completed-run guard remains unchanged. It hard-refused picker cache misses and upstream LLM purposes. It verified all understanding, moments, promos and baseline file hashes unchanged. Five answer-key reads were cache hits; **zero Azure-mini HTTP requests**. No understand/find/build/baseline stage was rerun.

Coverage: **12/16 selected**, **12/20 retained**. Incremental rerun wall time: **205.498743 seconds**; request cap **88**.

| Part | Calls | HTTP requests | Cache hits | Input tokens | Output tokens | USD | HTTP codes |
|---|---:|---:|---:|---:|---:|---:|---|
| answer_key:azure | 5 | 0 | 5 | 0 | 0 | 0.00000000 | {} |
| cold_judge:azure_foundry | 26 | 26 | 0 | 23305 | 2633 | 0.01841598 | {"HTTP_400": 8} |
| fidelity:azure_foundry | 12 | 10 | 2 | 3052 | 198 | 0.00230750 | {} |

Returned Foundry model strings: `["llama70"]`. All eight failures are HTTP 400 on the same sample identifiers as the D79 table above. Every captured `error.code` and `innererror.code` is null; category flags are empty objects. Per-request metadata is in `d80_judge_only.json`, `http_error_metadata`. No cause is inferred from these absent fields. Failed-request usage remains unreported.

Pilot item answer distributions (16 selected, including 4 unmeasured): `{"ends_unresolved": {"no": 2, "unmeasured": 4, "yes": 10}, "hook_now": {"no": 4, "unmeasured": 4, "yes": 8}, "orphan_line": {"no": 12, "unmeasured": 4}, "spoils_ending": {"no": 12, "unmeasured": 4}, "standalone": {"no": 4, "unmeasured": 4, "yes": 8}}`. Pilot lanes: `{"launch_batch": 4, "needs_human": 8, "reserve": 8}`; launch selection: `{"family_relaxed_fill": ["P05-E17-002"], "promo_ids": ["P05-E15-002", "P05-E09-002", "P05-E10-001", "P05-E17-002"], "shortfall": 1}`. These results do not authorize another live run.

Updated 50-episode estimate: **551 logical calls**, **562 HTTP requests**, **USD 0.73082282**, **3454.060 seconds** scaled request time. Sources: `outputs/runs/pilot/estimate_50.json` and `d80_estimate_summary.json`. Its upstream-generation costs are reused once from v1 (including original paid key generation), while only cold/fidelity are replaced by the D80 arm. The incremental rerun table above is separate and contains the actual warm-cache cost. Failed-request usage and cache-dependent billing remain limitations. No full-run content was read.

Unchanged full-coverage call ceiling from frozen selection/chunk/cutoff rules: **659 logical calls**, hypothetical reserve cap **791** (209 picker + 450 judge calls). This is a planning ceiling, not authorization to run.

| Estimate provider | Logical calls | HTTP requests | Input tokens | Output tokens | USD | Scaled request seconds |
|---|---:|---:|---:|---:|---:|---:|
| azure | 209 | 238 | 794590 | 172832 | 0.54431150 | 1608.466 |
| azure_foundry | 342 | 324 | 237213 | 25479 | 0.18651132 | 1845.594 |

The observed-pattern estimate includes only 12/16 scored pilot selections, skipped fidelity after failed cold calls, and two fidelity cache hits. It is not a full-coverage cost ceiling. A hard token/USD/wall-time ceiling is unknown without all input lengths and future error usage; none is guessed. The 659-call ceiling assumes every configured slot is filled, before retries; 791 is a hypothetical request cap with the same 20% reserve.

## Final STOP

Frozen hashes and copied arms were re-verified; final evidence: `outputs/runs/dev/judge/d80_final_verification.json`. No further live calls, filters/endpoints changed, held-out work, 50-episode execution, commit or push.

# D81: ten-minute diagnosis

## Error-response structures

Historical D79/D80 raw bodies were not saved. Hariom separately authorized eight fresh diagnostic resends, cap 8, each latest-D80 failed request once with identical reconstructed request bytes. Sources: `outputs/runs/pilot/d81_response_structures.json` and `logs/d81_diagnostic_calls.jsonl`. All eight returned HTTP 400 and share exactly the JSON paths/types below; the JSON artifact also repeats the full structure per request. Raw bodies were never saved or printed.

| Request | HTTP status | Response bytes | Nested error.code | Message guard | Message length | Request byte hash verified |
|---|---:|---:|---|---|---:|---|
| p05.cold_judge.P05-E15-001.run1 | 400 | 425 | content_filter | clean | 64 | True |
| p05.cold_judge.P05-E15-001.run2 | 400 | 425 | content_filter | clean | 64 | True |
| p05.cold_judge.P05-E15-001.run3 | 400 | 425 | content_filter | clean | 64 | True |
| p05.cold_judge.P05-E15-003.run1 | 400 | 425 | content_filter | clean | 64 | True |
| p05.cold_judge.P05-E16-001.run1 | 400 | 425 | content_filter | clean | 64 | True |
| p05.cold_judge.P05-E16-001.run2 | 400 | 425 | content_filter | clean | 64 | True |
| p05.cold_judge.P05-E16-001.run3 | 400 | 425 | content_filter | clean | 64 | True |
| p05.cold_judge.P05-E16-002.run1 | 400 | 425 | content_filter | clean | 64 | True |

| JSON key path | Value type | Allowed exact value / guarded message |
|---|---|---|
| `$` | object |  |
| `$["id"]` | string |  |
| `$["model"]` | string |  |
| `$["choices"]` | array |  |
| `$["choices"][0]` | object |  |
| `$["choices"][0]["index"]` | integer |  |
| `$["choices"][0]["message"]` | object |  |
| `$["choices"][0]["message"]["role"]` | string |  |
| `$["choices"][0]["message"]["content"]` | string |  |
| `$["choices"][0]["finish_reason"]` | string |  |
| `$["choices"][0]["content_filter_results"]` | object |  |
| `$["choices"][0]["content_filter_results"]["error"]` | object |  |
| `$["choices"][0]["content_filter_results"]["error"]["code"]` | string | "content_filter" |
| `$["choices"][0]["content_filter_results"]["error"]["message"]` | string | Response content blocked by label 'MultiSeverity_ViolenceScore'. |
| `$["usage"]` | object |  |
| `$["usage"]["prompt_tokens"]` | integer |  |
| `$["usage"]["total_tokens"]` | integer |  |
| `$["created"]` | integer |  |
| `$["object"]` | string |  |
| `$["prompt_filter_results"]` | null |  |

Only one key named code/type/status/param exists in each body: the nested `code`, exactly `"content_filter"`. No `type`, `status` or `param` keys are present. HTTP status **400** comes from the response status, outside the JSON body. The only message/detail string per body is the nested error message shown above; all **8** passed `tools/guard.py`'s **8-word** check, **0** were withheld. Other scalar values, including message.content, were not retained. Diagnostic wall time: **65.676408 seconds**. Response usage keys exist, but their values were outside this diagnostic whitelist; reported D81 USD remains unknown.

## Offline request comparison

Source: `outputs/runs/pilot/d81_diagnosis.json`, `per_item` and `per_request`. These are the latest D80 requests: **4 failing items / 8 requests**, **12 successful items / 18 requests**. All 26 reconstructed prompts and cache identities match their canonical logged hashes. Bytes are the JSON request body serialized by the same installed SDK through a fake transport; original wire packets were not retained. The eight live diagnostic hashes also match these reconstructions.

Serialized chars counts Unicode code points in the full JSON request; message chars counts the decoded system+user contents, including the inline schema; clip chars counts the decoded user/clip portion. The one non-ASCII character in every complete D80 request is the approved standalone question punctuation. All clips contain zero non-ASCII characters. Control counts below exclude LF and tab. Repeated samples have identical count/size metrics, so each item needs one row.

| Item | Outcome | Requests | Body bytes | Serialized chars | Message chars | Clip chars | Non-ASCII (body/messages/clip) | Prohibited controls | Lone surrogates | Invalid UTF-8 |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| P05-E09-001 | successful | 3 | 5256 | 5254 | 4625 | 1386 | 1/1/0 | 0 | 0 | 0 |
| P05-E09-002 | successful | 1 | 5682 | 5680 | 5016 | 1687 | 1/1/0 | 0 | 0 | 0 |
| P05-E10-001 | successful | 3 | 5404 | 5402 | 4753 | 1454 | 1/1/0 | 0 | 0 | 0 |
| P05-E10-002 | successful | 1 | 7341 | 7339 | 6524 | 2805 | 1/1/0 | 0 | 0 | 0 |
| P05-E10-003 | successful | 1 | 5203 | 5201 | 4561 | 1292 | 1/1/0 | 0 | 0 | 0 |
| P05-E10-004 | successful | 1 | 5375 | 5373 | 4737 | 1468 | 1/1/0 | 0 | 0 | 0 |
| P05-E15-001 | failed | 3 | 5943 | 5941 | 5253 | 1864 | 1/1/0 | 0 | 0 | 0 |
| P05-E15-002 | successful | 1 | 5998 | 5996 | 5325 | 1966 | 1/1/0 | 0 | 0 | 0 |
| P05-E15-003 | failed | 1 | 8713 | 8711 | 7811 | 3882 | 1/1/0 | 0 | 0 | 0 |
| P05-E15-004 | successful | 1 | 4623 | 4621 | 4055 | 966 | 1/1/0 | 0 | 0 | 0 |
| P05-E16-001 | failed | 3 | 5643 | 5641 | 4979 | 1650 | 1/1/0 | 0 | 0 | 0 |
| P05-E16-002 | failed | 1 | 5867 | 5865 | 5179 | 1790 | 1/1/0 | 0 | 0 | 0 |
| P05-E17-001 | successful | 3 | 5307 | 5305 | 4665 | 1396 | 1/1/0 | 0 | 0 | 0 |
| P05-E17-002 | successful | 1 | 5180 | 5178 | 4549 | 1310 | 1/1/0 | 0 | 0 | 0 |
| P05-E17-003 | successful | 1 | 5308 | 5306 | 4679 | 1440 | 1/1/0 | 0 | 0 | 0 |
| P05-E17-004 | successful | 1 | 5181 | 5179 | 4563 | 1354 | 1/1/0 | 0 | 0 | 0 |

Failing body-size range: **5643–8713 bytes**; successful range: **4623–7341 bytes**. No Unicode general category is exclusive to either group, for serialized JSON, decoded messages or clip text. Category counts per item are in the JSON artifact. Unicode category `Cc` there includes permitted line feeds; the prohibited-control metric excludes LF/tab and is zero throughout. Strict UTF-8 decode and encode passed on all reconstructed requests. This does not identify a character-encoding or universal size-threshold explanation for all failures.

## Conclusion and smallest proposed fix

**CAUSE FOUND: provider-reported response content filtering**, with nested code `content_filter` and the guard-clean `MultiSeverity_ViolenceScore` message in every diagnostic response. This is direct response evidence. It does not identify the triggering input or generated words, which were not inspected.

The current extractor inspects root/error/innererror containers but does not descend into `choices[*].content_filter_results.error`. That explains the earlier null metadata even when the fresh response contains a code. Smallest proposed code amendment: whitelist that exact nested code path and classify the failure explicitly as `CONTENT_FILTERED`, preserving unscored status. This improves observability; it does not unblock filtering or restore coverage. A coverage remedy would need a separate approved decision. **No fix was applied.**

STOP. No filters, endpoints, judge, prompts, schema, temperatures or scores changed. No further requests, 50-episode execution, held-out work, commit or push.

# D82: filter classification and approved pilot rerun

## Code and offline validation

Sources: `src/promo_finder/provider_protocol.py`, `llm.py`, `judging.py`, `tests/test_p07c.py`, and `outputs/runs/pilot/d82_final_tests.xml`. The metadata reader now inspects `choices[*].content_filter_results.error.code` and `prompt_filter_results` as well as the prior root/innererror paths. Only fixed known filter-label names are extracted from error messages; no message text is retained. Existing whitelist category flags remain metadata.

Explicit filtered failures raise `CONTENT_FILTERED` before protocol/transport/validation retries. The physical log retains HTTP status plus classification; judge run failures retain only metadata and stay unscored. Explicit nested blocking in an HTTP 200 response is handled before JSON parsing and caching. Safe, unblocked categories are not treated as blocking. Tests verify a filtered non-429 resets the consecutive-429 streak.

Final suite: **598 passed**, **0 failures**, **0 errors**, **0 skipped**; 15 additions over the saved 583-test suite. No real provider was used in tests. The final JUnit is `outputs/runs/pilot/d82_final_tests.xml`; earlier passing invocation: `d82_tests.xml`.

Before replacing current pilot outputs, the D80 arm was copied (never moved/deleted) into `outputs/runs/pilot/arms/llama_d80/`: **156 files**, all SHA-256 values verified, inventory SHA-256 **`6b4ba61866f2fc9a478aebfc003eb1130be19a4d445604f61a9e66923a690440`**. Its archive manifest records individual source hashes. Existing llama_v1/Groq arms remain intact.

## Pilot rerun and remaining filters

Command arguments: `run --eps 9,10,15,16,17 --run pilot`, executed through the same judge/rank-only wrapper as D80, with D82 artifact names. Source: `outputs/runs/pilot/d82_judge_only.json`, `d82_rerun_context.json`, `judge/judge_E*.json`, `ranked/promos_dev.json`, and canonical call-log metadata after that context offset. Upstream file hashes were verified unchanged and answer-key cache misses would have been refused before network use.

Hariom reports that llama70 output violence now blocks High only. This is user-supplied deployment context; application code did not inspect the portal policy, alter filters, switch endpoints/keys or switch judges. The observed failures below do not prove which policy setting was applied server-side.

Coverage: **12/16 selected (75%)**, **12/20 retained (60%)**. All **7** HTTP 400 failures were classified **CONTENT_FILTERED**; **0** transport or validation retries occurred. The frozen repeated-item schedule contains independent question shuffles; these are separate planned samples, not retries. No additional resend followed this phase.

| Episode | Selected | Scored |
|---|---:|---:|
| E09 | 2 | 2 |
| E10 | 4 | 4 |
| E15 | 4 | 2 |
| E16 | 2 | 0 |
| E17 | 4 | 4 |

| Filtered sample | HTTP status | Classification | Nested code | Label names only |
|---|---:|---|---|---|
| p05.cold_judge.P05-E15-001.run1 | 400 | CONTENT_FILTERED | content_filter | ["MultiSeverity_ViolenceScore"] |
| p05.cold_judge.P05-E15-001.run2 | 400 | CONTENT_FILTERED | content_filter | ["MultiSeverity_ViolenceScore"] |
| p05.cold_judge.P05-E15-001.run3 | 400 | CONTENT_FILTERED | content_filter | ["MultiSeverity_ViolenceScore"] |
| p05.cold_judge.P05-E15-003.run1 | 400 | CONTENT_FILTERED | content_filter | ["MultiSeverity_ViolenceScore"] |
| p05.cold_judge.P05-E16-001.run1 | 400 | CONTENT_FILTERED | content_filter | ["MultiSeverity_ViolenceScore"] |
| p05.cold_judge.P05-E16-001.run2 | 400 | CONTENT_FILTERED | content_filter | ["MultiSeverity_ViolenceScore"] |
| p05.cold_judge.P05-E16-002.run1 | 400 | CONTENT_FILTERED | content_filter | ["MultiSeverity_ViolenceScore"] |

The affected items are **P05-E15-001, P05-E15-003, P05-E16-001 and P05-E16-002**, all unscored. P05-E16-001 has one successful third planned sample; because its first sample failed, the existing fidelity dependency skips fidelity. This explains **13 measured cold aggregates** but only **12 scored items**. No rule was changed to fill that gap.

Measured sample count: **19** (18 cached and one new); item denominator: **16**, with **3** wholly unmeasured cold aggregates.

| Question | Successful cold samples | Item aggregates |
|---|---|---|
| hook_now | `{"no": 7, "yes": 12}` | `{"no": 4, "unmeasured": 3, "yes": 9}` |
| ends_unresolved | `{"no": 2, "yes": 17}` | `{"no": 2, "unmeasured": 3, "yes": 11}` |
| standalone | `{"no": 7, "yes": 12}` | `{"no": 4, "unmeasured": 3, "yes": 9}` |
| orphan_line | `{"no": 19}` | `{"no": 13, "unmeasured": 3}` |
| spoils_ending | `{"no": 19}` | `{"no": 13, "unmeasured": 3}` |

Lanes: `{"launch_batch": 4, "needs_human": 8, "reserve": 8}`. Launch selection: `{"family_relaxed_fill": ["P05-E17-002"], "promo_ids": ["P05-E15-002", "P05-E09-002", "P05-E10-001", "P05-E17-002"], "shortfall": 1}`.

| Launch promo | Role | Hook | S |
|---|---|---|---:|
| P05-E15-002 | control | H1 | 0.774762 |
| P05-E09-002 | challenger | H3 | 0.708673 |
| P05-E10-001 | challenger | H5 | 0.701633 |
| P05-E17-002 | challenger | H5 | 0.459014 |

## Incremental accounting

All values: `outputs/runs/pilot/d82_judge_only.json`, `llm` and wall-time fields. This is the warm-cache rerun alone, not repeated upstream-generation cost. Costs use reported tokens and the supplied USD 0.71 per million input/output list price (RESEARCH), koreacentral meter not confirmed; failed-request usage remains unreported.

| Part | Calls | HTTP | Cache hits | Input tokens | Output tokens | USD | HTTP errors |
|---|---:|---:|---:|---:|---:|---:|---|
| answer_key:azure | 5 | 0 | 5 | 0 | 0 | 0.00000000 | {} |
| cold_judge:azure_foundry | 26 | 8 | 18 | 1358 | 178 | 0.00109056 | {"HTTP_400": 7} |
| fidelity:azure_foundry | 12 | 0 | 12 | 0 | 0 | 0.00000000 | {} |

Total reported-usage cost: **USD 0.00109056**. Judge wall time: **65.001232 s**; rank: **0.107043 s**; combined wrapper wall: **65.113116 s**. Returned model: `llama70`; output mode and token parameter remained `json_object` / `max_completion_tokens`. No new 50-episode estimate or execution was requested in D82; the earlier estimate remains historical.

## Commit gate and STOP

The requested gate was executed: `git add -A`, remove the two frozen untracked configuration files from the index, `git status`, `git diff --stat --cached`, then `.venv/Scripts/python.exe -B tools/guard.py`. Source: `outputs/runs/pilot/d82_commit_gate.json` (exact status, diff stat, staged path inventory and guard output). **43 files** are staged from the accumulated P07 worktree, including D82.

Confirmed: **no outputs/, data/, .cache/, .venv/, .env, .xlsx, gold, frozen file or HASHES.md is staged**. `config/baseline.yaml` and `config/eval_order.yaml` remain untracked and unstaged, with approved hashes unchanged. Those files are referenced by the code; a commit of the current index alone would omit them. This follows the explicit staging restriction and remains a review item before commit approval.

Guard: `guard: clean (43 files checked, mode=staged)`. Cached diff whitespace check passed. No staging guard text hits or blocked paths. The report and new test file are included in the staged set.

Historical gate proof: `outputs/runs/pilot/d82_final_verification.json`. This gate stopped for approval; Hariom's later correction and approval follow below. No push, held-out work, extra live request, application filter/endpoint change or 50-episode execution occurred.

## D82 b: accepted outcome and corrected commit approval

**D82 outcome = guardrail change did not recover the 7 filtered requests; accepted as CONTENT_FILTERED (D82 b).** This is Hariom's accepted disposition, not a claim of recovered coverage. The seven failed samples remain unscored and are not retried.

Hariom corrected the earlier staging restriction: frozen files must not be modified, but the existing `config/eval_order.yaml` and `config/baseline.yaml` must be added to the approved commit. Before staging, their SHA-256 values matched:

| Frozen config | Approved SHA-256 |
|---|---|
| config/eval_order.yaml | `71d0a4042e95ec90a5ec509f28eac447721d3e951ecb0259cb376520db734ab8` |
| config/baseline.yaml | `57ccd891e430926d0b2bc2766b4488759a32f3408def2bfdab684b8e37ca7cef` |

The final gate verified that both worktree bytes and staged blobs have the approved hashes, showed `git status` and `git diff --stat --cached`, and passed the guard: `guard: clean (45 files checked, mode=staged)`. Scope: **45 files**, including the two unchanged frozen configs and this pre-commit report edit. No outputs/, data/, .cache/, .venv/, .env, .xlsx, gold, eval documents or HASHES.md is staged. Evidence: `outputs/runs/pilot/d82_approved_commit_gate.json`, saved before the commit.

Approved commit message:

```text
P07+P07a: judge fix, run folders, one-command pipeline, baseline, pilot; Azure Llama judge (D74), standalone wording (D80), content-filter classification (D82); frozen eval_order + baseline configs
```

This report edit is included before the authorized commit. After committing, read `tools/hash_eval.py` and print, without running, the exact PowerShell commands for Hariom to append and verify both config hashes. Agents do not edit eval/HASHES.md. Never push.
