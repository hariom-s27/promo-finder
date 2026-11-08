PLAIN SUMMARY
- What happened: Completed the approved single live DEV judge invocation, then ranked the current candidates. Builder archive, ablations, model pings, tests and report are complete; commit is approval-gated.
- What it means: 21/39 current items have complete scoring evidence; launch batch contains 5 items. Human-review lanes and failed runs remain explicit.
- Problems: Groq request failures reduced evidence coverage; counts and effects are below. Backup featherless_llama is unverified after HTTP 401 at ping and must be re-pinged before P07. It was not retried now.
- Decision needed (options + your pick): A: approve the P05 commit with the reported limitations (pick); B: review the incomplete evidence before committing. No prompt or threshold tuning was performed.
- Exact next message for Hariom to send to the chat: APPROVED. Commit the staged P05 changes with the agreed message. Never push.

SELF-AUDIT
1. Steps done: Step 0 done (HEAD and initial clean status; fresh 321-test baseline). A done (archive, DEV rebuild and ten ablations). B done with backup ping failure. C/D/E done with one live judge invocation; failed runs excluded and counted. F done with code-only rank. G report and checks done; staging/guard evidence below, commit awaiting approval. Commands: python -m promo_finder judge --eps 5-8,19-22; python -m promo_finder rank --eps 5-8,19-22. Evidence: outputs/promos/p05_ablation.json, outputs/promos/build_summary.json, outputs/judge/judge_summary.json, outputs/judge/p05_validation.json, outputs/ranked/promos_dev.json.
2. Decisions I made that the prompt did not specify: Preserve max_speakers for legacy config compatibility; production uses new thresholds. Exact ties after failed repeats are unmeasured. Missing scoring evidence produces null scores and needs_human, preventing launch selection. Repeat disagreement requires at least two successful runs. Alternatives would require inventing a tie-break or missing score; these cases are covered by invented fixtures.
3. Deviations from the prompt: Initial read-only discovery preceded TEMP/TMP setup; later commands complied. Archive/ablation ran before the final passing suite; no live calls preceded that suite. Featherless authentication prevented a successful backup ping. Main Groq failures were recorded under the approved failure handling. No judge switch, Featherless retry, prompt tuning or second live invocation.
4. Numbers: Builder numbers come from outputs/promos/p05_ablation.json and build_summary.json. Live counts, reliability and agreements come from outputs/judge/judge_summary.json; validation and combined ping/main accounting from outputs/judge/p05_validation.json. Rank numbers come from outputs/ranked/promos_dev.json. Baseline/test numbers come from outputs/judge/offline_verification.json and offline_tests.xml. Formula definitions/hash come from config/score_formula.yaml; pricing/budget from config.yaml.
5. Tests: before 321; new 90; total 411; failures 0. Last fresh suite used project .venv, unique basetemp and cache_dir inside it. Sources: outputs/judge/offline_tests.xml and offline_verification.json. No pipeline code changed after that suite. Live artifacts also passed checker/schema/evidence/shuffle/aggregate/archive/launch validation: outputs/judge/p05_validation.json.
6. Frozen items: match rule, rubric, template and eval/HASHES.md unchanged; no eval files changed. Real line-ID format unchanged. Cold requests use clip-local IDs, with evidence mapped back after validation.
7. Held-out seal: Real operations selected DEV only; no new held-out outputs. Judge/rank refusal tests passed. Real gold, gold_sealed and ai_labels files were not opened. AI response/transcript text was not printed. Reference agreement uses only the supplied DEV majorities.
8. Safety: No push or commit. No keys printed. Real .env not inspected; credentials used only by application code. TEMP/TMP and fresh pytest basetemps inside project .cache/tmp after the initial deviation. .cache/pytest-tmp untouched. Guard evidence and staged-path exclusions are below; no script content detected in commit candidates.
9. LLM calls: Combined per-provider and per-part calls, requests, 429s, models, tokens, USD, cache hits and JSON modes are below. Groq json_schema remains best-effort and every successful response was validated in code. Failed runs do not enter aggregates. HTTP failures lacking usage have unknown unreported usage. Featherless remains unverified; no retry during the main run.
10. Risks and open items for P07: Re-ping featherless_llama after resolving HTTP 401, before P07. Investigate Groq HTTP failures and incomplete evidence before expanding the run; metadata preserves status codes, without provider response text. Human agreement is descriptive at six references. Keep the pre-declared sensitivity comparisons and scoring freeze. Baseline, pilot, full run, gold scoring and app work were not run. The 50-episode call budget is below.

