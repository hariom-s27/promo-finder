PLAIN SUMMARY
- What happened: Added make-workbook and export-gold, generated the ignored labelling workbook, passed the full suite, and staged the changes. The staged guard is clean. Work is stopped at the commit gate.
- What it means: Labelling can happen in Excel. Export normalizes LABELS into the frozen CSV format and delegates all final validation to the existing check-gold command.
- Problems: No remaining functional failures. Early test runs used the operating-system temporary directory for invented openpyxl XML intermediates; this violated the project-only write constraint. The final test run and real workbook generation explicitly used the project cache. Sandbox permission failures and their successful retries are recorded below.
- Decision needed (options + your pick): Approve the staged implementation for the requested commit, or request changes. My pick: approve after reviewing the recorded temporary-file deviation. No commit or push has been made.
- Exact next message for Hariom to send to the chat: APPROVED

SELF-AUDIT
1. Steps done: Step 0 -> done: clean starting status, HEAD 6ab790e, required source inspection, metadata-only gold.csv check, frozen hash comparison, and baseline 150 passed. The baseline ran after explicit plan approval because pytest writes temporary files. Plan -> done and approved. Part A -> done in workbook.py and cli.py: one workbook, held-out sheet order, scene rows, live parsing, styling, overwrite protection, counts-only output. Part B -> done in workbook.py: template headers, dropdowns, helpers, conditional formatting and freeze panes. Part C -> done in workbook.py and cli.py: values-only A-M export, normalization, CSV bytes, seal refusal and existing checker dispatch. Part D -> done in the new workbook/export tests and the guard tests. Part E -> done through verification, report, staging and commit-gate checks; evidence follows below. Commit -> not done, intentionally awaiting approval. Push -> not done.
2. Decisions I made that the prompt did not specify: Missing held-out episodes refuse generation instead of creating a partial workbook; a partial workbook would conceal missing source data. Helpers show bad ID in length_check when any segment lookup fails instead of treating an ignored text result as a valid total. Hash-ledger target basenames are compared case-insensitively, including when recorded under another directory, to protect names on Windows. Fractional or nonnumeric grades remain invalid values for check-gold rather than being silently rounded. Tabs and line breaks are converted to spaces in the rationale word helper. LABELS headers are validated before export; malformed workbook errors never echo cell values. Source strings beginning with an equals sign are stored as text. These choices keep check-gold authoritative; alternatives were partial generation, misleading helper results, narrower seal matching, silent coercion, or accepting malformed inputs.
3. Deviations from the prompt: The baseline was deferred until after plan approval with explicit user authorization. Existing tests create and read invented temporary env fixtures; the user explicitly authorized this exception while protecting the real project .env. Initial openpyxl fixture saves used the default Windows temp directory, outside the project; openpyxl normally deletes these intermediate XML files after saving. No real episode text was involved in those test workbook saves. This is an execution mistake, not a claimed exception. Remaining runs set TEMP and TMP to the project cache, and no openpyxl XML files remained there after completion. Pip initially failed because sandbox socket access was forbidden, then the same approved installation succeeded outside the sandbox. The unchanged baseline initially failed during sandbox temp-directory cleanup, then passed outside the sandbox. The final suite used a fresh project-local --basetemp and disabled pytest's cache provider to avoid stale directory/cache permissions. Two evidence-only Python -c commands had shell quoting errors; corrected PowerShell checks supplied the evidence below. No source or frozen data was changed to address these environment issues.
4. Numbers: See the sourced counts table, per-file test table, command transcripts and hash table below. Real workbook counts came from generation counters, never from reopening cells.
5. Tests: Before 150 passed; new 18; final 168 passed, failures 0, errors 0. The final run had no warnings. Focused tests passed before full-suite verification; their early cache warning is recorded below.
6. Frozen items: eval/match_rule.md, eval/gold_rubric.md and eval/gold_template.csv match eval/HASHES.md. HASHES.md matches its starting SHA256. Git reports no changes to those files or labelling.py, gold.py, checker.py, parser.py and models.py. The line-ID constructor and E##-L### format are untouched.
7. Held-out seal: No episode-level model/tool or baseline promo output was created or found in the output-directory inventory. Existing parsed/ping/log artifacts are the same categories described in logs/P01b_report.md's held-out-seal section. This task created only the labelling workbook under the real outputs directory. No real workbook was opened, loaded back, or printed. Existing outputs/labelling files were not opened or printed. Only directory/file metadata and generation counts were inspected. The existing eval/gold.csv was never opened, hashed or exported over. Export and workbook readback tests used invented fixture workbooks only.
8. Safety: No push, commit or real model call. The real promo-finder/.env was never opened, read, printed or searched, and no test was added that touches it. No keys or real script text were printed or copied into source, tests, this report, or a commit message. Only openpyxl was added as a direct requirement; pip also installed its required et-xmlfile dependency. Workbook paths are ignored and blocked by the staged-path guard, which also skips opening them. The final staged guard result and exclusions are recorded at the gate below. All intended project changes are within promo-finder; the early test-temp exception is disclosed above rather than asserting perfect write confinement.
9. LLM calls: 0. Neither new command imports or invokes the model client. Existing model tests use fake providers and make no network calls. Network access was used only for the requested pip installation.
10. Risks and open items for the next prompt: Excel computes formulas; openpyxl does not. Formula strings, styles and validations were checked on invented workbooks, without opening the real workbook in Excel. Paste operations can bypass Excel validation, and helper checks do not implement the checker rules. check-gold remains final authority. Keep TEMP and TMP inside the project when running openpyxl under this task's write-confinement rule. The existing real gold.csv remains untouched and must be populated only by a later authorized export. A hashed export requires a new version name. Await commit approval; never push.

