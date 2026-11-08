PLAIN SUMMARY
- What happened: Implemented the approved show-understanding layer and ran the DEV pipeline once. All outputs were written. The test suite passed 217 tests (168 existing + 49 new). The live run completed 11 logical calls using 17 HTTP requests.
- What it means: DEV understanding is complete: coverage is 100% (231/231 dialogue lines), with 17 speaker labels, 2 reveal marks, 0 resolution marks, and 21 policy hits. The monetary estimate from reported usage is USD 0.01536525. Commit approval remains pending.
- Problems: Six HTTP 429 attempts recovered through wrapper retries; there were no failed logical calls or response-validation failures. The original pytest temporary-directory issue and initial schema-inspection test bug were resolved before the final passing suite.
- Decision needed (options + your pick): Approve the P02 commit, or request changes. Pick: approve the reviewed implementation and DEV-only outputs; keep all generated data ignored and never push.
- Exact next message for Hariom to send to the chat: APPROVED. Commit P02 with the approved commit message. Do not push.

SELF-AUDIT

1. Steps done: each prompt step -> done / not done, with evidence (file, command, output)

| Step | Status | Evidence |
|---|---|---|
| Step 0 location/base | Done | Project working directory; approved baseline dc55eb14db4c739b12497e8dc1669db3ac1e6573; baseline clean |
| Step 0 source review | Done | Reviewed llm.py, config.py, models.py, parser.py, cli.py, labelling.py, config.yaml, tools/guard.py |
| Step 0 tests | Done | Successful baseline: 168 passed; fresh temporary directory recorded in metadata.json |
| PLAN and approval | Done | One A-H plan approved with explicit amendments; implementation follows those amendments |
| A standing rules | Done | AGENTS.md; HASHES.md rule is append-only for the user, agents never edit it |
| B intensity | Done | intensity.py; intensity_E##.json for all requested DEV episodes; 568 rows |
| C policy | Done | policy.py; policy_E##.json; 21 canonical hits across DEV |
| D character sheet | Done | Two character chunks merged into characters.json; 17 labels; 100% coverage |
| E show header | Done | show_header.json; all field limits verified by code |
| F reveals/resolutions | Done | reveals_E##.json for all requested DEV episodes; ID/count/word-limit checks passed |
| G command/dry-run/seal | Done | CLI tests; real DEV dry-run succeeded; real held-out request returned exit 1 |
| G live gate/run | Done | Explicitly approved command executed once, outside sandbox for Azure access; exit 0; 17 requests within limit 50 |
| H tests/report/guard | Done | JUnit: 217 passed; finalized report; postlive-audit.json; staged guard clean on 21 files |
| H staging/commit gate/commit | Staging done; STOP at commit gate; commit not done | git add -A; 21 approved staged files; guard clean; awaiting explicit commit approval |

2. Decisions I made that the prompt did not specify: what, why, alternative

- Proposed intensity weights, token definitions, centered smoothing with available edge neighbors, constant normalization to zero, and the action-verb subset were approved. They give deterministic behavior; alternatives were other weights, edge padding, or broader term matching.
- ALL-CAPS requires at least two letters; strong emotion matches the entire trimmed, lower-case tag. Short dialogue has one through four word tokens. The first dialogue line has no speaker-change feature.
- The approved profanity vocabulary is explicit in config/policy_terms.yaml. Matching is case-insensitive with Unicode word boundaries, curly-apostrophe normalization, and flexible phrase whitespace. Each canonical line/category/term combination is emitted once.
- PolicyScanner owns its flag index so promo_flags(line_ids) does not depend on module-global mutable state. A module-level scan(lines) convenience function is also available.
- The earliest chunk's role wins; alias unions ignore case; relationship unions use exact label/relation pairs. The code establishes first_line from actual speaker occurrences and counts corrections. Unsupported alias/mentioned-name claims are dropped with a count.
- Reveal duplicates use (line_id, type), retain the highest confidence, and follow parsed line order. Alternatives included treating all same-line marks as duplicates or retaining the first confidence.
- Shared helpers live in understanding_common.py. Orchestration owns count-only summaries and preflight. Existing model/parser/label/guard code remains unchanged.
- The configured chunk size defaults to four episodes; gaps always split chunks. No additional repair calls are made for low coverage.
- Dry-run dependency allowances reserve predecessor completion budgets rather than fabricate character or header text. They are planning estimates, not exact predictions of later prompts.

