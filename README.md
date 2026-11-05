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
