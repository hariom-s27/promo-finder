PLAIN SUMMARY
- What happened: Completed the single approved DEV find run and the code-only DEV build. Reveals v2 passed acceptance with 13 combined E05/E19 marks against the minimum 3. The builder generated 176 pairs and kept 9 promos. The explicit held-out refusal fix is implemented and tested. All 321 tests pass: 217 existing plus 104 new.
- What it means: Every kept promo passed a fresh timestamp-checker verification, including exported times, line membership and duration. Kept durations are 20 / 25 / 43.5 seconds (min/median/max); 4 of 9 are montages. Configured reveal block keeps 9; the flag counterfactual keeps 34 after dedupe and cap. P03 is ready for the commit approval gate.
- Problems: Four moment HTTP 429s occurred and all recovered within the wrapper; there were no terminal failures. V2 produced more E05/E19 marks than Hariom's hand count; passing the count gate does not establish marking accuracy. Four DEV episodes have no surviving promos under the required gates. The initial offline cache-order failure was fixed and the final suite passes.
- Decision needed (options + your pick): Approve the prepared commit, or request changes before committing. Pick: commit this P03 implementation with the configured block mode and documented limitations. Commit remains pending explicit approval; no push.
- Exact next message for Hariom to send to the chat: APPROVED

SELF-AUDIT
1. Steps done: Step 0 done: clean starting tree, HEAD 8d8303be447a7269e10382fa9b20d4c7eee082e8, required source inspection and 217 passing baseline tests. A done: archive and v2 files in outputs/understanding; counts and acceptance in outputs/moments/find_summary.json. B done: config.py/llm.py plus fake clock/provider tests; live retry evidence in outputs/logs/llm_calls.jsonl. C done: all requested outputs/moments/moments_E##.json files, counts below. D done: dry-run approval followed by one live DEV invocation. E done: all requested candidates files, build_summary.json and ignored dev_review.md. F done: find/build and exact HELD_OUT_REFUSED probes. G tests/report done; staging/guard evidence recorded at the end; commit not done, pending user approval.
2. Decisions I made that the prompt did not specify: Cleaned reveal records restore schema-field order so cached and fresh predecessor results produce identical moment prompts. Equal-strength moment duplicates retain first occurrence; equal-score builder ties prefer continuous, then earlier hook/cliff and endpoints. Low recall is assessed before episode-end fallback, as approved in the plan. Fallback recap uses the half-open interval from zero to recap_fallback_s; its exact endpoint is excluded and tested. Primary drop reasons use the approved deterministic precedence. No model or gate threshold was changed autonomously.
3. Deviations from the prompt: None in the approved scope. The user amendments replace first-scene recap and unbounded Retry-After behavior. The requested final refusal fix adds the explicit HELD_OUT_REFUSED code and message without changing P02 understand. The already-approved live command was started before that independent CLI-only fix; its AI prompts, parameters and schema were unchanged. No additional live find invocation occurred.
4. Numbers: Thresholds/rates come from config.yaml. Dry-run numbers: .cache/tmp/p03_gate_1b022a0fc4214c92aa9b263b554dfcdc/dry_run.json. Live calls/tokens/models/costs, per-episode marks/moments: outputs/moments/find_summary.json. Request/retry records: outputs/logs/llm_calls.jsonl. P02 counts: outputs/understanding/archive_p02/reveals_E*.json. Kept/drop/reveal-mode/duration/montage/recap counts: outputs/promos/build_summary.json and candidates_E*.json. Independent verification and new refusal outputs: .cache/tmp/p03_gate_1b022a0fc4214c92aa9b263b554dfcdc/live_checks.json. Final tests: .cache/tmp/p03_final_dc27ab6958554bb180e8aa2cb1535f87/results.xml; baseline also in logs/P02_report.md. Hariom's supplied counts and minimum are recorded in finding.py:acceptance. Labels such as P03 and E05 identify phases/episodes.
5. Tests: Before 217; new 104; total 321; failures 0 on the final full-suite run after the refusal fix. The initial offline run had 320 passed and 1 failed; stable reveal field ordering fixed that failure. Existing refusal test cases now assert the full exact message/code for both commands.
6. Frozen items: eval/match_rule.md, eval/gold_rubric.md, eval/gold_template.csv and eval/HASHES.md unchanged. No eval file is in the change manifest. The E##-L### ID format, parser, checker, set_tiou implementation and shared models are unchanged. Frozen-file/index verification is recorded at the commit gate below.
7. Held-out seal: Real find/build E01 probes both returned exit 1 with HELD_OUT_REFUSED before sources/artifacts/secrets. No held-out understanding/moment/promo output exists. Existing parser/labelling artifacts preserved. Gold-label, gold-sealed and AI-label contents were not inspected. No show text, AI text or real character names printed. Recap refuses held-out predecessors before discovery/parsing; the only additional source episode needed by the DEV build was the available, non-held-out E18, solely for recap. It received no AI call or output.
8. Safety: No commit or push. No keys printed; the agent never inspected the real .env. Only the approved live application's existing loader accessed credentials. Every shell command ran from promo-finder with TEMP/TMP under .cache/tmp and project .venv Python. Every pytest invocation used a new basetemp and a cache_dir inside it. .cache/pytest-tmp untouched. Generated outputs remain ignored; no output is deleted. No show text was added to tracked files or commit messages. Guard/index evidence is below.
9. LLM calls: 16 logical calls, 20 HTTP requests, 4 HTTP 429s, 0 cache hits, 0 terminal failures. Returned model string for both parts: gpt-5-mini-2025-08-07. Input tokens 64,132; output tokens 11,904; configured-price USD 0.039841. Reveals: 8 calls / 8 requests / 0 429s / 25,584 input / 3,860 output / USD 0.014116. Moments: 8 calls / 12 requests / 4 429s / 38,548 input / 8,044 output / USD 0.025725. API failures without usage are not assigned invented token charges. Fake-provider tests are excluded.
10. Risks and open items for the next prompt: Commit approval remains pending. There is no judge, frozen ranking formula, baseline, scoring, full run or app. Higher reveal counts need later semantic review; count acceptance alone proves no precision claim. Required spoiler/join/speaker gates yield no promos for E05/E06/E20/E21. Reveal flag mode is a measured counterfactual, not the configured output. Four 429s still occurred despite pacing; bounded Retry-After recovered them. Recap produced no flagged promo starts by either method. Do not alter frozen items, loosen gates or run held-out episodes to improve counts. Never push.