3. Deviations from the prompt: what, why

- Approved baseline correction: use dc55eb1, preserving the two hash-only seal commits after P01c. HASHES.md was not edited.
- Approved pytest deviation: every subsequent pytest invocation uses a new unique --basetemp below .cache/tmp. The original .cache/pytest-tmp was not retried, deleted, or modified after the initial failed attempt. The successful Step 0 retry is recorded below.
- The successful Step 0 retry had a cache-provider write warning. Implementation runs additionally set pytest's cache_dir inside their fresh temporary directory; the final suite has no warning.
- Approved schema amendment: no pattern/minLength constraints are sent. Each short field has a description stating its word limit. Code normalizes whitespace, trims over-long fields, and records counts per field. The planned wrapper pattern-validator change was dropped.
- Approved coverage amendment: coverage below 95% sets coverage_below_target in characters.json and run_summary.json and continues through header/reveals. An invented-fixture pipeline test verifies this.
- Approved pricing amendment: use supplied Azure gpt-5-mini rates under pricing in config.yaml; source tag RESEARCH, list price, Global Standard.
- Approved frozen-file wording amendment: HASHES.md is append-only, only Hariom adds rows via tools/hash_eval.py; agents never edit it. The other three frozen files are never edited.
- Approved held-out interpretation: the seal audit concerns new understanding outputs. Prior parsed and labelling artifacts remain present and preserved.
- The first implementation test failure was in the test schema walker: a property named type was mistaken for a schema declaration. The test was corrected to recognize string-valued schema types; production behavior was unchanged by that correction.

4. Numbers: every number with the file it comes from

Evidence directory (E): `.cache/tmp/p02-prelive-98646482c33945bd972fd625a541a407/`.
Final test result (T): `.cache/tmp/p02-tests-c4f1d10582164bc097786aefcd691d91/results.xml`.
All paths in this report are relative to `D:\sem_iitk\sem9\kuku\promo-finder` unless fully qualified.

