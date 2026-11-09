# P09c report: live tab uses Azure with a daily cap (D106 a)

9 November 2026. Starting HEAD `e46a1cf`. Stopped at the commit gate.

## Plain summary

Tab 2, now named **Try it live**, runs the official Azure pair from `config.yaml`, the `azure_mini` picker and the `azure_llama` judge, instead of the Groq free overlay. It still takes one to three episodes, works in a temporary tree that is deleted afterwards, and skips the comparison baseline because it is a demo, not an evaluation. A hard global cap of **30 episodes per UTC day** now applies; past it the tab shows "daily demo cap reached; full results are in Tab 1". Tab 1 is unchanged.

`config/free.yaml`, the CLI free path and the README's free-path section are unchanged. The README cites the completed `free_demo_d104` run as the free version and now says the app no longer uses it.

## What changed

- **Keys:** the four Azure names (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_ENDPOINT`) are read only from Streamlit secrets or the environment and stay in memory. They are handed to the client factory as a mapping (`default_client_factory` gained an optional `env` argument; with no argument it reads the process environment exactly as before). Nothing is written to the environment or to disk, and `.env` is never loaded. Error text is scrubbed of the four values. A missing key gives a friendly note naming the missing secret names, never values; `.streamlit/secrets.toml.example` lists the four names only.
- **Foundry gate kept:** the pipeline refuses to judge on Foundry without a successful judge-shape ping. The demo performs that ping inside its temporary tree (same record as the CLI ping), so the gate is satisfied, not bypassed. It adds at most five requests beyond the run budget, usually one.
- **Baseline skip:** `Config.baseline_skipped` is true for the free demo or the app demo. The pipeline uses it for the stage list, the baseline plan and the final snap/check. Official runs are unchanged: the official plan byte-identity test still passes.
- **Daily cap:** an in-process counter, reserved before any provider call, checked against the UTC date, and never refunded (the cap bounds spend, not successes). Invalid uploads and missing keys do not consume it. At the P07b rate (about USD 0.018 per episode, a list-price estimate) the cap bounds spend near USD 0.55 per UTC day per server process.
- **Friendly outcomes:** cap reached, missing keys, and rate-limit or quota refusals (any HTTP 429 form) show a note, not an error box. Other failures show a content-free error code.

## Limits to know

- **Not exercised live.** The Azure live path was verified offline only: a fake provider ran the real pipeline end to end (ping, picker, judge, ranking) and a mutation check that removed the ping made three end-to-end tests fail. No Azure call was made. Run one small upload after deployment to confirm the live keys and deployments.
- The counter lives in one process. A restart, or Streamlit Cloud putting the app to sleep, resets it, so it is a guard against runaway use, not a durable budget.
- There is no run lock. Two simultaneous runs each have their own rate limiter, so they can exceed the Foundry deployment's per-minute quota together; the result is a 429, shown as the friendly note.
- The shell this work ran in already defines some Azure variables in its environment (the offline smoke's "no keys" case reported only two names missing). The app falls back to the environment by design, so a local `streamlit run` on this machine would make real Azure calls when **Find promos** is clicked. Values were never read, printed or logged.

## Verification

- **894 tests passed** (873 at P09b), zero failures, 47.53 s, recorded in `.cache/tmp/p09c_d106a_tests.xml`. Every pytest invocation used a fresh basetemp and cache_dir under `.cache/tmp`, with TEMP/TMP set there. Sockets are blocked in the new tests.
- New tests (`tests/test_demo_azure.py`, `tests/test_streamlit_app.py`): the cap (30, atomic refusal, UTC rollover and offset, exact message, enforced by `run_uploads`, failed runs still count); each missing key; keys read from the mapping and not the environment; official config and roles unchanged with the family check passing; the free overlay path unchanged; an Azure-only dry-run plan without a baseline; a full fake-provider run with cleanup; a rate-limited run becoming the friendly note; the upload cap; temporary-tree cleanup on success and failure.
- Two tests in `tests/test_free_path.py` used the app's `prepare()` as a shortcut to the free configuration. Now that `prepare()` is Azure, they build the free configuration through a local helper with the same assertions, so the CLI free path stays covered.
- Offline AppTest (system Python with the venv's packages, because the venv lacks Streamlit), sockets disabled, invented secrets: zero exceptions in all three scenarios, both tab labels correct, the missing-key note, the live caption showing the cap (30 left), and the cap-exhausted note. Evidence: `.cache/tmp/p09c_d106a_smoke.json`.
- All 16 HASHES rows verify. No file under `outputs/`, `eval/` or `config/` changed since HEAD. No scoring code, result, official output or frozen file was edited.
- Guards: staged mode clean (10 files before this report), all-file mode clean (167 files), staged whitespace check clean.

No live AI call, network call, package rebuild, commit or push occurred. The real secrets file was never opened, searched or printed.

Pending commit message: `P09c: live tab uses Azure with daily cap (D106 a)`.