Implementation evidence

Modified files:

- D:/sem_iitk/sem9/kuku/promo-finder/config.yaml
- D:/sem_iitk/sem9/kuku/promo-finder/src/promo_finder/config.py
- D:/sem_iitk/sem9/kuku/promo-finder/src/promo_finder/llm.py
- D:/sem_iitk/sem9/kuku/promo-finder/src/promo_finder/reveals.py
- D:/sem_iitk/sem9/kuku/promo-finder/src/promo_finder/cli.py
- D:/sem_iitk/sem9/kuku/promo-finder/tests/test_llm.py
- D:/sem_iitk/sem9/kuku/promo-finder/tests/test_reveals.py

Created files:

- D:/sem_iitk/sem9/kuku/promo-finder/src/promo_finder/moments.py
- D:/sem_iitk/sem9/kuku/promo-finder/src/promo_finder/finding.py
- D:/sem_iitk/sem9/kuku/promo-finder/src/promo_finder/builder.py
- D:/sem_iitk/sem9/kuku/promo-finder/tests/test_moments.py
- D:/sem_iitk/sem9/kuku/promo-finder/tests/test_find.py
- D:/sem_iitk/sem9/kuku/promo-finder/tests/test_builder.py
- D:/sem_iitk/sem9/kuku/promo-finder/tests/test_build.py
- D:/sem_iitk/sem9/kuku/promo-finder/logs/P03_report.md

Generated, git-ignored files (the episode set is exactly 05,06,07,08,19,20,21,22):

- outputs/understanding/archive_p02/reveals_E##.json: archived originals, retained.
- outputs/understanding/reveals_E##.json: v2 replacements.
- outputs/moments/moments_E##.json and outputs/moments/find_summary.json.
- outputs/promos/candidates_E##.json, outputs/promos/build_summary.json and outputs/promos/dev_review.md.
- outputs/understanding/.llm_cache/<cache_key>.json and metadata-only outputs/logs/llm_calls.jsonl.
- Test/gate evidence under .cache/tmp. Existing parsed/labelling/intensity/policy/character/header artifacts are preserved.

Timestamp checker inspection

Unchanged public functions in src/promo_finder/checker.py:

```python
build_index(episodes: Iterable[Episode]) -> LineIndex
check_promo(spans: list[tuple[str, str]], index: Mapping[str, Line], cfg=None) -> CheckResult
snap_to_lines(ep: int, start_ms: int, end_ms: int, index: Mapping[str, Line]) -> tuple[tuple[str, str], int, int]
```

The builder accepts line-ID spans only. It obtains segment times and duration from check_promo, checks construction and reactions, and rechecks every retained candidate. snap_to_lines is unused. Independent post-build validation checked all 9 promos: every exported endpoint equals the checker's parsed-line endpoint, flattened line IDs and duration match, segment count is at most 2, and no marked reveal or resolution is included in block-mode output. Provenance matches the saved moment/reveal call metadata. All episode accounting reconciles generated = dropped + kept. Evidence: live_checks.json and candidate files.

P02 versus current prompting and wrapper behavior

P02 used short reveal/resolution definitions with permission to return no marks, without every-scene guidance or an invented example. V2 uses the approved definitions, scene guidance and one invented example; the response schema is unchanged and no mark quota is imposed.

P02 read numeric Retry-After and retry-after-ms, used exponential retries and capped waits at 120 seconds. It had no minimum interval or per-call effort override. The current wrapper applies provider-scoped physical-request concurrency/spacing, including retries and Azure paths. Effective per-call effort is inserted into params before cache hashing. Reveals and moments use configured low effort; other calls retain their model default. No OpenAI-family temperature is sent. SDK automatic retries stay disabled. Every physical attempt consumes max_calls_per_run.

Retry-After is followed only for a positive wait at most rate_limit.max_retry_after_s, configured 60 seconds; larger/invalid/nonpositive/nonfinite values use existing capped exponential backoff. Tests cover numeric seconds, milliseconds, HTTP dates, the configured bound and disabled handling. The live recovered retry waits were 2.044, 4.267, 5.032, 7.003 seconds, from llm_calls.jsonl. They are wait durations, not invented response usage.

Recap implementation and measured counts

Normalization lower-cases, removes punctuation and collapses whitespace. For available non-held-out E-1, each of the first 12 current lines is compared to any of the last 15 predecessor lines using stdlib SequenceMatcher; the inclusive ratio threshold is 0.85. Otherwise, including the first episode, use the first 5 seconds. These values are configurable in builder. Only the first segment's starting line determines possible_recap; it applies the configured 0.5 penalty and never directly drops a promo. E05 uses fallback because E04 is sealed. The other requested episodes use similarity; E19 uses the available unsealed E18. Sources: config.yaml, builder.py and build_summary.json.

| Episode | Method | Recap lines | Generated similarity flags | Generated fallback flags | Kept similarity flags | Kept fallback flags |
|---|---|---|---|---|---|---|
| E05 | fallback | 4 | 0 | 0 | 0 | 0 |
| E06 | similarity | 0 | 0 | 0 | 0 | 0 |
| E07 | similarity | 0 | 0 | 0 | 0 | 0 |
| E08 | similarity | 0 | 0 | 0 | 0 | 0 |
| E19 | similarity | 0 | 0 | 0 | 0 | 0 |
| E20 | similarity | 0 | 0 | 0 | 0 | 0 |
| E21 | similarity | 0 | 0 | 0 | 0 | 0 |
| E22 | similarity | 0 | 0 | 0 | 0 | 0 |

Method totals: similarity used for 7 episodes, fallback for 1. Both methods yielded 0 flagged generated/kept promo starts. There were 4 fallback-window lines in E05; no surviving structural candidate started on them. Similarity found 0 recap lines in the other DEV episodes. These are observed counts, not an accuracy claim.

DEV dry-run evidence

Command, with the required environment prefix:

```powershell
.\.venv\Scripts\python.exe -m promo_finder find --eps 5-8,19-22 --dry-run
```

Exit 0; no client, secrets or LLM-cache read, and no find output written. Count-only stdout is preserved in dry_run.json.

| Part | Calls | Known input | Dependency allowance | Estimated input | Output budget | Estimated USD |
|---|---|---|---|---|---|---|
| reveals | 8 | 25676 | 0 | 25676 | 48000 | 0.102419 |
| moments | 8 | 37756 | 48000 | 85756 | 48000 | 0.117439 |
| Total | 16 | 63432 | 48000 | 111432 | 96000 | 0.219858 |