| Numbers | Source |
|---|---|
| Baseline 168 passed; final 217 passed; 49 new; 0 final failures/errors | E/metadata.json; T; baseline provenance is the successful Step 0 console result |
| First implementation run: 213 passed, 1 failed | .cache/tmp/p02-tests-f997fcfcb584464c81e60dd753db09f8/results.xml |
| DEV: 8 episodes, 568 lines, 231 dialogue lines, 17 distinct dialogue speaker labels, 0 missing loglines | E/metadata.json, inputs |
| First chunk: episodes 5-8, 280 lines, 9 labels; second: episodes 19-22, 288 lines, 10 labels | E/metadata.json, inputs.chunks |
| Calls: 2 character + 1 header + 8 reveals = 11; configured request limit 50 | E/dry-run.json; config.yaml |
| Estimated input 198509 tokens; output budget 66000 tokens; USD 0.18162725 | E/dry-run.json; computation in understanding_common.py |
| Rates: USD 0.25 input and USD 2.00 output per million tokens | config.yaml, pricing.azure_mini; user-supplied RESEARCH list price, Global Standard |
| Base completion cap 6000 per call; reasoning effort minimal; deployment mini | config.yaml, models.azure_mini |
| Character chunk default 4; coverage target 95%; camera cap 120 characters | config.yaml; characters.py; understanding_common.py |
| Word limits: role 6, relation 4, alias/mentioned-name 6, header 4/20/25/6/10, reveal what 12 | characters.py; header.py; reveals.py schema descriptions and code trimming |
| Smoothing window 3; short dialogue maximum 4 words; weights and 7 emotion tags | intensity.py; config.yaml, intensity |
| Pre-live: held-out refusal exit 1; 0 held-out understanding files; 0 real requests | E/metadata.json; E/held-out-refusal.txt |
| Existing parsed files 50, including 16 held-out; labelling files 17, including 16 held-out | E/metadata.json, held_out_file_metadata; filenames counted only |
| Pre-report working-file guard: 20 checked, clean; default guard: 0 staged files, clean | Command output; E/guard-staged.txt; final report-inclusive scan recorded below |
| Pre-live report-inclusive working-file guard: 21 checked, clean; AGENTS.md: 16 lines; pre-live staged paths: 0 | E/guard-working.txt; E/manifest.json; AGENTS.md; pre-live check command |
| Live: 11 logical calls, 17 physical requests, 0 cache hits, 6 retries, 6 HTTP 429 failures, 0 failed logical calls, 0 response failures | outputs/understanding/run_summary.json; E/postlive-audit.json; outputs/logs/llm_calls.jsonl |
| Live reported usage: 46589 input tokens, 1859 output tokens; USD 0.01536525 estimate | outputs/understanding/run_summary.json, llm; config.yaml pricing |
| Coverage: 100%, 231/231 dialogue lines, 17 speaker labels; coverage_below_target=false | outputs/understanding/run_summary.json, character_counts; outputs/understanding/characters.json metadata/counts |
| Live marks: 2 reveals, 0 resolutions; policy hits: 21 total (14 violence, 1 sexual, 3 self_harm, 3 minors; other categories 0) | outputs/understanding/run_summary.json, marks and policy_hits |
| Word-limit trims: 0 in each of 10 field groups | outputs/understanding/run_summary.json, trims_by_field |
| Character first-line corrections: 8 + 2 = 10; unsupported name claims dropped: 0 + 1 = 1 | E/postlive-audit.json, counts.character_checks; chunk metadata |
| Understanding artifacts: 29 root files, 11 cache files; 0 held-out episode files; post-live refusal exit 1 with no output/log changes | E/postlive-audit.json; E/postlive-held-out-refusal.txt |

5. Tests: before count, new count, total, failures

Before: 168 passed. Added: 49 cases, including parameterized cases. Final: 217 passed, 0 failures, 0 errors, no warnings.

Successful Step 0 command used the existing virtual environment and `--basetemp .cache/tmp/p02-baseline-d0e0dbeebeb94f9c92de6b0975cb9515`.

Final command, run from the project with TEMP/TMP inside .cache/tmp:

```powershell
python -m pytest -q --tb=no --basetemp .cache/tmp/p02-tests-c4f1d10582164bc097786aefcd691d91 -o cache_dir=.cache/tmp/p02-tests-c4f1d10582164bc097786aefcd691d91/pytest-cache --junitxml .cache/tmp/p02-tests-c4f1d10582164bc097786aefcd691d91/results.xml
```

All new provider tests are offline and use invented input and fake responses. The dry-run estimator is stubbed in these tests. Existing integration parser tests remain part of the complete suite. Real secrets are replaced by invented/missing temporary env paths through the existing test fixture.

| File | Passed |
|---|---:|
| tests/test_characters.py | 6 |
| tests/test_checker.py | 17 |
| tests/test_export_gold.py | 8 |
| tests/test_gold.py | 47 |
| tests/test_guard.py | 12 |
| tests/test_hash_eval.py | 7 |
| tests/test_header.py | 3 |
| tests/test_intensity.py | 4 |
| tests/test_list_lines.py | 8 |
| tests/test_llm.py | 28 |
| tests/test_parser.py | 27 |
| tests/test_policy.py | 16 |
| tests/test_reveals.py | 3 |
| tests/test_tiou.py | 9 |
| tests/test_understand.py | 14 |
| tests/test_workbook.py | 8 |
| Total | 217 |

