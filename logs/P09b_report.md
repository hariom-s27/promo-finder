# P09b report: app open without a passcode (D105 c)

9 November 2026. Starting HEAD `bb5c537`. Stopped at the commit gate.

Both tabs now open without authentication. The obsolete gate and comparison helper were removed. Saved Azure results render independently of credentials. The live tab retains the one-to-three episode cap, input validation and owned temporary-tree cleanup.

Missing Groq credentials, SDK HTTP 429 responses, wrapped rate-limit errors and daily-quota refusals produce this fixed public message: "free-tier limit reached, try later; full results are in Tab 1". Provider exception text is inspected only in memory for classification and is never displayed or logged. Other validation errors retain their existing content-free messages. No model, cap, quota, scoring or pipeline behavior was changed.

The secret-name example and README now require only the Groq key for live use. Tests cover both tabs without authentication, missing credentials, the upload cap, five quota/rate-limit error forms, and cleanup after failures. The report records the final D105 c implementation; no earlier access-gate behavior is retained.

Verification: **873 tests passed**, zero failures, **43.91 seconds**, recorded in `.cache/tmp/p09b_d105c_tests.xml`. Every pytest invocation used a fresh basetemp and cache_dir under `.cache/tmp`, with TEMP/TMP set there. `.cache/pytest-tmp` was untouched. Offline AppTest rendered both tabs, three saved-results tables and five launch cards with no authentication widgets; missing-key mode showed the friendly fallback and configured-key mode exposed the uploader. Socket connections were disabled. Smoke evidence: `.cache/tmp/p09b_d105c_smoke.json`.

All-file/staged guards, staged whitespace, sealed-input verification and protected-file checks pass. Six changed files are staged: app, demo error handling, tests, README, secret-name example and this required project report. Official outputs, frozen files, cached/live-run artifacts, the private transcript review and the package remain unchanged. The real secrets file was never opened, searched or printed. No network/AI calls, package rebuild, commit or push occurred.

Pending commit message: `P09b: app open without passcode (D105 c)`.