FILES CREATED OR CHANGED

| Action | Full path | Purpose |
|---|---|---|
| Created | D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\workbook.py | Workbook generation, template loading and CSV export |
| Changed | D:\sem_iitk\sem9\kuku\promo-finder\src\promo_finder\cli.py | Command arguments and existing checker dispatch |
| Changed | D:\sem_iitk\sem9\kuku\promo-finder\tools\guard.py | Block workbooks anywhere without reading their cells |
| Changed | D:\sem_iitk\sem9\kuku\promo-finder\requirements.txt | Add openpyxl>=3.1 |
| Changed | D:\sem_iitk\sem9\kuku\promo-finder\.gitignore | Ignore *.xlsx anywhere |
| Created | D:\sem_iitk\sem9\kuku\promo-finder\tests\test_workbook.py | Workbook structure, formulas, validation and overwrite checks |
| Created | D:\sem_iitk\sem9\kuku\promo-finder\tests\test_export_gold.py | Exact CSV bytes, checker integration and seal protection |
| Changed | D:\sem_iitk\sem9\kuku\promo-finder\tests\test_guard.py | Workbook path rejection and no-read check |
| Created | D:\sem_iitk\sem9\kuku\promo-finder\logs\P01c_report.md | This report |
| Generated, ignored | D:\sem_iitk\sem9\kuku\promo-finder\outputs\labelling\gold_labelling.xlsx | Real labelling workbook; never reopened |

Test workbooks, CSVs, XML test reports, pip cache and final runtime temporary files are under the ignored project .cache directory. Dependencies were installed in the project's existing .venv. No pyproject dependency metadata or other source files were changed.

REUSED ENTRY POINTS AND HEADER

- promo_finder.labelling.HELD_OUT, BLOCKS and fmt_ms are imported directly by workbook.py.
- cli._load_episodes calls parser.parse_dir live, without loading existing parsed outputs.
- cli.cmd_export_gold calls the unchanged cli.cmd_check_gold after writing. That function builds its index with checker.build_index, then calls gold.read_sheet, gold.check_sheet and gold.format_report.
- workbook.template_header reads the first CSV record from eval/gold_template.csv. The existing checker independently compares it with gold.HEADER. No exported header was retyped in the implementation.

NUMBERS AND SOURCES

| Number | Source |
|---|---|
| Starting commit 6ab790e | git rev-parse --short HEAD; unchanged at the commit gate |
| Baseline 150 passed | Baseline command output below; unchanged baseline file counts also appear in logs/P01b_report.md |
| New tests 18 = 8 + 8 + 2 | tests/test_workbook.py, tests/test_export_gold.py, additions to tests/test_guard.py; final XML counts below |
| Final 168 passed; 0 failures/errors | .cache/p01c-final-results.xml and final pytest console output |
| Focused 28 passed, 1 cache warning | Focused command output for workbook/export/guard files |
| Real 16 episode sheets, 1231 line rows, 27 scene rows | make-workbook console output below; counters in workbook.write_workbook and HELD_OUT in labelling.py |
| LABELS 60 rows; rows 2-61; 6 helper columns | workbook.py LABEL_ROWS and HELPERS; tests/test_workbook.py |
| CSV 13 columns | eval/gold_template.csv; header comparison in tests/test_workbook.py |
| README 14 instruction rows | workbook.py README_LINES |
| Helper limits 20-60 seconds; rationale 20 words | workbook.py formulas; unchanged checker/config and gold.py rules |
| Fixture workbook 16 episode sheets, 34 line rows, 17 scene rows | tests/test_workbook.py using normal fixtures plus invented in-memory episodes |
| Existing gold.csv 119 bytes | Get-Item metadata only; no contents inspected |
| openpyxl 3.1.5 | pip show openpyxl Version line below; installed distribution metadata in .venv |
| et-xmlfile 2.0.0 | Successful pip installation output; installed dependency metadata in .venv |
| Model calls 0 | Only parse/labelling/checking commands ran; fake-provider model tests remain unchanged |
| Output inventory: labelling 17 files; parsed 50; logs 1; parse_report.json 1; ping_results.json 1 | Get-ChildItem file metadata grouped by output category; contents were not read |
| Staged 9 files; staged workbooks 0; staged gold CSVs 0 | git diff --cached --name-only path checks; guard.py staged output below |

COMMAND EVIDENCE

Every command ran from D:\sem_iitk\sem9\kuku\promo-finder. Python commands used .venv\Scripts\python and PYTHONDONTWRITEBYTECODE=1.