6. Frozen items: confirm untouched

All match the approved baseline byte-for-byte both before and after the live run (E/postlive-audit.json). `git diff --name-only -- eval` returned no paths. No gold-label files were edited. Line-ID formatting remains `E{ep:02d}-L{idx:03d}`; models.py and parser.py were not changed.

| Frozen file | SHA-256 |
|---|---|
| eval/match_rule.md | d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2 |
| eval/gold_rubric.md | 6f7b5161a66d857e913e5f73715f6b36c129d4cd57b69cd7d618e2b53f5550c0 |
| eval/gold_template.csv | bb794d8a826bbc62288c30d16010e162c647ae5bdd19673dc22ebaf422bd8391 |
| eval/HASHES.md | e1ee6bed429a88b004c4370bc0ea2cdb2f840e2141fae613ac29f629b508409c |

7. Held-out seal

- All real understanding artifacts are limited to DEV episodes 5-8,19-22. The post-live audit found zero held-out episode files.
- `python -m promo_finder understand --eps 1 --dry-run` was rerun after the live command and returned exit 1 with the same clear refusal.
- A before/after metadata snapshot verified that this refusal changed no understanding output or LLM call-log file. Evidence: E/seal-before.json and E/postlive-audit.json.
- The override flag was never passed. CLI tests also cover mixed selections and refusal before source loading.
- Earlier parsed/labelling artifacts were preserved. The new loader parses only requested source episodes.
- AI text was never displayed or manually inspected. Code checked IDs, counts, coverage, limits, and metadata without emitting the text.

8. Safety

- No push or commit occurred. Staging and final guard evidence are recorded below; commit requires separate approval.
- No keys were printed. The agent never manually opened, searched, printed, or inspected the real .env; credentials were loaded only through the existing application loader during the explicitly approved live command.
- Every shell command ran inside promo-finder with TEMP/TMP under .cache/tmp. All writes stayed inside the project, and no dependency was installed.
- Every pytest run after the initial inaccessible-directory attempt used a fresh unique --basetemp. The original .cache/pytest-tmp was left untouched after that attempt.
- Only the single approved live pipeline command received outside-sandbox network access. Subsequent work performed local checks and reporting; the live command was not rerun.
- No source or test changes were made after the final passing test suite. Only the report and ignored evidence/artifacts changed during the live/reporting phase.
- No script dialogue or real character names were copied into code, tests, report, console, or commit text. Tests use invented fixtures.
- Actual AI response/cache text is confined to ignored outputs/understanding. The existing LLM log and report contain only IDs, hashes, counts, usage, model strings, and safe error codes.
- Final staged guard/path checks and frozen hashes are recorded below. Generated outputs, workbooks, secrets, gold labels, and frozen-file changes must not be staged.

9. LLM calls: count, models, tokens, cost estimate, cache hits

The approved live command ran once and exited 0. It completed 11 logical calls using 17 physical HTTP requests, with 0 cache hits, 6 recovered HTTP 429 failures/retries, 0 failed logical calls, and 0 response-validation failures. The returned model string for every part was gpt-5-mini-2025-08-07. Reported usage totals 46589 input tokens and 1859 output tokens; the list-price estimate is USD 0.01536525. Per-part evidence appears below.

The wrapper's public signature and cache-key algorithm are unchanged. The key is SHA-256 of canonical JSON containing provider, configured model, effective parameters, messages, and strictified schema. Temperature is removed for OpenAI-family models. Physical HTTP requests, including backoff and Azure fallback attempts, now share the configured budget. Metadata records retry events and failed attempts without provider message bodies.

The original wrapper checks its cache before its dry-run branch. The understand dry-run instead calls only the existing estimator: it creates no client, loads no secrets, makes no calls, and writes no understanding outputs. Cache-hit usage is excluded from new-token and cost totals. Usage from rejected schema/truncated responses is included when the provider supplies it.