A1-A4 EVIDENCE
Sources: outputs/promos/p05_ablation.json and outputs/promos/archive_p03/build_summary.json. Counts are offline, using the existing moment/reveal artifacts.

| Configuration | Kept |
|---|---:|
| P03 | 9 |
| only_A1 | 34 |
| only_A2 | 9 |
| only_A3 | 10 |
| only_A4 | 10 |
| all | 39 |
| without_A1 | 11 |
| without_A2 | 39 |
| without_A3 | 36 |
| without_A4 | 37 |

P03 versus P05 per episode:

| Episode | Generated | P03 kept | P05 kept |
|---|---:|---:|---:|
| E05 | 20 | 0 | 1 |
| E06 | 29 | 0 | 7 |
| E07 | 21 | 4 | 4 |
| E08 | 25 | 3 | 5 |
| E19 | 21 | 1 | 4 |
| E20 | 15 | 0 | 6 |
| E21 | 19 | 0 | 6 |
| E22 | 26 | 1 | 6 |

Drops by rule, aggregate:

| Rule | P03 | P05 |
|---|---:|---:|
| checker | 45 | 45 |
| J2 | 0 | 0 |
| J4 | 20 | 20 |
| speakers | 20 | 4 |
| resolution | 26 | 36 |
| reveal | 49 | 0 |
| late_series | 0 | 0 |
| dedupe | 7 | 32 |
| cap | 0 | 0 |

Drops by rule, per episode (same rule order on each row):

| Episode | Phase | checker | J2 | J4 | speakers | resolution | reveal | late_series | dedupe | cap |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| E05 | P03 | 6 | 0 | 4 | 8 | 0 | 2 | 0 | 0 | 0 |
| E05 | P05 | 6 | 0 | 4 | 4 | 4 | 0 | 0 | 1 | 0 |
| E06 | P03 | 4 | 0 | 11 | 0 | 5 | 9 | 0 | 0 | 0 |
| E06 | P05 | 4 | 0 | 11 | 0 | 2 | 0 | 0 | 5 | 0 |
| E07 | P03 | 5 | 0 | 0 | 4 | 4 | 0 | 0 | 4 | 0 |
| E07 | P05 | 5 | 0 | 0 | 0 | 8 | 0 | 0 | 4 | 0 |
| E08 | P03 | 5 | 0 | 0 | 0 | 8 | 7 | 0 | 2 | 0 |
| E08 | P05 | 5 | 0 | 0 | 0 | 8 | 0 | 0 | 7 | 0 |
| E19 | P03 | 4 | 0 | 4 | 1 | 9 | 1 | 0 | 1 | 0 |
| E19 | P05 | 4 | 0 | 4 | 0 | 9 | 0 | 0 | 0 | 0 |
| E20 | P03 | 3 | 0 | 1 | 7 | 0 | 4 | 0 | 0 | 0 |
| E20 | P05 | 3 | 0 | 1 | 0 | 5 | 0 | 0 | 0 | 0 |
| E21 | P03 | 7 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 |
| E21 | P05 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |
| E22 | P03 | 11 | 0 | 0 | 0 | 0 | 14 | 0 | 0 | 0 |
| E22 | P05 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | 0 |

