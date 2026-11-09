# P09 report: README, generated results, free workflow, app and raw package

9 November 2026. HEAD remains `d159589`. Prepared at the commit gate; no commit or push.

## PLAIN SUMMARY

The README now documents the finished tool and starts with five code-generated result lines. `docs/RESULTS.md` renders the unchanged official result files, with separate fresh A/B blocks and explicitly post-hoc held-out v2. v1 remains the default and v2 optional (D99). No evaluation was rerun or pooled.

The free path completed episodes 23–24 under D104 a, using a free-only 4,500-token answer-key cap and the approved singleton character batching. It kept and scored **four promos**, reused **seven upstream cache entries**, and completed all six promo stages. It made **14 pipeline HTTP requests plus one separate fresh preflight**, with **zero HTTP errors/429s**, **USD 0** recorded free-path cost, and **22,472 newly reported tokens** including preflight. Two Qwen schema-validation retries resolved using the unchanged retry mechanism. The earlier D102 partial attempt is preserved separately.

The Streamlit app has saved full results and live-upload tabs. The saved tab now shows five saved launch cards and a labelled 150-shows/month cost assumption. The public export contains no transcript, rationale, speaker labels or names. The private Drive handoff contains a code-generated transcript review of **107 promos**, never staged or committed.

The package and ZIP are built: **942 files**, **15,543,935 uncompressed bytes**, **1,878,622 ZIP bytes**. The final full suite passed **872 tests** in **53.94 seconds**. Frozen files, all official outputs, and all 36 D102 files are unchanged. Work stops at the commit gate.

## Built and measured

- `tools/make_results_table.py` renders four saved public metric JSON files into `docs/RESULTS.md`. It also inserts a five-line Results at a glance block at the very top of README, using those generated metric files. A/B remain separate; held-out v2 remains post-hoc. Missing/inconsistent metrics fail rather than inventing numbers.
- `docs/DECISIONS.md` contains only `Decision log: see project notes (copied by Hariom)`; Hariom supplies the content.
- `config/free.yaml` selects existing `groq_oss` and `groq_qwen`, with distinct openai/alibaba families, singleton character batches (D100 a), and only `purposes.answer_key.max_completion_tokens: 4500` (D104 a). The whitelist refuses other purpose/cap changes and any free-only setting on official roles. Official config, v1/v2 behavior, other caps, ranking, prompts, score formula and evaluation remain unchanged. The app reads the same overlay.
- The free pipeline skips the comparison baseline and retains promo judging/ranking/final checks. It requires only the Groq key. It is a small demo, not an evaluation or proof of free full-show capacity.
- `tools/export_app_results.py` builds `app/assets/full_results.json` from the saved full v1 ranking and full/v2 manifests. Every promo has exactly episode, start, end, duration, hook_type, cliff_type, S, lane and rank. Categoricals are fixed enums and times are formatted from numeric milliseconds. Other fields are discarded. The export contains 195 promos, the saved five launch-batch rows, seven Azure stage-usage rows, totals, v2 cost, scale arithmetic and source hashes. Size: 50,912 bytes.
- App tab `Full results (Azure run)` displays five metadata-only launch cards, all saved rows, `docs/RESULTS.md`, per-stage Azure calls/HTTP/tokens/USD/wall time and v2 rerun cost. The saved-results tab works without a Groq key. No cold-judge text, rationale or transcript is exported into the app.
- The `Cost at scale` box uses P07b totals from the export: USD 0.90769904 and 78.61403370833335 minutes per show. Multiplying by the explicit assumption of 150 identical shows/month gives USD 136.154856 and 11,792.10505625 minutes, or 196.53508427083338 serial hours. The UI labels workload/pricing/time equivalence as an assumption; it is not a measured monthly forecast. v2's cached rerun cost remains USD 0.25884782.
- App tab `Try it live (free)` keeps the passcode gate, maximum three UTF-8 episode uploads, content-free error box, ranked table and JSON download. Inputs, outputs, logs and cache are confined to an owned temporary tree and cleaned on success/failure. Only display/download data persists in the active session. The app reads keys from Streamlit secrets/environment, bypassing dotenv. Filename episode and source ID may differ, matching the parser contract.
- The real `.streamlit/secrets.toml` and private `top_promos_by_episode.md` filename are ignored and guard-blocked without opening them. `.streamlit/secrets.toml.example` lists names only. Requirements include Streamlit and editable installation of the local package.

## D102 a: preserved partial evidence