Pricing is RESEARCH: user-supplied Azure gpt-5-mini list price, Global Standard. Cost computation is `(input_tokens * 0.25 + output_tokens * 2.00) / 1000000` USD. No discount for provider-side prompt caching is assumed. Unknown usage from transport failures cannot be reconstructed.

10. Risks and open items for the next prompt

- Coverage met the target: 100%, and coverage_below_target is false. Pointer/name provenance checks corrected 10 first-line pointers and dropped one unsupported name claim; no word-limit trims were needed.
- Only two reveals and no resolutions were returned. P02 has not measured semantic recall or accuracy; enum and code checks establish ID validity and deterministic formatting, not story interpretation quality.
- The live command recovered from six HTTP 429 attempts. All 17 physical requests remained within the configured limit of 50. No additional live run or repair call was issued.
- Cost uses reported token usage and the supplied RESEARCH list prices, Global Standard. It does not apply provider-side prompt-cache discounts or reconstruct any unknown usage for failed transport attempts.
- The report and source are prepared for the commit gate. Await explicit approval, commit with the approved message, and never push. Do not add moment finding, promo building, judging, ranking, or an app.

Evidence: files created/changed

Created:

```text
D:\sem_iitk\sem9\kuku\promo-finder\AGENTS.md
D:\sem_iitk\sem9\kuku\promo-finder\config\policy_terms.yaml
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\intensity.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\policy.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\characters.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\header.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\reveals.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\understanding_common.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\understanding.py
D:\sem_iitk\sem9\kuku\promo-finder\tests\test_intensity.py
D:\sem_iitk\sem9\kuku\promo-finder\tests\test_policy.py
D:\sem_iitk\sem9\kuku\promo-finder\tests\test_characters.py
D:\sem_iitk\sem9\kuku\promo-finder\tests\test_header.py
D:\sem_iitk\sem9\kuku\promo-finder\tests\test_reveals.py
D:\sem_iitk\sem9\kuku\promo-finder\tests\test_understand.py
D:\sem_iitk\sem9\kuku\promo-finder\logs\P02_report.md
```

Changed:

```text
D:\sem_iitk\sem9\kuku\promo-finder\config.yaml
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\config.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\cli.py
D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\llm.py
D:\sem_iitk\sem9\kuku\promo-finder\tests\test_llm.py
```

Evidence: dry-run output

Command: `python -m promo_finder understand --eps 5-8,19-22 --dry-run`. Exit: 0. Full count-only JSON: E/dry-run.json.

| Part | Calls | Known input | Dependency allowance | Estimated input | Output budget | Estimated USD |
|---|---:|---:|---:|---:|---:|---:|
| Characters | 2 | 20516 | 0 | 20516 | 12000 | 0.029129 |
| Header | 1 | 597 | 12000 | 12597 | 6000 | 0.01514925 |
| Reveals | 8 | 21396 | 144000 | 165396 | 48000 | 0.137349 |
| Total | 11 | 42509 | 156000 | 198509 | 66000 | 0.18162725 |

The planned call count is within max_calls_per_run=50. These are prospective uncached calls. Output budgets exclude wrapper retries that can expand the completion cap.

Evidence: live-run summary per part

Source: `outputs/understanding/run_summary.json`; metadata-only copy in E/live-console.json; independent checks in E/postlive-audit.json. Command: `python -m promo_finder understand --eps 5-8,19-22`. It ran once with explicit outside-sandbox network approval and exited 0.

