# P01 report: skeleton, parser, checker, LLM wrapper

PLAIN SUMMARY
- What happened: The foundation is built and tested. All 50 real episodes parse with no errors (3,727 lines, 100 scenes). 78 of 78 unit tests pass. The leak guard is clean. All four non-TBD models answer the ping: groq_oss (`openai/gpt-oss-120b`), groq_qwen (`qwen/qwen3.8-27b`), azure_mini (`gpt-5-mini-2025-08-07`) and azure_strong (`gpt-5.4-2026-03-05`). Both Azure deployments work on the v1 path. The first ping returned HTTP 401 for Azure. Hariom fixed the key in `.env` and re-ran the ping, and both Azure models then passed.
- What it means: The parser, checker and wrapper are ready for P02 (moment finder). The configured pair, picker azure_mini (openai family) and judge groq_qwen (alibaba family), works as set in `config.yaml`, with no change needed.
- Problems: (1) Solved: the Azure 401 came from a bad key. It was fixed by Hariom; no code or config change. (2) The format note said "2 scenes per episode". In the real files it is 1 to 5 per episode (still 100 in total). The parser assumes no fixed number.
- Decision needed (options + your pick): None for P01. For P02, the open question is how to choose the featherless_judge model (still TBD). My pick: keep groq_qwen as judge until P02 has an eval set to compare judges on.
- Exact next message for Hariom to send to the chat:
  `P01 committed. Start P02 (moment finder) using picker azure_mini and judge groq_qwen.`

SELF-AUDIT

## 1. Steps done
| Part | Status | Evidence |
|---|---|---|
| 0 Location check | done | Workspace folders listed: the scripts folder and `promo-finder`. data_dir set in `config.yaml`. 50 `episode-*.txt` found recursively (one subfolder deep). |
| A Skeleton and safety | done | All files listed below. `.venv` created with `python -m venv .venv`; requirements and `-e .` installed only in the venv. `.gitignore` covers data/, outputs/, .cache/, .venv/, .env, *.env, __pycache__/, *.pyc, .pytest_cache/, *.egg-info/. `tools/guard.py` gives exit 0 (clean). |
| B Parser and validator | done | `python -m promo_finder parse` wrote `outputs/parsed/E01..E50.json` and `outputs/parse_report.json`. `tests/test_parser.py` 27 passed (including the integration test on real data). |
| C Timestamp checker | done | `src/promo_finder/checker.py`. `tests/test_checker.py` 17 passed: every error code, the 20.000/60.000 pass cases, the 19.999/60.001 fail cases, a 2-episode promo, snapping. |
| D LLM wrapper and ping | done | `src/promo_finder/llm.py`. `tests/test_llm.py` 25 passed. Live ping: 4 of 4 ok after the Azure key fix (see section 8). Groq `/models` checked. |
| E Report and commit | done | This file. `pytest` 78 passed, `parse` ok, `guard` clean (staged). Committed as "P01: skeleton, parser, checker, LLM wrapper" (approved by Hariom). Not pushed. |