D102 used the exact earlier caps and fresh Groq preflight on episodes 23–24. Understanding, moment selection and building completed, keeping E23=0 and E24=4 candidates. The E24 answer-key request was refused locally before HTTP: wrapper-estimated input 2,879 + unchanged output cap 6,000 = **8,879 > 8,000 TPM**. A network-free reconstruction matched the failed prompt hash. No cold clip judging or ranking completed, and the attempt was not resumed after that refusal.

D102 made eight pipeline HTTP requests plus one separate preflight, with zero HTTP errors/429s and 23,642 reported tokens including preflight. Qwen was observed only in tiny preflight/guard pings. Its original manifest, cache, counts and refusal records remain under `outputs/runs/free_demo/`; all **36 files** still match their pre-D104 hashes. The D102 context and evidence files were not rewritten to claim success.

## D104 a: completed cached free attempt

D104 explicitly approved the free-only answer-key cap of 4,500 and reuse of the earlier cache. Existing pipeline run names are immutable, so the new attempt uses `outputs/runs/free_demo_d104/`, preserving the original directory without moving/deleting it. Eight cache files and saved upstream artifacts were copied and hash-verified. Upstream p02/p03 requests were enforced cache-only: **zero upstream HTTP requests**, seven cache hits. The same candidates were rebuilt.

Before any new request, the saved workload was checked offline:

| Request | Reservation against 8,000 TPM |
|---|---:|
| E24 answer key, estimated input 2,879 + output cap 4,500 | 7,379 |
| Largest of six scheduled Qwen cold-judge requests | 2,920 |
| Largest of four fidelity bounds, including generated-answer allowance | 1,011 |

All fit. Only the answer-key output cap changed; the cold-judge, fidelity, ping, picker and other caps stayed unchanged. The full dry schedule remained 30 calls / 36-request pipeline cap. The user-supplied free limits are 30 RPM, 1,000 RPD, 8,000 TPM and 200,000 TPD per model; remaining quota is an observation, not guaranteed by those entitlements.

A separate fresh uncached `groq_qwen` preflight succeeded under run `free_demo_d104_preflight`. Existing application code alone loaded credentials from the real `.env`; the assistant did not inspect it. The one-attempt runner `.cache/tmp/p09_d104_live.py` then called the existing pipeline entry point using the verified cache. No retry/resume after a terminal refusal occurred because **no terminal refusal occurred**.

| New D104 usage, including separate preflight | HTTP requests | Reported input tokens | Reported output tokens | Returned model |
|---|---:|---:|---:|---|
| groq_oss answer key | 1 | 3,349 | 652 | openai/gpt-oss-120b |
| groq_qwen, including preflight | 14 | 16,731 | 1,740 | qwen/qwen3.8-27b |
| Total | 15 | 20,080 | 2,392 | both above |

Provider-reported input tokens differ from the wrapper's pre-call estimate; they are not substituted for one another. New reported usage totals **22,472 tokens**. Cached response usage is excluded from this new-usage total.

The pipeline recorded 19 logical calls, seven cache hits and 14 HTTP requests; separate preflight added one logical call/HTTP request. Two Qwen schema-validation retries account for the extra HTTP requests beyond the uncached logical schedule. Both resolved; transport retries, HTTP errors and 429s were zero. All sent calls used Groq, with USD 0 configured free-path charge and no paid fallback. Runner wall time including preflight was **190.405 seconds**, about 3.2 minutes.

All stages completed: understand, find, build, judge, rank, snap/check. E23 kept zero candidates; E24 kept four and all four were selected/scored. Final lanes: **launch_batch=2, reserve=2, needs_human=0**. These are demo output counts, not recall or quality estimates. No gold was scored for this run.

Private evidence lives under `outputs/runs/free_demo_d104/`: `run_manifest.json`, `dry_run.json`, `d104_cache_copy.json`, `d104_execution_context.json`, `d104_live_evidence.json` and metadata-only call logs. The context records dirty working-tree provenance and source/config/overlay/runner fingerprints. D103's later UI/export/package edits did not alter the pipeline implementation used for D104.

## D103 a: presentation and confidential package

The five launch cards come from the saved official launch lane, not a new selection. The scale box is computed by the exporter from saved P07b totals. The five README result lines are regenerated by `tools/make_results_table.py`; they remain consistent with the saved public metric JSON files.

Offline AppTest passed with socket connections disabled, an invented passcode and no Groq key: zero exceptions, both tabs, five launch cards, scale box, three dataframes and seven metrics. Evidence: `.cache/tmp/p09_d103_smoke.json`. Earlier local Streamlit startup smoke also passed. No Cloud deployment or browser action occurred. Hariom deploys via Streamlit Cloud → New app → repository/branch → `app/streamlit_app.py`, Python 3.11+, with Secrets `APP_PASSCODE` and `GROQ_API_KEY`.