End-line comparisons (matched moment identities):
```json
{
  "P03_vs_P05": {
    "matched_kept": 9,
    "changed_final_end": 5,
    "newly_kept": 30,
    "no_longer_kept": 0
  },
  "A4_on_off": {
    "matched_kept": 34,
    "changed_final_end": 17,
    "newly_kept": 5,
    "no_longer_kept": 3
  }
}
```
All matched P05/P03 items and the A4 counterfactual are reported separately; new/missing kept items are not treated as unchanged ends.

Resolution confidence counts, P05 (intersections may overlap; exclusive drops use highest blocking confidence):

| Confidence | Intersections | Drops |
|---|---:|---:|
| low | 0 | 0 |
| medium | 1 | 0 |
| high | 36 | 36 |
The confidence gate is an inference from the supplied human check; this DEV ablation finds no kept-count gain from A2 alone or on top of the other changes. This does not establish marking accuracy.

MODEL AND PING EVIDENCE
Sources: config.yaml, outputs/judge/pings.json, outputs/logs/llm_calls.jsonl. Picker azure_mini: openai; judge groq_qwen: alibaba; backup featherless_llama: meta. Existing config family refusal plus explicit runtime refusal are tested. Backup selection changes only active.judge.
Groq limiter: 30 RPM; 8000 TPM; concurrency 1; minimum interval 1.5 seconds. Input plus output-cap reservation is settled to reported usage. Qwen reasoning effort is none. No response text is included below.
```json
{
  "models": [
    {
      "model_key": "groq_qwen",
      "status": "ok",
      "model_string": "qwen/qwen3.8-27b",
      "cache_key": "eff66008ceb366d5e5ddc0e054f74bf870b74993acbc1d91cc37e0411a77fe61",
      "cached": false,
      "usage": {
        "input_tokens": 21,
        "output_tokens": 6
      },
      "trims_by_field": {},
      "response_mode": "json_schema"
    },
    {
      "model_key": "featherless_llama",
      "status": "failed",
      "error_code": "PROVIDER_ERROR"
    }
  ],
  "failed_runs": 1,
  "llm": {
    "parts": {
      "ping:featherless": {
        "calls": 1,
        "http_requests": 1,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usd": 0.0,
        "model_strings": [],
        "json_modes": [],
        "schema_failures": 0
      },
      "ping:groq": {
        "calls": 1,
        "http_requests": 1,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 21,
        "output_tokens": 6,
        "usd": 0.0,
        "model_strings": [
          "qwen/qwen3.8-27b"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      }
    },
    "providers": {
      "featherless": {
        "calls": 1,
        "http_requests": 1,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usd": 0.0,
        "schema_failures": 0
      },
      "groq": {
        "calls": 1,
        "http_requests": 1,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 21,
        "output_tokens": 6,
        "usd": 0.0,
        "schema_failures": 0
      }
    }
  }
}
```
Featherless HTTP 401 is recorded in outputs/logs/llm_calls.jsonl. Reported token sums are zero for that request because the provider returned no usage; actual unavailable usage is unknown. No strict/json_object capability conclusion can be drawn for the backup.

