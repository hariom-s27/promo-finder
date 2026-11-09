<!-- results-at-a-glance:start -->
**Results at a glance**
- Official held-out Recall@32: v1 3/16; baseline 6/16.
- Official negatives hit: v1 0/6; baseline 5/6.
- Fresh A, Recall@16: v2 2/8; v1 2/8.
- Fresh B, Recall@8: v2 1/4; v1 1/4.
- Held-out v2 Recall@32: 3/16 — post-hoc; [definitions and limits](docs/RESULTS.md).
<!-- results-at-a-glance:end -->

# Promo finder

## What it does

Reads a timestamped microdrama screenplay and finds ranked 20–60 second promos with a hook, a cliffhanger and enough context to stand alone. Results have launch-batch, reserve and needs-human lanes for editorial review. v1 is the default; v2 is an optional overlay (D99).

## Setup and one command

From the repository folder, using Python 3.11 or later:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:TEMP = Join-Path $PWD '.cache\tmp'
$env:TMP = $env:TEMP
python -m promo_finder run --eps 1-50 --run <name> --allow-held-out
```

Choose a new run name each time. `--allow-held-out` is optional for selections outside the original held-out episodes; the full selection above requires it. Add `--dry-run` to estimate calls and tokens without loading credentials or making requests.

Supply credentials locally through environment variables or an untracked `.env`. Key names only: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_ENDPOINT`, `GROQ_API_KEY`, `FEATHERLESS_API_KEY`. The default full run uses the Azure picker and Azure Foundry judge. Never commit credentials.

Set `KUKU_DATA_DIR` to the folder containing the episode files:

```text
<local-show-folder>/
  episode-001-Episode 1.txt
  episode-002-Episode 2.txt
  ...
```

Files use the input-pack timestamped scene/dialogue format, with UTF-8 text and speaker labels. For a **new show**, point `KUKU_DATA_DIR` at its folder and use a fresh run name. The understanding step rebuilds show-specific context; later stages reuse the same code and configuration with that context. No show-specific prompts or code edits are needed. Outputs stay under `outputs/runs/<name>/`.

## Swap a model by configuration

Current role lines in `config.yaml`:

```yaml
active:
  picker: azure_mini
  judge: azure_llama
```

Change the relevant role line to an existing model key. Picker and judge must have distinct, known families; the loader and judge refuse self-judging. The judge previously moved from Groq-Qwen to Azure-Llama through configuration (D71→D74). Changing model definitions is separate from selecting a role. The comparison baseline is frozen to the official picker; use the explicitly supported free demo below for the Groq pair.

## How it works

AI proposes line IDs. Code turns those IDs into timestamps and enforces 20–60 seconds, line-boundary cuts and chronological order. A different-family judge reads each clip cold. The frozen score formula ranks the clips; review gates assign launch-batch, reserve and needs-human lanes. Lane labels do not change evaluation order.

## Measured results

[Generated results, definitions and denominators](docs/RESULTS.md) cover official v1 versus baseline, separate fresh blocks A/B, and explicitly post-hoc held-out v2. Regenerate directly from the saved public JSON files:

```text
python tools/make_results_table.py
```

This renders existing results; it never scores labels or reruns an evaluation. Result numbers are maintained in the generated document.

## Cost and scale

The full 50-episode v1 run cost **USD 0.908**, took about **79 minutes** and used **551 logical calls** ([P07b](logs/P07b_report.md)). The v2 rerun cost **USD 0.259** with cache reuse ([P08b](logs/P08b_report.md)). These are reported-usage list-price costs; failed-request token usage was unreported.