## 2. Decisions I made that the prompt did not specify
| What | Why | Alternative |
|---|---|---|
| Guard skips 8-word windows that contain a timestamp or consist only of layout words (script markers, scene field labels, `INT.`/`EXT.`, numbers, `|`). **Accepted by Hariom.** | Every invented fixture shares the layout line `--- SCRIPT START --- / SCENE 01 / Scene heading: INT.` with the real files. Without the skip, all 8 fixtures were false hits. Real leaks always contain story words, so they are still caught: scanning a real episode against the set gave 81 hit lines. | Exempt `tests/fixtures/` entirely (weaker), or add an allow-list file. |
| Line IDs count per episode across scenes (`E07-L042` = 42nd block in that file). Scene times are kept on Scene only. **Confirmed by Hariom.** | Stable, simple, and the same as the prompt's example. | Per-scene numbering. |
| Malformed blocks get no line index. Indexes stay consecutive over accepted lines. | The checker range logic relies on consecutive indexes. | Reserve an index for skipped blocks (that would create gaps). |
| Extra checker code `BAD_SEGMENT_TIME` (the last line of a span ends at or before the first line starts). | That segment would have zero or negative length. It cannot happen with the real data, but it must never pass. | Fold it into TOO_SHORT. |
| TOO_SHORT/TOO_LONG are only checked when every span resolved. | A partial total after an UNKNOWN_ID span would only add noise. | Always check. |
| Overlap/gap counting uses time-sorted lines. A "gap" is time that no earlier line covers (running max end). | Camera and action lines overlap dialogue by design, so a file-order gap would count false gaps. | Plain consecutive-pair gap in file order. |
| `snap_to_lines` move values are signed (start moved ≤ 0 = earlier, end moved ≥ 0 = later). If the end is past the last line it clamps to the last line. | Keeps the direction information for baseline scoring. | Absolute values. |
| `load_secrets` exits only if the secrets file is missing **and** some keys are not already in the environment. | Lets CI or a shell provide keys without a file. | Always exit when the file is missing. |
| Parameters the OpenAI SDK does not know (e.g. `include_reasoning`) are sent in `extra_body`. Temperature is stripped for every `family: openai` model. | The SDK rejects unknown keyword arguments. | Hard-code per provider. |
| Azure: if v1 fails, the fallback is tried; whichever path works is remembered per run. Every request (including the fallback) counts toward the budget. 429/5xx backoff retries do not count again. | A conservative budget; the log shows which path worked. | Count backoff retries too. |
| The call log records one line per HTTP request (including retries and cache hits), plus `azure_path` event lines. | Cost tracking per real request. | One line per `call()`. |
| Ping results are also saved to `outputs/ping_results.json` (git-ignored). | Evidence for this report. | Console only. |
| pytest temp dir, pip cache, TMP and the tiktoken cache all point to `promo-finder/.cache/`. | The "write only inside promo-finder" rule. | Default system temp. |
| Episode also stores `header_ep`, `continuity`, `warnings`; Line also stores `src_line`. | Needed for warnings and later prompts. | Leave them out. |

## 3. Deviations from the prompt
- Before Gate A, during the read-only format scan, I wrote one throw-away scan script (counts only, no script text) to the session scratch folder outside promo-finder. It was not written into the project. From then on, everything stayed inside promo-finder.
- `tiktoken` downloaded its `o200k_base` vocabulary file once (a free, non-LLM network fetch) into `.cache/tiktoken`, during `ping --dry-run`.
- `pip install -e .` was used (approved). This needs setuptools in an isolated build environment (fetched by pip) and creates `src/promo_finder.egg-info/` (git-ignored).
- openai resolved to **3.46.0**, which pulls in `httpx2` as a transitive dependency. It was not added by me, and every API the wrapper uses is present.

## 4. Numbers
| Number | Value | Source |
|---|---|---|
| Episode files found | 50 | Part 0 scan / `outputs/parse_report.json` totals.episodes |
| Scenes | 100 (per episode: 1×25 eps, 2×9, 3×9, 4×5, 5×2) | `outputs/parse_report.json` |
| Lines | 3,727 (dialogue 1,487 · camera 1,754 · action 372 · sfx 114 · other 0) | `outputs/parse_report.json` totals.lines_by_kind |
| Lines per episode | min 37, max 121 | `outputs/parse_report.json` episodes.*.lines |
| Total duration | 6,162,620 ms (≈ 102.7 min); per episode 70,500 to 200,750 ms | `outputs/parse_report.json` |
| Distinct speakers (count only) | 64 | `outputs/parse_report.json` totals.distinct_speakers |
| Lines with `ext` filled (double bracket) | 56 | `outputs/parsed/*.json` |
| SFX lines with bracketed text | 4 | `outputs/parsed/*.json` |
| Dialogue lines without emotion | 0 | `outputs/parsed/*.json` |
| Parse warnings | OUT_OF_SCENE 1; no file-level warnings | `outputs/parse_report.json` |
| Validator | start≥end 0 · backwards starts 8 · overlaps 2,400 · gaps > 2 s 0 · out of scene 1 | `outputs/parse_report.json` totals.validator |
| Guard shingles from data_dir | 33,928 | guard self-check |
| Tests | 78 passed, 0 failed, 0 skipped | `pytest -q` |
| LLM requests | 8 real in total: ping 1 = 6 (2 Groq ok, 4 Azure 401); ping 2 = 2 (Azure ok) plus 2 Groq cache hits | `outputs/logs/llm_calls.jsonl`, `outputs/ping_results.json` |

## 5. Tests
| File | Passed | Failed | Skipped |
|---|---|---|---|
| tests/test_parser.py (includes integration) | 27 | 0 | 0 |
| tests/test_checker.py | 17 | 0 | 0 |
| tests/test_llm.py | 25 | 0 | 0 |
| tests/test_guard.py | 9 | 0 | 0 |
| **Total** | **78** | **0** | **0** |

Integration output (counts only): `episodes=50 lines=3727 scenes=100 file_warnings=0 start_ge_end_flagged=0`.