DRY RUN
Source: outputs/judge/dry_run.json. No secrets or network requests were used for preflight.
```json
{
  "dry_run": true,
  "episodes": [
    5,
    6,
    7,
    8,
    19,
    20,
    21,
    22
  ],
  "current_items": 39,
  "reference_items": 6,
  "repeated_items": 21,
  "parts": {
    "answer_key": {
      "calls": 8,
      "known_input_tokens": 34492,
      "dependency_allowance_tokens": 0,
      "output_budget_tokens": 48000,
      "provider": "azure",
      "model_key": "azure_mini",
      "estimated_input_tokens": 34492,
      "estimated_usd": 0.104623
    },
    "cold_judge": {
      "calls": 87,
      "known_input_tokens": 117996,
      "dependency_allowance_tokens": 0,
      "output_budget_tokens": 69600,
      "provider": "groq",
      "model_key": "groq_qwen",
      "estimated_input_tokens": 117996,
      "estimated_usd": 0.0
    },
    "fidelity": {
      "calls": 45,
      "known_input_tokens": 9630,
      "dependency_allowance_tokens": 23040,
      "output_budget_tokens": 11520,
      "provider": "groq",
      "model_key": "groq_qwen",
      "estimated_input_tokens": 32670,
      "estimated_usd": 0.0
    }
  },
  "providers": {
    "azure": {
      "calls": 8,
      "estimated_input_tokens": 34492,
      "output_budget_tokens": 48000,
      "estimated_usd": 0.104623
    },
    "groq": {
      "calls": 132,
      "estimated_input_tokens": 150666,
      "output_budget_tokens": 81120,
      "estimated_usd": 0.0
    }
  },
  "planned_calls": 140,
  "recommended_budget": 168,
  "max_calls_per_run": 168,
  "budget_covers_plan": true,
  "estimated_judge_pacing_s": 1990.5,
  "pacing_basis": "input plus completion reservations; excludes latency and retries",
  "token_basis": "local tokenizer estimate plus configured fidelity dependency allowance; excludes retries",
  "no_items_episodes": [],
  "pricing": {
    "azure_mini": {
      "input_per_million_usd": 0.25,
      "output_per_million_usd": 2.0,
      "source": "RESEARCH",
      "description": "list price, Global Standard"
    }
  },
  "cache_basis": "logical schedule; live calls may hit cache; each item/run has a distinct namespace"
}
```
Budget increased from 50 to 168 in config.yaml: 140 planned main calls plus the approved 20 percent headroom, rounded up. Pings use a separate wrapper instance. Main HTTP retries/validation retries must fit the same cap.
At the dry-run gate, no main P05 calls had run and only the successful ping cache entry existed. The estimate includes the configured 512-token fidelity dependency allowance per item. Live cache/usage accounting is below; estimates are not usage guarantees.

LIVE PER PART
Sources: outputs/judge/judge_summary.json and p05_validation.json; log metadata in outputs/logs/llm_calls.jsonl. One live DEV judge invocation; no no-cache rerun.