The picker has no pacing yet: the full run recorded **130 HTTP 429 retries** (#54). Free tiers also have daily token limits (#45); a small episode count does not guarantee sufficient quota.

The free demo selects `groq_oss` (`openai/gpt-oss-120b`, family `openai`) and `groq_qwen` (family `alibaba`):

```text
python -m promo_finder run --eps 23-24 --run free_demo --config-overlay config/free.yaml --dry-run
```

**Free path = demo, not evaluation.** It skips the comparison baseline, uses singleton character batching (D100 a) and a free-only 4,500-token answer-key output cap (D104 a). Official v1/v2 settings, other caps, baseline and scoring behavior are unchanged. The app uses the same overlay. The supplied free limits are 30 RPM, 1,000 RPD, 8,000 TPM and 200,000 TPD per model. Inspect per-request and daily budgets before live use. No paid fallback is used.

The D104 a attempt completed episodes 23–24, keeping and scoring four promos, with USD 0 recorded cost and zero 429s. It reused seven upstream cache entries from the earlier D102 partial attempt; only remaining judging work made new substantive requests. Two schema-validation retries resolved without cap changes. The D102 failure is preserved; the completed attempt lives in `outputs/runs/free_demo_d104/`. This demonstrates a small cached free workflow, not full-show free capacity or evaluated free-model quality. See the [P09 report](logs/P09_report.md).

## Limits and where it picks badly

Read [P08](logs/P08_report.md) and [P08b](logs/P08b_report.md). Gold comes from one labeller who had read the show, with small samples and incomplete editorial coverage. Script time only approximates edit time. Eight of sixteen held-out gold clips were unreachable under the moment-boundary limit. The judge barely discriminates on some questions. The name guard also flags common label words (#59). Fresh B was selected for changed candidate sets and includes pilot-exposed episodes; it is not a random sample. More candidates did not establish better recall.

## Optional v2 overlay

```text
python -m promo_finder run --eps 1-50 --run <new-name> --allow-held-out --config-overlay config/v2.yaml
```

F2 extends eligible short clips to the first line boundary reaching the minimum duration. F5b retains earlier medium/high resolution with a penalty and human-review flag, while still dropping resolution at the end. Its end window is fixed. The generated results show **no measured fresh recall gain over v1**. v1 remains the default (D99).

## Confidentiality, app and local package

Scripts are supplied locally by the user; no real script data is included in this repository. Generated run files, gold labels, caches and credentials remain ignored. The decisions placeholder is in [docs/DECISIONS.md](docs/DECISIONS.md); Hariom supplies its content.

For the small app, install `requirements.txt`, then run:

```text
streamlit run app/streamlit_app.py
```

Both app tabs open without a passcode (D105 c):

- **Full results (Azure run):** five saved launch-batch cards, all ranked metadata, evaluation metrics, per-stage Azure usage and v2 rerun cost. A cost-at-scale box projects the P07b per-show cost and minutes to 150 shows/month, explicitly labelled as an assumption. The repository export contains timestamps, duration, type codes, score, lane and rank only; no transcript, explanations, speaker labels or names. Build it with `python tools/export_app_results.py`.
- **Try it live (free):** accepts one to three episodes, uses the Groq demo path, and keeps input/output/cache files in a temporary directory cleaned after processing. It sends uploaded text to Groq only when the user starts a run. The live table and JSON download remain in the active browser session.

Tab 1 works without a Groq key. If the key is missing or a quota/rate limit is reached, Tab 2 shows "free-tier limit reached, try later; full results are in Tab 1". The app reads keys only from Streamlit Secrets or the environment and never loads `.env`.

To deploy: Streamlit Cloud → New app → select repository and branch → `app/streamlit_app.py`. Choose Python 3.11 or later; enter `GROQ_API_KEY` in Cloud Secrets. `.streamlit/secrets.toml.example` lists the name only; the real `secrets.toml` is ignored and guard-blocked. Deployment is performed by Hariom; no push or deployment is performed by this task.

Build the local confidential handoff from the completed free attempt:

```text
python tools/package_outputs.py --free-run free_demo_d104
```

It creates `outputs/package/kuku_promo_finder_raw_outputs/` and a ZIP, excludes LLM caches, and exports AI labels with the rationale column removed. The package also contains `review/top_promos_by_episode.md`: up to three saved top promos per episode with judge answers and confidential transcripts, for Drive-only review. The original partial free attempt is preserved separately. The tool never overwrites an existing package and prints counts/sizes only. Keep both artifacts private and outside commits; the transcript-review filename is ignored and guard-blocked everywhere.