| Part | Logical calls | HTTP requests | Cache hits | Returned model string | Input tokens | Output tokens | Estimated USD | Retries | HTTP failures | Response failures | Failed calls |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| Intensity/policy | 0 | 0 | 0 | None (code only) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Characters | 2 | 2 | 0 | gpt-5-mini-2025-08-07 | 20451 | 1590 | 0.00829275 | 0 | 0 | 0 | 0 |
| Header | 1 | 1 | 0 | gpt-5-mini-2025-08-07 | 1682 | 83 | 0.00058650 | 0 | 0 | 0 | 0 |
| Reveals | 8 | 14 | 0 | gpt-5-mini-2025-08-07 | 24456 | 186 | 0.00648600 | 6 | 6 | 0 | 0 |
| Total | 11 | 17 | 0 | gpt-5-mini-2025-08-07 | 46589 | 1859 | 0.01536525 | 6 | 6 | 0 | 0 |

Every HTTP failure was HTTP_429 and recovered. Usage from failed HTTP attempts was unavailable; the estimate uses returned response usage. No schema or empty/truncated-response retry was needed.

Coverage: 100% (231/231 dialogue lines), 17 speaker labels, coverage_below_target=false. Counts come from run_summary.json and the code audit; no names are reported.

Trims per field:

| Part | Field | Trims |
|---|---|---:|
| characters | role | 0 |
| characters | relationships.relation | 0 |
| characters | aliases | 0 |
| characters | mentioned_names | 0 |
| header | genre | 0 |
| header | central_conflict | 0 |
| header | main_relationships | 0 |
| header | tone | 0 |
| header | setting | 0 |
| reveals | what | 0 |

Additional provenance checks: first-line corrections were 8 and 2 across the two chunks, respectively; unsupported name claims dropped were 0 and 1. All reveal invalid-ID drops and duplicate-removal counts were zero. Word limits, character IDs/labels, reveal IDs/counts, intensity bounds, and deterministic policy rescans passed code checks.

Evidence: DEV marks and policy counts

| Episode | Reveals | Resolutions | Intensity rows |
|---|---:|---:|---:|
| E05 | 0 | 0 | 62 |
| E06 | 0 | 0 | 97 |
| E07 | 0 | 0 | 58 |
| E08 | 0 | 0 | 63 |
| E19 | 0 | 0 | 63 |
| E20 | 0 | 0 | 68 |
| E21 | 2 | 0 | 76 |
| E22 | 0 | 0 | 81 |
| Total | 2 | 0 | 568 |

Policy hits are distinct line/category/term flags, not necessarily unique flagged lines.

| Episode | violence | sexual | nonconsent_abuse | self_harm | minors | profanity | shock_fear | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E05 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 3 |
| E06 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| E07 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| E08 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 2 |
| E19 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 2 |
| E20 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 3 |
| E21 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| E22 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| Total | 14 | 1 | 0 | 3 | 3 | 0 | 0 | 21 |

Evidence: guard output

```text
guard: clean (0 files checked, mode=staged)
P02 working-file guard: clean (20 files checked)
P02 working-file guard: clean (21 files checked)
```

The first working-file scan preceded the initial report; the report-inclusive pre-live scan checked all 21 intentional files and was clean. Final staging used git add -A. The staged guard passed on all 21 approved files; E/guard-staged-live.txt records the output, and E/stage-check.json verifies the index scope. E/staged-status.txt and E/staged-stat.txt contain the final git status and git diff --stat --cached output. No commit or push has occurred; STOP at the commit gate.

Final commit-gate evidence:

```text
guard: clean (21 files checked, mode=staged)
```

- All 21 staged paths exactly match the approved source/config/test/report manifest.
- Index checks passed: no outputs/, .cache/, data/, .venv/, secret env files, workbooks, eval/gold*.csv, or any frozen file is staged.
- Frozen-file hashes match the approved baseline after the live run. The repeated held-out refusal returned exit 1 and changed no output or LLM log file.
- The latest test result remains 217 passed, 0 failures/errors; no production or test code changed after that run.
- Commit message prepared: `P02: show understanding (intensity, policy flags, characters, header, reveals) on DEV`.
- Decision now required: approve the commit. Commit has not been executed; never push.