## 6. Format check: "Known format" note vs real files
| Claim | Result |
|---|---|
| 50 files `episode-NNN-Episode <id>.txt`; filename number = header number in all 50 | matches (0 mismatches) |
| Header: episode number, logline, continuity notes; then SCRIPT START … SCRIPT END | matches (nothing after SCRIPT END in any file) |
| **2 scenes per episode** | **does not match.** 100 scenes in total, but per episode: 25 episodes have 1, 9 have 2, 9 have 3, 5 have 4, 2 have 5. |
| 3,727 blocks: label, Start/End line, exactly one text line | matches (every block has exactly 1 text line) |
| Episode 6 uses ALL-CAPS scene field labels | matches (only episode 6) |
| 56 speakers with two bracket groups | matches. Every other speaker label has exactly one group (the emotion). |
| 4 SFX blocks with bracketed text | matches |
| Times are mm:ss.ss | matches (all 7,454 block times) |
| Not in note | UTF-8, LF line endings, no BOM; files sit one subfolder below data_dir |

## 7. Safety
- `.env`: never opened, read, printed or searched by me. It was loaded only by our code (`load_secrets`, python-dotenv, override=True) during `ping --dry-run`, `ping`, and one shape check. That check printed only the URL scheme/host suffix/path and the key's length and character class, never a value. Hariom edited the Azure key and ran the second ping; I did not touch `.env`.
- No key value was printed or logged. Error messages pass through a scrubber that replaces any secret value with `***`; `tests/test_llm.py::test_error_message_scrubs_key` covers it. The call log holds a sha256 of the prompt, not the prompt.
- `tools/guard.py`: clean on the 32 staged files (staged mode). It is installed as `.git/hooks/pre-commit`, using the venv python, and blocks the commit if the venv is missing. It never opens `.env` files, prints only `path:line`, and fails closed (exit 2) if data_dir is missing.
- No script text, dialogue or character names are in any created file. Fixtures are invented (a made-up lighthouse story). Reports and logs contain only counts and line IDs. The only reference to the series is the data_dir folder path in `config.yaml`, as the prompt requires.
- Git repo is promo-finder only. Nothing pushed, no remote.

## 8. LLM calls
Current results (`outputs/ping_results.json`, second ping, after the Azure key fix):

| Model key | Result | Model string | Tokens in/out | Latency | Path | Cached |
|---|---|---|---|---|---|---|
| groq_oss | ok (`{"ok": true}`) | `openai/gpt-oss-120b` | 113 / 32 | 1,167 ms (live, first ping) | – | yes (cache hit) |
| groq_qwen | ok (`{"ok": true}`) | `qwen/qwen3.8-27b` | 20 / 6 | 144 ms (live, first ping) | – | yes (cache hit) |
| azure_mini | ok (`{"ok": true}`) | `gpt-5-mini-2025-08-07` | 39 / 17 | 2,446 ms | **v1** | no |
| azure_strong | ok (`{"ok": true}`) | `gpt-5.4-2026-03-05` | 39 / 11 | 1,009 ms | **v1** | no |
| featherless_judge | skipped (TBD) | – | – | – | – | – |

History (`outputs/logs/llm_calls.jsonl`):
- Ping 1: 6 real requests. Groq 2 ok; Azure mini and strong each HTTP 401 on v1, then 401 on the fallback.
- Ping 2 (run by Hariom after the key fix): 2 real requests (Azure, both v1 ok; log event `azure path in use: v1`) and 2 Groq cache hits.
- Totals: 8 real requests, 2 cache hits. Most real requests in one run: 6 of 50.

The Azure fallback path (`AzureOpenAI`, api_version `2025-04-01-preview`) has not yet been seen to succeed live. It is covered by `tests/test_llm.py::test_azure_falls_back_once`.

## 9. Risks and open items for P02
1. **featherless_judge** is still TBD. It is skipped everywhere until a model is chosen.
2. **Overlapping lines:** in a span (first..last), segment time is first.start → last.end, as the prompt specifies. A middle camera line can run past the last line's end, so the clip may cut a shot early. P02 may want "end = max end of covered lines". That needs a decision because it changes the checker contract.
3. **The 8 backwards starts** are small (100 to 1,000 ms), all within one scene, mostly a camera line followed by a dialogue line. With the (episode, start) ordering rule, a promo whose 2nd segment starts on one of those lines could be judged OUT_OF_ORDER against a segment that ends just before it. This is rare and only matters for adjacent segments.
4. **E22-L023** ends 300 ms after its scene's end. It is harmless, but a promo spanning the scene boundary will include it.
5. **Strict json_schema support** differs by provider/model (qwen on Groq accepted it for the tiny schema). Larger P02 schemas should be tested with `--dry-run` first, then one live call.
6. **The Groq tpm limit (8,000)** is low for long prompts. The limiter waits rather than failing, so P02 batch runs on Groq will be slow.
7. **The guard layout-word list** is tuned to this screenplay format. If a new format appears, revisit `FORMAT_WORDS`.
8. The pre-commit hook lives in `.git/hooks/`, which git does not version. A fresh clone needs it installed again.

