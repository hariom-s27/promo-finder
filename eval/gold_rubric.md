# GOLD LABELLING RUBRIC, version 1, 5 Nov 2026

Hashed together with `eval/match_rule.md` BEFORE labelling. If the rubric has to change during labelling, stop, write a version 2, log it, hash it, then continue. Every change is reported.
Sources: D05, H1-1 to H1-11, DR04 (hook and cliffhanger types), DR09.

## 1. Who and when
- Labeller: Hariom, the only labeller. He has read the whole show (stated in the write-up).
- Labelling happens before ANY tool or baseline output exists for the held-out episodes.
- No second labeller (H1-11). This is listed as a limitation.

## 2. Where
- Held-out episodes only, in 4 blocks: A = 1–4, B = 11–14, C = 26–29, D = 42–45.
- Target: about 15 positives (about 4 per block, at least 3 per block) and about 5 negatives (at least 1 per block where possible).

## 3. Hard limits (every label, positive or negative)
- Length 20–60 s, as computed by `check-gold` (not by hand).
- Cuts only on line boundaries: each segment = a start line ID and an end line ID.
- At most 3 segments, in story order (no flash-forward).
- All segments inside held-out episodes. Crossing episodes is allowed only between consecutive held-out episodes (e.g. ep 2 → ep 3).
- Two positives must not overlap with tIoU ≥ 0.5 (otherwise they are the same promo; keep the better one).
- NOT applied to gold: the tool's spoiler gate, join rules or policy flags. Label as an editor would.

## 4. What to look for (guidance, not a checklist)
- A strong first 3 seconds: something is already happening.
- An ending that leaves one specific, high-stakes question open.
- A cold viewer can follow it: who, their relationship, what is at stake.

## 5. Hook type (positives only): what starts in the first 3 s
| Code | Type | Short definition |
|---|---|---|
| H1 | Physical aggression | violence or forceful contact already happening |
| H2 | Public humiliation | a character is degraded in front of others |
| H3 | Bombshell line | a line that instantly changes a relationship or status |
| H4 | Identity / status reveal | hidden power or identity is shown or named |
| H5 | Imminent danger | a threat is in motion, outcome open |
| H6 | Status contrast cut | adjacent moments show the same person high vs low status |
| H7 | Accusing question | opens mid-confrontation on a demanding question |
| H8 | Reaction before cause | a shocked face before we see why |
| H9 | Forbidden intimacy | romantic tension with a taboo or power gap |
| H10 | Flash-forward | NOT used for gold (story-order limit) |

## 6. Cliffhanger type (positives only): how it ends
| Code | Type | Short definition |
|---|---|---|
| C1 | Open question | high-stakes question asked, not answered |
| C2 | Peril cut | danger in motion, outcome after the cut |
| C3 | Reveal, no explanation | new fact lands, its meaning not shown |
| C4 | Interrupted reveal | reveal is about to happen and is cut off |
| C5 | Decision point | explicit choice, not yet made |
| C6 | Arrival / interruption | someone enters at the peak of conflict |
| C7 | Reversal begun | underdog strikes back, comeuppance not complete |
| C8 | Held reaction | ends on a frozen shocked face |
| C9 | Emotional suspension | confession, accusation or proposal awaits a reply |

## 7. Grade
| Grade | Meaning |
|---|---|
| 3 | would launch as is |
| 2 | good with a light trim |
| 1 | usable starting point for an editor |
| 0 | NEGATIVE: looks tempting but is not a promo |

## 8. Negatives (grade 0): pick the main reason
| Code | Reason |
|---|---|
| N1 | Resolved: the answer, rescue, apology or defeat is inside the clip |
| N2 | Over-explained: the reveal is explained right after, killing the gap |
| N3 | Low stakes: ends on a trivial question or moment |
| N4 | Flat exit: ends on a transition with nothing pending |
| N5 | Confusing cut: needs earlier episodes (unknown name, "it's him") |
| N6 | Weak open: first 3 s are scenery, greetings or setup |

## 9. Rationale (every label)
- One line, at most 20 words.
- Roles only ("the wife", "the boss"). NO character names, NO quoted dialogue, NO script text.

## 10. Procedure
1. Run `list-lines` for one block (writes git-ignored files to `outputs/labelling/`).
2. Read the block and fill `eval/gold.csv` from `eval/gold_template.csv`.
3. Run `check-gold` and fix every error until it is clean.
4. Repeat for the 4 blocks.
5. Hash `eval/gold.csv` and commit the hash only (H1-10). Keep a backup copy of `gold.csv` inside the workspace, outside the repo. Never edit the file after hashing; a fix = version 2 + a log entry.
