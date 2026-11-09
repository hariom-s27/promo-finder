# EVAL HASHES (sha256 of file bytes, LF line endings)
Frozen BEFORE any gold label exists. A changed file = a new version + a new DECISION_LOG entry.

| File | sha256 | Bytes | Recorded (UTC) | Note |
|---|---|---|---|---|
| eval/match_rule.md | d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2 | 4423 | 2026-11-07T18:37:17Z | frozen before labelling |
| eval/gold_rubric.md | 6f7b5161a66d857e913e5f73715f6b36c129d4cd57b69cd7d618e2b53f5550c0 | 4531 | 2026-11-07T18:37:17Z | frozen before labelling |
| eval/gold_template.csv | bb794d8a826bbc62288c30d16010e162c647ae5bdd19673dc22ebaf422bd8391 | 119 | 2026-11-07T18:37:17Z | frozen before labelling |
| eval/gold.csv | e1a2287d724e7a46d2606c79562b6414d3d0a55324a276e189c5c183ef5bbdd4 | 3275 | 2026-11-08T01:59:34Z | gold labels, hash only (file committed at P08) |
| outputs/gold_sealed/gold_longlist_v1.csv | df6d7be38839630dcbf61cd66eb97346658fb46a27c1db52249d65edf7c2d03e | 10499 | 2026-11-08T01:59:34Z |  |
| outputs/ai_labels/claude_v1.csv | fafdcc025d1154deed6571e5efa7d724d880933266d3eb4650f713942b7c7acb | 3170 | 2026-11-08T02:06:08Z |  |
| outputs/ai_labels/gpt_v1.csv | 9229fa4625a4740fdb313184110084dce9f89e8e8d83e0f5ff9f00feb3c08573 | 3167 | 2026-11-08T02:06:08Z |  |
| config/score_formula.yaml | 8f76ddf50855441a2b9dfc1e60b7f4f0db3cca308a8a37f22c7f25374b5638f3 | 2203 | 2026-11-08T05:29:10Z |  |
| config/eval_order.yaml | 71d0a4042e95ec90a5ec509f28eac447721d3e951ecb0259cb376520db734ab8 | 941 | 2026-11-08T16:56:30Z | frozen P07 config |
| config/baseline.yaml | 57ccd891e430926d0b2bc2766b4488759a32f3408def2bfdab684b8e37ca7cef | 1546 | 2026-11-08T16:56:30Z | frozen P07 config |
| config/v2.yaml | e09761554e5407f6d2b9a815c15f136942124b874fa048c192c221c058ece2f5 | 766 | 2026-11-09T01:07:47Z | v2 overlay F2+F5b (D97) |
| eval/match_rule_fresh.md | ba2a39d027a25ee19ea96a7517a44e637373a0efd05945ec04c34e843e6a884a | 3015 | 2026-11-09T01:07:48Z | fresh-set match rule (D94c) |
| eval/match_rule_fresh_b.md | 545ee2060cc7b640dcb2559d950a4dadbdd655411ba7317a4d28b66049acfa5d | 3433 | 2026-11-09T01:47:13Z | fresh block B rule (D98b) |
| eval/gold_fresh.csv | 40db75a8ffd04cb4d274f44f77415470cbf1e95b066ca448166922f10611a0e7 | 1321 | 2026-11-09T02:11:59Z | fresh block A gold (31-34), labelled by Hariom |
| eval/gold_fresh.csv | 40db75a8ffd04cb4d274f44f77415470cbf1e95b066ca448166922f10611a0e7 | 1321 | 2026-11-09T02:45:21Z | fresh block A gold (31-34), labelled by Hariom |
| eval/gold_fresh_b.csv | 5549ed984adeb3cbd28a6c1d7f2590d44b19e02001d513784f1c6aa838a01fc5 | 519 | 2026-11-09T02:45:21Z | fresh block B gold (15-17,35), labelled by Hariom |