Main-run summary:
```json
{
  "status": "complete",
  "failed_runs_by_part": {
    "answer_key": 0,
    "cold_judge": 24,
    "fidelity": 10
  },
  "llm": {
    "parts": {
      "answer_key:azure": {
        "calls": 8,
        "http_requests": 8,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 34388,
        "output_tokens": 10594,
        "usd": 0.029785,
        "model_strings": [
          "gpt-5-mini-2025-08-07"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      },
      "cold_judge:groq": {
        "calls": 87,
        "http_requests": 92,
        "http_429s": 2,
        "cache_hits": 0,
        "input_tokens": 46900,
        "output_tokens": 10639,
        "usd": 0.0,
        "model_strings": [
          "qwen/qwen3.8-27b"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      },
      "fidelity:groq": {
        "calls": 35,
        "http_requests": 38,
        "http_429s": 2,
        "cache_hits": 0,
        "input_tokens": 6135,
        "output_tokens": 540,
        "usd": 0.0,
        "model_strings": [
          "qwen/qwen3.8-27b"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      }
    },
    "providers": {
      "azure": {
        "calls": 8,
        "http_requests": 8,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 34388,
        "output_tokens": 10594,
        "usd": 0.029785,
        "schema_failures": 0
      },
      "groq": {
        "calls": 122,
        "http_requests": 130,
        "http_429s": 4,
        "cache_hits": 0,
        "input_tokens": 53035,
        "output_tokens": 11179,
        "usd": 0.0,
        "schema_failures": 0
      }
    }
  }
}
```
Combined P05 ping and main accounting:
```json
{
  "llm": {
    "parts": {
      "answer_key:azure": {
        "calls": 8,
        "http_requests": 8,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 34388,
        "output_tokens": 10594,
        "usd": 0.029785,
        "model_strings": [
          "gpt-5-mini-2025-08-07"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      },
      "cold_judge:groq": {
        "calls": 87,
        "http_requests": 92,
        "http_429s": 2,
        "cache_hits": 0,
        "input_tokens": 46900,
        "output_tokens": 10639,
        "usd": 0.0,
        "model_strings": [
          "qwen/qwen3.8-27b"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      },
      "fidelity:groq": {
        "calls": 35,
        "http_requests": 38,
        "http_429s": 2,
        "cache_hits": 0,
        "input_tokens": 6135,
        "output_tokens": 540,
        "usd": 0.0,
        "model_strings": [
          "qwen/qwen3.8-27b"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      },
      "ping:featherless": {
        "calls": 1,
        "http_requests": 1,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usd": 0.0,
        "model_strings": [],
        "json_modes": [],
        "schema_failures": 0
      },
      "ping:groq": {
        "calls": 1,
        "http_requests": 1,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 21,
        "output_tokens": 6,
        "usd": 0.0,
        "model_strings": [
          "qwen/qwen3.8-27b"
        ],
        "json_modes": [
          "json_schema"
        ],
        "schema_failures": 0
      }
    },
    "providers": {
      "azure": {
        "calls": 8,
        "http_requests": 8,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 34388,
        "output_tokens": 10594,
        "usd": 0.029785,
        "schema_failures": 0
      },
      "groq": {
        "calls": 123,
        "http_requests": 131,
        "http_429s": 4,
        "cache_hits": 0,
        "input_tokens": 53056,
        "output_tokens": 11185,
        "usd": 0.0,
        "schema_failures": 0
      },
      "featherless": {
        "calls": 1,
        "http_requests": 1,
        "http_429s": 0,
        "cache_hits": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usd": 0.0,
        "schema_failures": 0
      }
    }
  },
  "http_errors": {
    "azure": {},
    "groq": {
      "HTTP_400": 34,
      "HTTP_503": 4,
      "HTTP_429": 4
    },
    "featherless": {
      "HTTP_401": 1
    }
  }
}
```
Reported token totals include returned usage on unsuccessful response parses, when provided, and exclude cache hits. HTTP errors without usage have unreported usage; zero recorded tokens do not prove zero work. Free-provider USD is the configured assumption.
Artifact validation and trim counts:
```json
{
  "items": 45,
  "current_items": 39,
  "references": 6,
  "cold_runs": 87,
  "successful_cold_runs": 63,
  "failed_cold_runs": 24,
  "fidelity_statuses": {
    "ok": 25,
    "skipped": 10,
    "failed": 10
  },
  "trims_by_field": {
    "answer_key.who": 0,
    "answer_key.stakes": 0,
    "answer_key.open_question": 0,
    "cold_judge.reader_who": 0,
    "cold_judge.reader_stakes": 0,
    "cold_judge.reader_next": 0
  },
  "errors": {}
}
```

FLIP RATE PER QUESTION
Source: outputs/judge/judge_summary.json. Denominator is measured repeated items; failed runs excluded. Single-run items are unmeasured.

| Question | Disagreeing items | Measured items | Flip rate |
|---|---:|---:|---:|
| hook_now | 4 | 13 | 0.3076923076923077 |
| ends_unresolved | 2 | 13 | 0.15384615384615385 |
| standalone | 2 | 13 | 0.15384615384615385 |
| orphan_line | 3 | 13 | 0.23076923076923078 |
| spoils_ending | 2 | 13 | 0.15384615384615385 |

Per-item flip rate is disagreeing questions divided by five, with review at 0.4. Unmeasured or tied majorities are not silently converted to measured agreement.

PART E AGREEMENT
Sources: outputs/judge/judge_summary.json and config/p03_human_majorities.yaml. Descriptive only; prompts and thresholds were not adjusted.

| Question | Agreement | Assessed references |
|---|---:|---:|
| Q1 | 6/6 | 6 |
| Q2 | 5/6 | 6 |
| Q3 | 4/6 | 6 |

