# Editor and platform feedback CSV

Design only. One row identifies one promo, platform, test type and start date.
No learning, collection or platform integration is implemented.

Columns, in this exact order:

```csv
show_id,promo_id,segments,hook_family,src_eps,H,C,A,F,P,S,weights_hash,batch_role,platform,test_type,start_date,impressions,plays_3s,views_15s,clicks,installs,ep1_completions,d1_retained,payers,revenue_d0,revenue_d7
```

| Columns | Type and meaning |
|---|---|
| show_id, promo_id | Required stable identifiers. |
| segments | Required JSON array of objects with episode, start_ms and end_ms; CSV-quote the JSON cell. Times come from the timestamp checker. |
| hook_family | Required moment-finder hook code H1–H9. |
| src_eps | Required JSON array of distinct source episode integers, in order. |
| H, C, A, F, P, S | Required numbers from the frozen official scoring formula, each 0–1; do not substitute sensitivity scores. |
| weights_hash | Required SHA-256 of the exact score_formula.yaml bytes. |
| batch_role | Required enum: control, challenger, reserve. Review status belongs in the ranking artifact. |
| platform | Platform identifier; required when platform results are supplied. |
| test_type | Enum even_split or normal; required when results are supplied. |
| start_date | ISO date YYYY-MM-DD in the reporting timezone. |
| impressions | Nonnegative integer: promo impressions delivered. |
| plays_3s | Nonnegative integer: plays reaching three seconds. |
| views_15s | Nonnegative integer: plays reaching fifteen seconds. |
| clicks | Nonnegative integer: attributed destination clicks. |
| installs | Nonnegative integer: attributed installs. |
| ep1_completions | Nonnegative integer: attributed first-episode completions. |
| d1_retained | Nonnegative integer: attributed users retained on day one. |
| payers | Nonnegative integer: attributed paying users. |
| revenue_d0, revenue_d7 | Nonnegative decimal: attributed cumulative revenue through day zero/day seven. Use a single documented currency for a dataset. |

Blank platform metrics mean unknown or not yet observed; zero means measured zero.
Do not infer a missing value or treat a normal delivery test as an even split.
Document attribution windows, metric definitions, currency and timezone alongside each dataset.
The CSV contains identifiers and metrics, with no transcript or model-generated prose.