Configured max_calls_per_run is 50. Picker azure_mini uses deployment mini; both purposes use low effort and the base completion limit is 6,000 tokens per call. Pricing from config.yaml: USD 0.25 per million input tokens and USD 2.00 per million output tokens, source RESEARCH. Unknown reveal hints receive one predecessor completion allowance per episode. Estimates exclude retries/cache savings; actual usage is below.

Live-run evidence

After explicit live approval, one network-enabled invocation ran:

```powershell
.\.venv\Scripts\python.exe -m promo_finder find --eps 5-8,19-22
```

Exit 0, status complete. It archived all 8 P02 reveal files before replacement, ran all 8 reveal calls before all 8 moment calls, then evaluated acceptance. No second live invocation, no model change and no no-cache rerun occurred. No schema/truncation retries occurred. Sources: find_summary.json and llm_calls.jsonl.

| Part | Calls | HTTP requests | 429s | Cache hits | Returned model strings | Input tokens | Output tokens | USD | Failures |
|---|---|---|---|---|---|---|---|---|---|
| reveals | 8 | 8 | 0 | 0 | gpt-5-mini-2025-08-07 | 25584 | 3860 | 0.014116 | 0 |
| moments | 8 | 12 | 4 | 0 | gpt-5-mini-2025-08-07 | 38548 | 8044 | 0.025725 | 0 |
| Total | 16 | 20 | 4 | 0 | gpt-5-mini-2025-08-07 | 64132 | 11904 | 0.039841 | 0 |

P02 versus v2 reveal counts

| Episode | P02 reveals | P02 resolutions | v2 reveals | v2 resolutions |
|---|---|---|---|---|
| E05 | 0 | 0 | 3 | 4 |
| E06 | 0 | 0 | 2 | 2 |
| E07 | 0 | 0 | 0 | 1 |
| E08 | 0 | 0 | 2 | 1 |
| E19 | 0 | 0 | 4 | 2 |
| E20 | 0 | 0 | 3 | 2 |
| E21 | 2 | 0 | 3 | 1 |
| E22 | 0 | 0 | 1 | 0 |
| Total | 2 | 0 | 18 | 13 |

Source: archived P02 files and v2 files/find_summary.json. Archive count: 8; archived counts match the preflight P02 counts. No archive was overwritten or deleted.

| Episode | Hariom reveals | Hariom resolutions | v2 reveals | v2 resolutions | Hariom total | v2 total |
|---|---|---|---|---|---|---|
| E05 | 0 | 2 | 3 | 4 | 2 | 7 |
| E19 | 3 | 1 | 4 | 2 | 4 | 6 |
| Total | 3 | 3 | 7 | 6 | 6 | 13 |

Acceptance: PASS, because 13 is at least 3. Hariom's total is 6. V2 total is higher; counts alone do not establish whether the extra marks are correct. No further model calls were made to reconcile those counts.

Moments per DEV episode

| Episode | Hooks | Model cliffs | Episode-end cliffs added | Final cliffs | low_recall |
|---|---|---|---|---|---|
| E05 | 4 | 5 | 1 | 6 | false |
| E06 | 6 | 5 | 1 | 6 | false |
| E07 | 5 | 5 | 1 | 6 | false |
| E08 | 5 | 5 | 1 | 6 | false |
| E19 | 5 | 5 | 1 | 6 | false |
| E20 | 5 | 4 | 1 | 5 | false |
| E21 | 5 | 4 | 0 | 4 | false |
| E22 | 6 | 5 | 0 | 5 | false |
| Total | 41 | 38 | 6 | 44 | 0 |

Hook counts by type:

| Episode | H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 | H9 |
|---|---|---|---|---|---|---|---|---|---|
| E05 | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| E06 | 0 | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 1 |
| E07 | 0 | 1 | 1 | 1 | 0 | 0 | 1 | 1 | 0 |
| E08 | 1 | 0 | 1 | 1 | 0 | 1 | 0 | 1 | 0 |
| E19 | 0 | 0 | 2 | 1 | 1 | 0 | 0 | 1 | 0 |
| E20 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 0 |
| E21 | 0 | 0 | 1 | 0 | 2 | 1 | 0 | 1 | 0 |
| E22 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 0 |
| Total | 4 | 4 | 9 | 4 | 6 | 5 | 1 | 7 | 1 |

Final cliff counts by type, including the episode-end additions:

| Episode | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 |
|---|---|---|---|---|---|---|---|---|---|
| E05 | 2 | 2 | 0 | 0 | 1 | 0 | 0 | 1 | 0 |
| E06 | 3 | 1 | 0 | 1 | 1 | 0 | 0 | 0 | 0 |
| E07 | 2 | 2 | 0 | 1 | 0 | 1 | 0 | 0 | 0 |
| E08 | 2 | 1 | 2 | 0 | 1 | 0 | 0 | 0 | 0 |
| E19 | 3 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 |
| E20 | 3 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| E21 | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 0 |
| E22 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 0 |
| Total | 17 | 8 | 5 | 5 | 4 | 1 | 0 | 4 | 0 |

Sources: moments_E##.json and find_summary.json. Low recall is assessed before fallback insertion and is false for every DEV episode. There were 0 invalid IDs dropped, 0 duplicates removed, and 0 word-limit trims in either live part; sources are saved metadata aggregated in live_checks.json. The episode-end candidate was already present in E21/E22; it was added in the other requested episodes. No low-recall retry was performed.

Code-only build evidence

Command:

```powershell
.\.venv\Scripts\python.exe -m promo_finder build --eps 5-8,19-22
```

Exit 0. No secrets or model calls. Sources: outputs/promos/build_summary.json and candidates_E##.json. Primary drops are exclusive; order is checker, J2, J4, speakers, resolution, late_series, reveal, dedupe, cap. Montage replaces a too-long continuous attempt for the same pair; it is not counted as an extra generated pair. Checker failures include construction failures. Reaction adjustments precede join/spoiler checks, with approved E1 precedence.

| Episode | Generated | checker | J2 | J4 | speakers | resolution | reveal | late_series | dedupe | cap | Kept |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E05 | 20 | 6 | 0 | 4 | 8 | 0 | 2 | 0 | 0 | 0 | 0 |
| E06 | 29 | 4 | 0 | 11 | 0 | 5 | 9 | 0 | 0 | 0 | 0 |
| E07 | 21 | 5 | 0 | 0 | 4 | 4 | 0 | 0 | 4 | 0 | 4 |
| E08 | 25 | 5 | 0 | 0 | 0 | 8 | 7 | 0 | 2 | 0 | 3 |
| E19 | 21 | 4 | 0 | 4 | 1 | 9 | 1 | 0 | 1 | 0 | 1 |
| E20 | 15 | 3 | 0 | 1 | 7 | 0 | 4 | 0 | 0 | 0 | 0 |
| E21 | 19 | 7 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| E22 | 26 | 11 | 0 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 1 |
| Total | 176 | 45 | 0 | 20 | 20 | 26 | 49 | 0 | 7 | 0 | 9 |

Checker details: TOO_SHORT totals 37; MONTAGE_CONSTRUCTION totals 8. J5 included 82 reactions across generated candidates that reached its stage and flagged reaction_cut on 5 such candidates; none of the 9 retained promos has reaction_cut. These counts include candidates later dropped. Sources: per-episode checker_errors/reactions_included/reaction_cut_candidates in build_summary.json and retained flags in live_checks.json.

Reveal-mode comparison through independent dedupe and cap:

| Episode | Block before dedupe/cap | Block final kept | Flag before dedupe/cap | Flag final kept |
|---|---|---|---|---|
| E05 | 0 | 0 | 2 | 1 |
| E06 | 0 | 0 | 9 | 6 |
| E07 | 8 | 4 | 8 | 4 |
| E08 | 5 | 3 | 12 | 5 |
| E19 | 2 | 1 | 3 | 2 |
| E20 | 0 | 0 | 4 | 4 |
| E21 | 0 | 0 | 12 | 6 |
| E22 | 1 | 1 | 15 | 6 |
| Total | 16 | 9 | 65 | 34 |

Configured output remains block. Resolution and late-series drops apply in both branches. The flag branch writes no alternative promo artifacts. Four DEV episodes have 0 kept candidates in block mode: E05, E06, E20, E21. The remaining kept counts are E07=4, E08=3, E19=1, E22=1.

Kept durations: min 20.0 seconds, median 25.0 seconds, max 43.5 seconds. Montage: 4 of 9, share 0.4444444444444444 (44.44% rounded). Recap and reaction-cut flags on retained promos: 0 by either method. Policy flags are attached without suppression: 4 kept promos carry the self_harm category. These policy counts are annotations only. Sources: build_summary.json, candidates files and live_checks.json.

The top-up-to-2-per-episode review is in ignored outputs/promos/dev_review.md. It contains transcript lines and was not printed or copied into this report. Episodes with no kept candidate remain represented by their zero count.