Q1 compares mean hook rating >=3; Q2 compares majority standalone; Q3 compares majority ends_unresolved. Failed runs are excluded. Unmeasured comparisons are shown as null, not disagreement.
```json
[
  {
    "promo_id": "P03-E07-001",
    "human": {
      "Q1": true,
      "Q2": true,
      "Q3": true
    },
    "judge": {
      "Q1": true,
      "Q2": true,
      "Q3": true
    },
    "agreement": {
      "Q1": true,
      "Q2": true,
      "Q3": true
    }
  },
  {
    "promo_id": "P03-E07-002",
    "human": {
      "Q1": true,
      "Q2": true,
      "Q3": false
    },
    "judge": {
      "Q1": true,
      "Q2": true,
      "Q3": true
    },
    "agreement": {
      "Q1": true,
      "Q2": true,
      "Q3": false
    }
  },
  {
    "promo_id": "P03-E08-001",
    "human": {
      "Q1": false,
      "Q2": true,
      "Q3": true
    },
    "judge": {
      "Q1": false,
      "Q2": true,
      "Q3": true
    },
    "agreement": {
      "Q1": true,
      "Q2": true,
      "Q3": true
    }
  },
  {
    "promo_id": "P03-E08-002",
    "human": {
      "Q1": false,
      "Q2": true,
      "Q3": false
    },
    "judge": {
      "Q1": false,
      "Q2": true,
      "Q3": false
    },
    "agreement": {
      "Q1": true,
      "Q2": true,
      "Q3": true
    }
  },
  {
    "promo_id": "P03-E19-001",
    "human": {
      "Q1": false,
      "Q2": true,
      "Q3": false
    },
    "judge": {
      "Q1": false,
      "Q2": true,
      "Q3": true
    },
    "agreement": {
      "Q1": true,
      "Q2": true,
      "Q3": false
    }
  },
  {
    "promo_id": "P03-E22-001",
    "human": {
      "Q1": true,
      "Q2": false,
      "Q3": true
    },
    "judge": {
      "Q1": true,
      "Q2": true,
      "Q3": true
    },
    "agreement": {
      "Q1": true,
      "Q2": false,
      "Q3": true
    }
  }
]
```

RANKING AND LAUNCH EVIDENCE
Coverage limitations (source: outputs/judge/p05_coverage.json; cause counts are nonexclusive):
```json
{
  "current_unscored": 18,
  "current_missing_evidence_causes_nonexclusive": {
    "missing_key": 0,
    "no_successful_cold_runs": 4,
    "missing_successful_fidelity": 17,
    "tied_majority": 2
  },
  "review_reasons_nonexclusive": {
    "policy": 5,
    "flip_rate": 2,
    "reveal_and_ending": 1,
    "missing_evidence": 18
  },
  "reference_successful_runs": {
    "P03-E07-001": 1,
    "P03-E07-002": 3,
    "P03-E08-001": 3,
    "P03-E08-002": 1,
    "P03-E19-001": 2,
    "P03-E22-001": 3
  }
}
```

Sources: outputs/ranked/promos_dev.json and config/score_formula.yaml.
```json
{
  "items": 39,
  "scored": 21,
  "formula_sha256": "8f76ddf50855441a2b9dfc1e60b7f4f0db3cca308a8a37f22c7f25374b5638f3",
  "launch_batch": {
    "promo_ids": [
      "P05-E07-001",
      "P05-E06-007",
      "P05-E21-001",
      "P05-E22-002",
      "P05-E19-004"
    ],
    "family_relaxed_fill": [],
    "shortfall": 0
  },
  "lane_counts": {
    "needs_human": 25,
    "launch_batch": 5,
    "reserve": 9
  },
  "score_distribution": {
    "min": 0.28409863945578234,
    "median": 0.5821428571428572,
    "max": 0.8460884353741497
  },
  "kendall_equal": {
    "tau_b": 0.7482035902347645,
    "n": 21,
    "concordant": 182,
    "discordant": 26,
    "ties_x_only": 1,
    "ties_y_only": 0,
    "ties_both": 1,
    "denominator": 208.49940047875438
  },
  "kendall_no_funnel": {
    "tau_b": 0.8232662719901884,
    "n": 21,
    "concordant": 187,
    "discordant": 17,
    "ties_x_only": 1,
    "ties_y_only": 4,
    "ties_both": 1,
    "denominator": 206.49455198624491
  }
}
```