---

## Evidence

### File list (created, committed candidates)
```
.gitignore  README.md  config.yaml  pyproject.toml  requirements.txt
eval/.gitkeep  logs/.gitkeep  logs/P01_report.md  prompts/.gitkeep
src/promo_finder/__init__.py  __main__.py  checker.py  cli.py  config.py  llm.py  models.py  parser.py  validate.py
tests/conftest.py  test_checker.py  test_guard.py  test_llm.py  test_parser.py
tests/fixtures/normal/episode-001-Episode 9000001.txt  episode-002-Episode 9000002.txt
tests/fixtures/edge/episode-010-Episode 9000010.txt (filename/header mismatch)
tests/fixtures/edge/episode-021-… (multi-line)  -022-… (odd times)  -023-… (broken block)
tests/fixtures/edge/episode-024-… (ALL-CAPS labels)  -025-… (double bracket)
tools/guard.py
```
Git-ignored, created at run time: `.venv/`, `.cache/` (llm, pip, pytest-tmp, tiktoken, tmp), `outputs/` (parsed/, parse_report.json, ping_results.json, logs/llm_calls.jsonl), `src/promo_finder.egg-info/`, `.pytest_cache/`.

### Parse totals (`outputs/parse_report.json`)
```
episodes=50  scenes=100  lines=3727  total_duration_ms=6162620  distinct_speakers=64
lines_by_kind: dialogue 1487, action 372, camera 1754, sfx 114, other 0
warnings_by_code: OUT_OF_SCENE 1
file_warnings_by_code: (none)
```

### Validator counts
```
start_ge_end: 0
backwards_starts: 8
  E04-L110 (after E04-L109)  back 500 ms
  E12-L022 (after E12-L021)  back 1000 ms
  E20-L041 (after E20-L040)  back 100 ms
  E21-L012 (after E21-L011)  back 100 ms
  E21-L022 (after E21-L021)  back 100 ms
  E32-L027 (after E32-L026)  back 300 ms
  E32-L034 (after E32-L033)  back 100 ms
  E46-L052 (after E46-L051)  back 300 ms
overlaps_total: 2400
  camera+dialogue 1548, action+camera 383, action+dialogue 210, camera+sfx 145, action+sfx 60,
  dialogue+sfx 34, dialogue+dialogue 10, camera+camera 5, action+action 4, sfx+sfx 1
gaps_over_2s: 0
out_of_scene: 1
  E22-L023: line 41,500–42,800 ms; scene 1 bounds 0–42,500 ms (ends 300 ms late)
```

### Ping results
```
(second ping, outputs/ping_results.json)
groq_oss      ok  model_string=openai/gpt-oss-120b    in=113 out=32  cached=true
groq_qwen     ok  model_string=qwen/qwen3.8-27b       in=20  out=6   cached=true
azure_mini    ok  model_string=gpt-5-mini-2025-08-07  in=39  out=17  latency=2446ms  api_path=v1
azure_strong  ok  model_string=gpt-5.4-2026-03-05     in=39  out=11  latency=1009ms  api_path=v1
featherless_judge skipped (TBD)
groq /models (11): allam-2-7b, canopylabs/orpheus-arabic-saudi, canopylabs/orpheus-v1-english,
  meta-llama/llama-prompt-guard-2-22m, meta-llama/llama-prompt-guard-2-86m, openai/gpt-oss-120b,
  openai/gpt-oss-20b, openai/gpt-oss-safeguard-20b, qwen/qwen3.8-27b, whisper-large-v3, whisper-large-v3-turbo
  qwen/qwen3.8-27b: PRESENT    openai/gpt-oss-120b: PRESENT
real requests made: 2 (second ping); first ping: 6 (Azure 401 on v1 and on the fallback)
```

### Guard output
```
guard: clean (32 files checked, mode=staged)
```
(Self-check: scanning one real episode against the data shingle set flagged 81 lines, so detection works.)
