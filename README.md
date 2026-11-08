# promo-finder

Reads a timestamped microdrama screenplay (one plain-text file per episode) and, in later
phases, proposes 20–60 second promo clips.

**Core rule:** the LLM may only point at line IDs (`E07-L042`). Code turns line IDs into
timestamps and enforces every rule, so a model-invented timestamp can never reach the output.

## Setup (Windows)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
```

Keys live in `.env` (never committed). Override the path with `KUKU_SECRETS_FILE`.
Override the scripts folder with `KUKU_DATA_DIR`.

## Commands

```
.venv\Scripts\python -m promo_finder parse            # -> outputs/parsed/E##.json, outputs/parse_report.json
.venv\Scripts\python -m promo_finder ping --dry-run   # list planned calls, no network
.venv\Scripts\python -m promo_finder ping             # one tiny call per configured model
.venv\Scripts\python -m pytest -q
.venv\Scripts\python tools/guard.py                   # leak guard; run before every commit
```

## Layout

- `src/promo_finder/parser.py`: screenplay to `Episode`/`Scene`/`Line`
- `src/promo_finder/validate.py`: timing sanity counts (warnings only)
- `src/promo_finder/checker.py`: line-ID spans to checked segments (the safety core)
- `src/promo_finder/llm.py`: one wrapper for Groq / Azure / Featherless with cache, pacing, budget
- `tools/guard.py`: blocks secrets, outputs and copied script text from commits
# P05 DEV judging and ranking

Use the project virtual environment. Set TEMP and TMP to the project `.cache/tmp`
directory. Archive P03 and compute offline ablations before rebuilding:

```powershell
.\.venv\Scripts\python.exe tools/p05_offline.py --eps 5-8,19-22
.\.venv\Scripts\python.exe -m promo_finder build --eps 5-8,19-22
.\.venv\Scripts\python.exe -m promo_finder ping --models groq_qwen,featherless_llama --no-cache --fail-fast
.\.venv\Scripts\python.exe -m promo_finder judge --eps 5-8,19-22 --dry-run
```

Stop for approval of the dry-run budget before live answer-key or judge calls.
After approval, run `judge --eps 5-8,19-22`, then `rank --eps 5-8,19-22`.
`judge --no-cache` bypasses saved responses. Judge/rank refuse held-out selections
with `HELD_OUT_REFUSED`; do not use the override during DEV work.

The cold judge sees clip-local evidence IDs. Code validates and maps them to real
IDs afterward. Failed runs do not enter aggregates. A repeated item's flip rate is
the fraction of five yes/no questions with disagreement; the review threshold is
0.4. Per-question rates across repeated items measure reliability separately.
References use the archived P03 spans and do not enter the ranking pool.

`config/score_formula.yaml` defines official, equal-weight and no-funnel scores.
Only the official score selects the launch batch. Generated transcripts and AI
answers stay under ignored `outputs/`. See `docs/feedback_schema.md` for the
feedback CSV design. No feedback learner is implemented.