Launch batch (identifiers and numeric components only):

| Promo ID | Role | Hook family | S | H | C | A | F | P |
|---|---|---|---:|---:|---:|---:|---:|---:|
| P05-E07-001 | control | H2 | 0.846088 | 0.750000 | 1.000000 | 0.666667 | 0.938776 | 0.000000 |
| P05-E06-007 | challenger | H3 | 0.781463 | 0.750000 | 1.000000 | 0.833333 | 0.448980 | 0.000000 |
| P05-E21-001 | challenger | H5 | 0.720850 | 0.916667 | 0.750000 | 0.833333 | 0.295918 | 0.300000 |
| P05-E22-002 | challenger | H1 | 0.715476 | 0.750000 | 0.750000 | 0.916667 | 0.285714 | 0.000000 |
| P05-E19-004 | challenger | H8 | 0.704932 | 0.750000 | 1.000000 | 0.333333 | 0.566327 | 0.000000 |

Family-relaxed fills and any shortfall are recorded in the ranking summary. No selected items share line IDs. References are excluded from the ranked pool.
S_no_funnel is pre-declared and stored next to S; its tau-b is a sensitivity result only. Neither it nor equal weighting changed official lanes or launch selection.
Formula SHA-256: 8f76ddf50855441a2b9dfc1e60b7f4f0db3cca308a8a37f22c7f25374b5638f3
Hariom hashes the committed formula later. eval/HASHES.md remains untouched.

TEST COUNTS PER FILE
Source: outputs/judge/offline_tests.xml.

| File | Passed |
|---|---:|
| tests/test_build.py | 16 |
| tests/test_builder.py | 38 |
| tests/test_characters.py | 6 |
| tests/test_checker.py | 17 |
| tests/test_export_gold.py | 8 |
| tests/test_find.py | 14 |
| tests/test_gold.py | 47 |
| tests/test_guard.py | 12 |
| tests/test_hash_eval.py | 7 |
| tests/test_header.py | 3 |
| tests/test_intensity.py | 4 |
| tests/test_judge_cli.py | 7 |
| tests/test_judging.py | 26 |
| tests/test_list_lines.py | 8 |
| tests/test_llm.py | 63 |
| tests/test_moments.py | 5 |
| tests/test_p05_offline.py | 16 |
| tests/test_parser.py | 27 |
| tests/test_policy.py | 16 |
| tests/test_rank_cli.py | 6 |
| tests/test_ranking.py | 30 |
| tests/test_reveals.py | 4 |
| tests/test_tiou.py | 9 |
| tests/test_understand.py | 14 |
| tests/test_workbook.py | 8 |

GUARD
Command: .venv/Scripts/python.exe tools/guard.py
Staged guard result: guard: clean (21 files checked, mode=staged).
Staged-path exclusions and exact guard output are recorded in outputs/judge/commit_gate.json. No outputs/, .xlsx, eval/gold*.csv, frozen file or HASHES.md change is staged. No unstaged tracked change remains at the gate.

P07 CALL-BUDGET ENVELOPE
Sources: config.yaml and the call-count definition implemented in src/promo_finder/judging.py. For K current items, T repeated current items, R references and E nonempty episodes: Azure calls=E; Groq cold calls=K+2T+3R; Groq fidelity calls=K+R. With repeat_runs=3 this gives Groq=2K+2T+4R.
Conservative 50-episode capacity envelope, before late-series drops: K<=400, T<=100, R=6 gives Groq<=1024 and Azure<=50, total<=1074 logical calls. At the same 20 percent reserve the physical-request cap would be 1289. Pings, baseline and pilot are extra. Token/time estimates require actual candidate lengths; no full run was made.

CURRENT GATE
Live judging and ranking are complete. Waiting for APPROVED at the commit gate. Never push.