Package command:

```text
.venv/Scripts/python.exe -B tools/package_outputs.py --free-run free_demo_d104
```

Deliverables:

- `outputs/package/kuku_promo_finder_raw_outputs/`
- `outputs/package/kuku_promo_finder_raw_outputs.zip`

The package contains full v1/v2 stage outputs, completed D104 free outputs, preserved D102 partial outputs, P08/P08b metrics and ledgers, gold CSVs, redacted AI-label copies and README.txt. No `.llm_cache`, secret file or sealed AI-label original is included. Source artifacts were copied, never moved or edited.

`review/top_promos_by_episode.md` is generated inside the ignored package only: up to three promos per episode in saved official rank order, **107 promos** total, with rank, lane, cuts, hook/cliff codes, saved aggregate judge answers and transcript. Transcript lines come from original saved `outputs/parsed/E##.json` inputs and are checked against saved promo timestamps. This file and the entire package are **Drive-only confidential handoff material**, never committed. No Drive upload was performed.

| Package item | Count / size |
|---|---:|
| Files | 942 |
| Output files | 935 |
| Gold CSVs | 3 |
| Redacted AI-label CSVs | 2 |
| Review Markdown | 1 |
| README.txt | 1 |
| Total uncompressed bytes | 15,543,935 |
| ZIP bytes | 1,878,622 |

ZIP SHA-256: `e50fd97df13e128f57aa975ec19ef7198c47d4ca70167f9ec22abdd4688f076e`. Every ZIP entry matches its packaged file; AI-label row counts are preserved and rationale columns absent. Cache/secret entry counts are zero. Evidence: `.cache/tmp/p09_package_counts.json` and `.cache/tmp/p09_package_audit.json`. Only counts/sizes/hashes were printed, never review or label content.

## SELF-AUDIT

1. **Scope:** D100/D101, the D102 attempt, D104 retry/cap and D103 presentation/package work were explicitly authorized. This checkpoint stops before commit and push. The separate original commit gate remains in force.
2. **Evidence:** Public metrics and the app export reuse saved official files without scoring. D102 partial and D104 complete artifacts are separate. D104 reuses verified free-model cache entries; it is not represented as a cold run or evidence of full-show free scale.
3. **Changes:** Only approved free-role/batching/answer-key settings were enabled. Official configs, v1/v2 and all other caps remain unchanged. No tuning or recovery followed a terminal refusal. No pre-existing artifact was deleted or moved.
4. **Numbers:** A/B remain separate and held-out v2 post-hoc. Daily budgets and request estimates are distinguished from reported tokens. Monthly cost/time is explicitly an assumption. Demo candidate/lane counts are not evaluation results.
5. **Tests:** Final suite **872 passed**, zero failures, **53.94 seconds** (`.cache/tmp/p09_final_gate_tests.xml`): 804 original plus 68 P09 tests. Official v1/v2 plans remain byte-identical to the pre-D100 invented references. Overlay privacy/caps, app behavior, export, generated README, redaction, review exclusion and package tests pass. Every pytest invocation used fresh basetemp/cache_dir paths under `.cache/tmp`, with TEMP/TMP there. `.cache/pytest-tmp` was untouched.
6. **Frozen files:** All 16 HASHES rows, including the duplicate, and seals verify. All **3,313 protected files** remain unchanged, as do all **36 D102 files**. No scoring code, results JSON, official output or frozen config/eval file was edited.
7. **Content:** No real dialogue, character names, speaker labels, transcript or rationale was copied into public source, tests, README, report, app export or commit scope. Only the explicitly authorized ignored package/review contains confidential transcript material; it was not printed. Tests use invented data.
8. **Secrets:** The assistant never opened/searched/printed `.env`. Existing application code loaded keys for authorized calls. The app reads only Streamlit secrets/environment. Secret examples list names only, and real secret/private-review files are guard-blocked.
9. **Calls/storage:** D104 used only remaining-stage Groq HTTP calls plus fresh preflight; upstream requests were cache-only. No paid model, dependency download, Cloud deployment, Drive upload or push occurred. Owned app temp cleanup is tested. Source artifacts and old attempts are preserved.
10. **Commit gate:** Package and ZIP verified; all-file guard clean (164 files), staged guard clean (26 files), staged whitespace clean, all 16 HASHES rows/seals verified, and protected-byte checks passed. Exactly **26 allowed files** are staged, with no unstaged changes: code/tests/free config/app/requirements/secret example/README/docs/tools/report and ignore rules only. Raw outputs, review, data, gold, workbooks, caches, `.env` and real secrets are excluded. HEAD remains `d159589`; no commit or push has been performed.