Baseline, before source edits:
```
.venv\Scripts\python -m pytest -q
150 passed in 3.15s
```
The initial sandbox run produced WinError 5 while pytest cleaned the existing project .cache/pytest-tmp directory. The unchanged rerun succeeded with the resolved cleanup target checked to be inside the project.

Dependency installation used project-local TEMP, TMP and PIP_CACHE_DIR:
```
.venv\Scripts\python -m pip install -r requirements.txt
```
The sandbox attempt failed with:
```
[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions
ERROR: Could not find a version that satisfies the requirement openpyxl>=3.1 (from versions: none)
ERROR: No matching distribution found for openpyxl>=3.1
```
The approved retry outside the sandbox completed:
```
Successfully installed et-xmlfile-2.0.0 openpyxl-3.1.5
```

Focused verification:
```
.venv\Scripts\python -m pytest -q tests/test_workbook.py tests/test_export_gold.py tests/test_guard.py --basetemp .cache/p01c-focused-1 --tb=short
28 passed, 1 warning in 3.08s
```
The warning concerned pytest's existing cache directory, not test behavior. An initial full suite also passed, before correcting openpyxl's temporary-directory environment:
```
.venv\Scripts\python -m pytest -q --junitxml=.cache/p01c-results.xml
168 passed in 7.36s
```

Final suite with TEMP and TMP set to the absolute project .cache/runtime-tmp directory:
```
.venv\Scripts\python -m pytest -q -p no:cacheprovider --basetemp .cache/p01c-final-1 --junitxml=.cache/p01c-final-results.xml
168 passed in 4.27s
```

Real workbook generation used that same project-local TEMP/TMP and did not use --force:
```
.venv\Scripts\python -m promo_finder make-workbook
outputs/labelling/gold_labelling.xlsx episode_sheets=16 line_rows=1231 scene_rows=27
```
No workbook cell verification followed this command. A metadata-only check found no remaining openpyxl temporary XML files in the project runtime-temp directory.

Version evidence:
```
.venv\Scripts\python -m pip show openpyxl
Version: 3.1.5
```

TEST COUNTS PER FILE

Counts are grouped from testcase classname attributes in .cache/p01c-final-results.xml. Only counts were printed.

| File | Before | New | Final |
|---|---:|---:|---:|
| tests/test_checker.py | 17 | 0 | 17 |
| tests/test_export_gold.py | 0 | 8 | 8 |
| tests/test_gold.py | 47 | 0 | 47 |
| tests/test_guard.py | 10 | 2 | 12 |
| tests/test_hash_eval.py | 7 | 0 | 7 |
| tests/test_list_lines.py | 8 | 0 | 8 |
| tests/test_llm.py | 25 | 0 | 25 |
| tests/test_parser.py | 27 | 0 | 27 |
| tests/test_tiou.py | 9 | 0 | 9 |
| tests/test_workbook.py | 0 | 8 | 8 |
| Total | 150 | 18 | 168 |

FROZEN-FILE HASH RE-CHECK

Get-FileHash -Algorithm SHA256 was rerun on these files. The first three digests were compared with the corresponding values in eval/HASHES.md; the ledger digest was compared with its starting value. All comparisons passed. Git also reported no changes to the frozen files or the parser/checker/gold/line-ID sources.

| File | SHA256 | Comparison |
|---|---|---|
| eval/match_rule.md | d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2 | Matches ledger |
| eval/gold_rubric.md | 6f7b5161a66d857e913e5f73715f6b36c129d4cd57b69cd7d618e2b53f5550c0 | Matches ledger |
| eval/gold_template.csv | bb794d8a826bbc62288c30d16010e162c647ae5bdd19673dc22ebaf422bd8391 | Matches ledger |
| eval/HASHES.md | 0e09c0c9276e306f6929c8cd0da1768c027ea3216c080f8e0a58c2a12d2d2280 | Matches starting digest |

GUARD AND COMMIT GATE

Before staging:
```
.venv\Scripts\python tools/guard.py
guard: clean (0 files checked, mode=staged)
```
This initial result is not presented as coverage of unstaged changes. The final staged result is required below. git diff --check passed. Git printed the existing autocrlf notices for non-eval source files and, in the sandbox, a global-ignore permission warning; neither changed any frozen file.

Staged using git add -A. git status --short:
```
M  .gitignore
A  logs/P01c_report.md
M  requirements.txt
M  src/promo_finder/cli.py
A  src/promo_finder/workbook.py
A  tests/test_export_gold.py
M  tests/test_guard.py
A  tests/test_workbook.py
M  tools/guard.py
```
git diff --stat --cached was displayed at the gate and contains only those files. git diff --check --cached passed. The final guard result:
```
guard: clean (9 files checked, mode=staged)
staged_files=9 staged_xlsx=0 staged_gold_csv=0
```
git check-ignore confirmed outputs/labelling/gold_labelling.xlsx and eval/gold.csv are ignored. No .xlsx or eval/gold.csv/versioned gold CSV is staged. Frozen hashes were rechecked again at the gate and all comparisons still passed. HEAD remains 6ab790e. No commit or push has been performed; wait for APPROVED before the requested commit.
