# P01b report: frozen eval files, hashes, list-lines, check-gold

PLAIN SUMMARY
- What happened: The match rule, gold rubric and gold template were copied byte for byte from `h1_source/` into `eval/`. All three sha256 values match the approved table, both on disk and as staged blobs, and Git stores them with LF endings. `eval/HASHES.md` records them. Four other things were built and tested: `list-lines` (labelling aid), `check-gold` (label sheet checker), `set_tiou` (overlap measure, reused at P08) and `tools/hash_eval.py`. Tests went from 78 to 150 passed, 0 failed. Everything is staged and not committed.
- What it means: The marking scheme and labelling rules are sealed before any label exists. Hariom can start labelling: run `list-lines`, fill `eval/gold.csv`, then run `check-gold`.
- Problems: None blocking. Under autocrlf=true, Git prints "LF will be replaced by CRLF" for non-eval files. This is harmless: the index stores LF, and eval/** is forced to LF by `.gitattributes`.
- Decision needed (options + your pick): Commit or not. (a) Commit as staged (my pick). (b) Ask for changes first.
- Exact next message for Hariom to send to the chat: `APPROVED - commit P01b`

SELF-AUDIT

## 1. Steps done
| Step | Status | Evidence |
|---|---|---|
| Step 0 repo check | done | git status clean, HEAD 9879fa0, pytest 78 passed, core.autocrlf=true (plan message) |
| A1 .gitattributes | done | `.gitattributes` = `eval/** text eol=lf\n` (20 bytes, checked with `od -c`) |
| A2 three eval files | done | copied with `read_bytes` -> `write_bytes` from `D:\sem_iitk\sem9\kuku\h1_source\` (approved answer Q1); nothing written in h1_source |
| A3 byte check | done | disk and staged sha256 equal the table (section 6) |
| A4 keep gold out of git | done | `.gitignore` lines 6-8; `tools/guard.py` `BLOCKED_GLOBS`; test `test_gold_label_files_blocked_but_template_allowed`; `git check-ignore` confirms gold.csv and gold_v2.csv are ignored and the template is not |
| B list-lines | done | `src/promo_finder/labelling.py`, `cli.py` `cmd_list_lines`, `tests/test_list_lines.py` (8 tests); real run: 16 files |
| C1 set_tiou | done | `src/promo_finder/tiou.py`, `tests/test_tiou.py` (9 tests, including the DR09 examples 0.72 and 0.718) |
| C2 check-gold | done | `src/promo_finder/gold.py`, `cli.py` `cmd_check_gold`, `tests/test_gold.py` (47 tests); template run prints `0 rows`, rc=0 |
| D1 hash_eval.py | done | `tools/hash_eval.py`, `tests/test_hash_eval.py` (7 tests); `init` wrote `eval/HASHES.md` |
| D2 staged check | done | `git ls-files --eol eval/` and staged-blob hashes (section 6) |
| E tests, guard, runs, report, staging | done | this file; `git add -A` run; NOT committed |

## 2. Decisions I made that the prompt did not specify
| What | Why | Alternative |
|---|---|---|
| Error code names: BAD_COLUMNS, MISSING_ID, DUP_ID, BAD_KIND, BAD_GRADE, BAD_HOOK, BAD_CLIFF, BAD_NEG_CODE, MISSING_SEG1, SEG_GAP, INCOMPLETE_SEG, NOT_HELD_OUT, EP_SKIP, POS_OVERLAP(other_id), EMPTY_RATIONALE, RATIONALE_TOO_LONG, NAME_IN_RATIONALE, plus file-level BAD_HEADER. The check_promo codes pass through unchanged. | Needed names for each rule; each has a test | Other names |
| A positive's hook/cliff code on a neg row is reported as BAD_HOOK / BAD_CLIFF; a neg_code on a pos row as BAD_NEG_CODE | Fewer codes, still precise | Separate codes |
| check_promo runs only when the segment structure is complete (no INCOMPLETE_SEG / MISSING_SEG1 / SEG_GAP) | Avoids noise like TOO_SHORT after a half-filled pair | Always run it |
| DUP_ID marks every row that shares the id | Both rows need fixing | Mark only later rows |
| POS_OVERLAP is checked for every positive whose spans are valid, even if another field (e.g. rationale) has an error. It is marked on both rows and names the other gold_id. | Overlap is about spans only | Only fully clean rows |
| Name guard: a full speaker label that is itself a skip word (a one-word label like the role word "guard") is also skipped. Words are split on letters only. | Matches the intent of the approved skip list | Match full labels always |
| A row's block = the block of its first segment's episode; rows with no readable held-out episode are counted under "other" | A crossing promo needs one block | Count it in both |
| Times are rounded to the nearest 0.1 s (half up) before formatting | Never shows `00:60.0` | Truncate |
| A `--- scene N ---` row goes before the first line of every scene, scene 1 included | Shows where every scene starts | Only from scene 2 |
| list-lines writes files with LF (`write_bytes`); missing requested episodes go to stderr as numbers | Plain, script-free output | - |
| check-gold prints a WARNING when the sheet has a BOM or CRLF (hash_eval add would refuse it later) | Catches the problem early | Silent |
| `hash_eval init` refuses to overwrite an existing `eval/HASHES.md`; `add` refuses if HASHES.md is missing, has CRLF, or the file is outside the repo; `add --note` is optional, and for `eval/gold.csv` / `eval/gold_v*.csv` the default note is "gold labels, hash only (file committed at P08)" | The seal must not be rewritten by accident | Allow overwrite |
| `check-gold` and `list-lines` take `--data-dir` (like `parse`) and parse data_dir live | Approved Q5; tests point them at the fixtures | - |

## 3. Deviations from the prompt
- The eval files were copied from `h1_source/` instead of written from the prompt text. Approved answer to Q1: the pasted text had lost its Markdown, so the match_rule hash could not be reproduced from it.
- No other deviations.

## 4. Numbers
| Number | Source |
|---|---|
| match_rule.md 4423 bytes, gold_rubric.md 4531, gold_template.csv 119 | `tools/hash_eval.py init` output; `eval/HASHES.md` |
| tests 78 -> 150 (72 new) | pytest runs (section 5) |
| list-lines: 16 files, 1231 table rows, 27 scene markers | `python -m promo_finder list-lines` console output (section 9) |
| 50 episodes parsed, 64 distinct speaker labels, 107 name-guard patterns | in-memory count only (names not printed) |
| guard: 17 staged files checked, clean | `python tools/guard.py` (before this report was staged; re-run at the gate) |

## 5. Tests
| File | Count |
|---|---|
| tests/test_checker.py | 17 (unchanged) |
| tests/test_parser.py | 27 (unchanged) |
| tests/test_llm.py | 25 (unchanged) |
| tests/test_guard.py | 10 (was 9, +1) |
| tests/test_tiou.py | 9 (new) |
| tests/test_list_lines.py | 8 (new) |
| tests/test_gold.py | 47 (new) |
| tests/test_hash_eval.py | 7 (new) |
| **Total** | **150 passed, 0 failed** (before: 78) |

## 6. Frozen items
| File | Expected (A3) | On disk | Staged blob | Bytes |
|---|---|---|---|---|
| eval/match_rule.md | d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2 | same | same | 4423 |
| eval/gold_rubric.md | 6f7b5161a66d857e913e5f73715f6b36c129d4cd57b69cd7d618e2b53f5550c0 | same | same | 4531 |
| eval/gold_template.csv | bb794d8a826bbc62288c30d16010e162c647ae5bdd19673dc22ebaf422bd8391 | same | same | 119 |

Source files in `h1_source/`: LF, no BOM, the same hashes. None of the three has been edited since the copy.

`git ls-files --eol eval/`:
```
i/none  w/none  attr/text eol=lf      	eval/.gitkeep
i/lf    w/lf    attr/text eol=lf      	eval/HASHES.md
i/lf    w/lf    attr/text eol=lf      	eval/gold_rubric.md
i/lf    w/lf    attr/text eol=lf      	eval/gold_template.csv
i/lf    w/lf    attr/text eol=lf      	eval/match_rule.md
```
Line-ID format is untouched: `models.line_id` was not changed, and the check-gold regex is `^E(\d{2})-L(\d{3})$`.

## 7. Held-out seal
- No tool or baseline output exists for any episode. `outputs/` holds only `parsed/`, `parse_report.json`, `ping_results.json`, `logs/` (from P01) and the new `labelling/`.
- The 16 `outputs/labelling/E##_lines.md` files were never opened, read or printed. Their names and row counts come from the command's own console output.
- No `eval/gold.csv` exists.

## 8. Safety
- No push, no new remote (origin already existed from before P01b and was not touched).
- No `.env` file was opened, read or searched. No keys were printed.
- `python tools/guard.py` (staged mode) is clean. The guard now also blocks `eval/gold.csv` and `eval/gold_v*.csv`.
- No script text, dialogue or character names appear in any created file, console output, this report or the commit message. Test fixtures and names are invented.
- Nothing was written outside `promo-finder/` (h1_source was only read). No new dependencies.

## 9. LLM calls
0. No LLM or network code was touched or run.

list-lines evidence (console output):
```
outputs/labelling/E01_lines.md rows=95 scenes=1
outputs/labelling/E02_lines.md rows=74 scenes=1
outputs/labelling/E03_lines.md rows=118 scenes=3
outputs/labelling/E04_lines.md rows=110 scenes=1
outputs/labelling/E11_lines.md rows=85 scenes=2
outputs/labelling/E12_lines.md rows=55 scenes=1
outputs/labelling/E13_lines.md rows=75 scenes=2
outputs/labelling/E14_lines.md rows=51 scenes=3
outputs/labelling/E26_lines.md rows=51 scenes=1
outputs/labelling/E27_lines.md rows=95 scenes=1
outputs/labelling/E28_lines.md rows=96 scenes=1
outputs/labelling/E29_lines.md rows=74 scenes=3
outputs/labelling/E42_lines.md rows=37 scenes=1
outputs/labelling/E43_lines.md rows=87 scenes=1
outputs/labelling/E44_lines.md rows=54 scenes=2
outputs/labelling/E45_lines.md rows=74 scenes=3
written: 16 files
```
check-gold on the template: `0 rows`, exit 0.

## 10. Risks and open items for the next prompt
- **snap_to_lines does not follow match_rule section 6.** The P01 function snaps outward to the *enclosing* line. Section 6 says *nearest* line start/end, with ties going to the earlier line. It is left unchanged as instructed; a section-6 "nearest" snap comes in P07.
- **decisions/ was not created.** match_rule.md refers to `decisions/DECISION_LOG.md`, the project's decision log, which lives outside this repo. Not created, as instructed.
- **The name guard only knows speaker labels.** A character named only in action or dialogue text, and never as a speaker, is not caught. The guard's 8-word shingle check covers longer quotes only. Skip list (approved Q3): mr, mrs, ms, dr, doctor, nurse, guard, officer, mom, dad, boss, man, woman, voice.
- **eval/gold.csv must stay LF and have no BOM** for `hash_eval add`. check-gold warns about both.
- **outputs/labelling/ contains script text.** It is git-ignored and blocked by guard.py; don't copy it anywhere else.
- At P08 the scorer should import `promo_finder.tiou.set_tiou` and `promo_finder.labelling.HELD_OUT` / `BLOCKS`, so the held-out set is defined in one place.

## Files
Created: `.gitattributes`, `eval/match_rule.md`, `eval/gold_rubric.md`, `eval/gold_template.csv`, `eval/HASHES.md`, `src/promo_finder/tiou.py`, `src/promo_finder/labelling.py`, `src/promo_finder/gold.py`, `tools/hash_eval.py`, `tests/test_tiou.py`, `tests/test_list_lines.py`, `tests/test_gold.py`, `tests/test_hash_eval.py`, `logs/P01b_report.md`.
Changed: `.gitignore`, `tools/guard.py`, `tests/test_guard.py`, `src/promo_finder/cli.py`.
Not in git (ignored): `outputs/labelling/E##_lines.md` x16.