Final test evidence

After the refusal fix, the final command used a new unique base:

```powershell
$p03Base = 'D:\sem_iitk\sem9\kuku\promo-finder\.cache\tmp\p03_final_dc27ab6958554bb180e8aa2cb1535f87'
.\.venv\Scripts\python.exe -m pytest -q --tb=no --basetemp "$p03Base" -o "cache_dir=$p03Base/pytest_cache" --junitxml "$p03Base/results.xml"
```

Result: 321 passed, 0 failures. The recorded basetemp is completed-run evidence and must never be reused. Future pytest invocations require a fresh unique path.

| Test file | Passing cases |
|---|---|
| tests/test_build.py | 16 |
| tests/test_builder.py | 38 |
| tests/test_characters.py | 6 |
| tests/test_checker.py | 17 |
| tests/test_export_gold.py | 8 |
| tests/test_find.py | 14 |
| tests/test_gold.py | 47 |
| tests/test_guard.py | 12 |
| tests/test_hash_eval.py | 7 |
| tests/test_header.py | 3 |
| tests/test_intensity.py | 4 |
| tests/test_list_lines.py | 8 |
| tests/test_llm.py | 58 |
| tests/test_moments.py | 5 |
| tests/test_parser.py | 27 |
| tests/test_policy.py | 16 |
| tests/test_reveals.py | 4 |
| tests/test_tiou.py | 9 |
| tests/test_understand.py | 14 |
| tests/test_workbook.py | 8 |
| Total | 321 |

Tests use invented fixtures and fake providers/clocks. They cover schema ID enums, per-call effort/cache separation, spacing, bounded Retry-After, moment cleaning/fallback/recall, find/archive/acceptance/accounting, construction and join/spoiler/policy rules, recap matching/fallback/seal, dedupe/cap and every kept candidate's checker validation. Both held-out CLI tests assert the exact refusal message/code across their parameterized sealed selections; sources tests/test_find.py and tests/test_build.py.

New held-out probe evidence

Commands, with the standard environment prefix:

```powershell
.\.venv\Scripts\python.exe -m promo_finder find --eps 1 --dry-run
.\.venv\Scripts\python.exe -m promo_finder build --eps 1
```

Actual output:

```text
find: refused: held-out episodes require --allow-held-out; error=HELD_OUT_REFUSED
find_held_out_exit=1
build: refused: held-out episodes require --allow-held-out; error=HELD_OUT_REFUSED
build_held_out_exit=1
```

No override flag was passed. No held-out understanding/moment/promo file exists; count 0. Sources: live_checks.json, test assertions and the probe command results. P02 understand remains unchanged.

Commit gate evidence

Staged with git add -A, as requested. Staging is complete; committing is pending. git status --short shows only the approved files:

```text
M  config.yaml
A  logs/P03_report.md
A  src/promo_finder/builder.py
M  src/promo_finder/cli.py
M  src/promo_finder/config.py
A  src/promo_finder/finding.py
M  src/promo_finder/llm.py
A  src/promo_finder/moments.py
M  src/promo_finder/reveals.py
A  tests/test_build.py
A  tests/test_builder.py
A  tests/test_find.py
M  tests/test_llm.py
A  tests/test_moments.py
M  tests/test_reveals.py
```

The staged manifest is exactly the 15 approved tracked source/config/test/report paths. No outputs/, data/, .cache/, .xlsx, eval/gold*.csv, secret file, frozen file or HASHES.md change is staged. Git status also shows no frozen worktree change. git diff --cached --check is clean. git diff --stat --cached was shown at the gate; its final output and manifest checks are saved in .cache/tmp/p03_gate_1b022a0fc4214c92aa9b263b554dfcdc/commit_gate.json.

Default staged guard command and result:

```powershell
.\.venv\Scripts\python.exe tools/guard.py
```

```text
guard: clean (15 files checked, mode=staged)
```

After adding this guard evidence, the report is restaged and the staged guard is rerun against the final index. No Python implementation changed after the final passing suite. The agent stops here for the separate commit approval.

Commit is not authorized until the user sends APPROVED at this gate. Proposed command after that approval only:

```powershell
git commit -m "P03: reveals v2, pacing, moment finder, promo builder on DEV"
```

Never push. This report is a snapshot prepared before committing; final commit SHA belongs in the post-commit response.
