# Spec: Task Matching & Equivalence

**Implements:** `src/ptb/match.py`, `src/ptb/adjudicate.py` (Phase 4)
**Principle:** every equivalence claim is auditable (method + score + note +
provenance). The most dangerous error is a false equivalence shown to a
candidate; the design errs toward false negatives.

## Normalization (defines `tasks.normalized_text`)

Applied in order:
1. Unicode NFKC; replace smart quotes/apostrophes with ASCII.
2. Repair extraction whitespace artifacts: collapse runs of whitespace to one
   space; rejoin mid-word splits only when the raw PDF line-flow caused them
   (e.g. "an d" → "and").
3. Lowercase; strip trailing period.
4. Canonicalize known abbreviation variants from a maintained table, e.g.
   "(aars)" ≡ "(aar)". The table starts with exactly this pair and grows only
   with human sign-off (recorded in this spec's changelog).
5. Strip bracketed IPS cross-references matching the strict pattern
   `[See the NWCG Incident Position Standards for <position title>, PMS
   350-<n>, for ...]`. Justification: the bracket names the source DOCUMENT
   of the reading position, not the behavior being evaluated — leadership
   tasks are otherwise word-identical across positions at the same
   leadership level (grounded: ENGB #1 vs FIRB #1 differ only in
   "Engine Boss ... PMS 350-103" vs "Firing Boss ... PMS 350-105" inside the
   bracket; found by spec-checker audit 2026-07-09). The stripped reference
   is preserved in `verbatim_text` and available as provenance.

NOT normalization: removing words (step 5's strict-pattern bracket is the
single sanctioned exception), stemming, reordering, synonym substitution.
"Ensure effective communication with adjacent resources and supervisors" vs
"...with supervisors and adjacent resources" (ENGB 16 / FIRB 13) is NOT
tier-1; reordering goes through tier 2.

## Tiers

**Tier 1 — identical (auto-confirmed).** Same normalized_text → same
`tasks.task_id` (INV-3); the sharing itself is the match. Grounded examples
that MUST land tier-1 across fixtures:
- "Gather critical information pertinent to the assignment." — FFT1 #2, ENGB #4, FIRB #2
- "Assemble and validate readiness of crew, equipment, and vehicles." — FFT1 #4, ENGB #5, FIRB #3
- "Apply the Risk Management Process." — FFT1 #22, ENGB #19, FIRB #14
- "Develop and communicate contingency plans and trigger points." — ENGB #21, CRWB #31, FIRB #16
- "Plan for and manage medical emergencies." — ENGB #22, FIRB #17
- "Conduct and/or participate in After Action Reviews (AARs)." — FFT1 #21, ENGB #18, CRWB #29 (via the AAR/AARs abbreviation table)
- Leadership Level 2, New Leader body — ENGB #1, CRWB #1, FIRB #1 (via
  normalization step 5, which strips each book's own bracketed IPS
  reference; the "(Convey Content)"/"(Convey Intent)" variance lives in the
  CATEGORY header, not the task body). FFT1 #1 is Leadership Level 1
  (Follower) with different body text and MUST NOT join this task_id.

**Tier 2 — semantic candidates (embedding → adjudication → human review).**
- Model: `sentence-transformers/all-MiniLM-L6-v2`, local CPU, versioned in output.
- Candidate cut: cosine ≥ 0.80 between normalized texts of different task_ids.
  (Initial value; tune only via spec changelog after inspecting the score
  distribution on the full corpus.)
- Claude adjudicates each candidate pair against the rubric below, assigning
  `relation` ∈ {equivalent, a_subsumes_b, b_subsumes_a,
  related_not_equivalent} + a note. Subsumption direction is relative to the
  stored (task_a_id < task_b_id) row ordering; adjudication verdicts record
  the SUBSUMER'S NORMALIZED TEXT (id-independent), and the loader derives
  a_subsumes_b vs b_subsumes_a from it at write time.
- equivalent/subsumption verdicts get `status='probable'` until human review
  promotes to `confirmed` (sets `human_reviewed_at`) or demotes to `rejected`
  (also sets `human_reviewed_at`; the row keeps tier 2 and the adjudicator's
  relation for audit).
- **Grounded seed pairs:** the rubric-grounded pairs pinned in
  `match.py GROUNDED_SEED_PAIRS` (FFT1#10/ENGB#9 and the two
  firing-operations-triple pairs involving CRWB#14) are ALWAYS adjudicated
  and recorded with their true cosine score, even though they fall below the
  candidate cut — the spec requires their verdicts to exist in the table
  (AC-M3, rubric case 4). Seeds are keyed by normalized text, never task id.

**Tier 3 — rejected candidates.** Adjudicated `related_not_equivalent` →
tier 3, `status='rejected'`. Kept with score + note for audit. Never
surfaced to candidates. (Human demotion of a tier-2 probable stays tier 2
with `status='rejected'` — see above.)

## Re-running the pipeline (new position added / objective changed)

The whole tier-2 layer is rebuilt from three durable, text-keyed inputs, so
task-id churn from DB rebuilds never invalidates past work:

1. `data/adjudications.json` — one verdict per candidate pair, keyed by
   `pair_key` (hash of the two normalized texts). Authored by Claude
   in-session against this spec's rubric; append-only.
2. `data/confirmations.json` — the human review record (promote/demote),
   same keying. Append-only; written via `py src/ptb/adjudicate.py promote`.
3. `match.py`'s pinned model constants + `GROUNDED_SEED_PAIRS`.

Procedure after any corpus change (details in PLAN.md Phase 4):

```
py src/ptb/db.py           # rebuild data/ptb.sqlite from extracted/
py src/ptb/match.py        # regenerate data/tier2_candidates.json
py src/ptb/adjudicate.py   # apply verdicts -> task_equivalences + checklist
```

If `adjudicate.py` finds candidate pairs with no verdict, it writes
`data/pending_adjudication.json`, loads nothing new to the DB, and exits
non-zero. Give that file to Claude to adjudicate (rubric below), append the
verdicts to `data/adjudications.json`, and rerun. Newly probable pairs land
on the regenerated checklist for one-time human review; previously reviewed
pairs keep their recorded outcome automatically.

## Adjudication rubric (the prompt contract for Claude)

Judge only from the two task texts + their categories + position titles:
1. **Action level must match.** perform/execute ≠ supervise/direct/lead ≠
   ensure/monitor. A performer task never equals a supervisory task.
   Grounded: FFT1 #10 "Act as a lookout" vs ENGB #9 "Scout line in critical
   areas and patrol fireline" → related_not_equivalent.
2. **Object and scope must match.** Same action on a narrower scope is
   subsumption, not equivalence. Grounded: FIRB #11 "Scout line in critical
   areas." vs ENGB #9 "Scout line in critical areas and patrol fireline."
   → a_subsumes_b (ENGB subsumes FIRB).
3. **Equivalence tolerates only phrasing differences.** Grounded: ENGB #8
   "Develop, implement, and adjust tactics based on incident objectives, fire
   behavior, risk assessment, and leader's intent" vs CRWB #19 "Develop and
   implement tactics based on..." → adjudicator must weigh "adjust": expected
   verdict a_subsumes_b (ENGB subsumes CRWB), acceptable verdict equivalent —
   the note must address "adjust" either way.
4. **Firing-operations triple (hard case, expected related_not_equivalent or
   subsumption chain, never blanket equivalence):** ENGB #13 "Supervise and
   participate in firing operations" / FIRB #9 "Monitor and supervise firing
   operations" / CRWB #14 "...Plan, direct, and supervise firing operations."
5. Doubt → related_not_equivalent. The system prefers a missed shortcut over
   a false qualification claim.

## Context codes are NOT part of equivalence — they gate satisfaction

Identical text with different codes is still one canonical task (grounded:
"Gather critical information..." is O in FFT1, I in ENGB, W/RX in FIRB), but a
candidate's completion CONTEXT must satisfy the target position's code.
Compatibility (evaluation context → codes it satisfies):
- wildfire → W, I, O   • prescribed fire → RX, I, O
- other ICS incident → I, O   • simulation → S, O
- rare-event/interview → R, O   • any/classroom/daily job → O
`W/RX` (alternatives) is satisfied by any listed alternative. Gap analysis
(gap-analysis.spec.md) applies this matrix; matching only stores codes.
Caution: the enhanced_gdoc format redefines `O` (developmental/non-incident);
the matrix row for `O` applies per the owning format's definition — see
gap-analysis.spec.md for the split handling.

## Acceptance criteria

- [ ] AC-M1: All six grounded tier-1 examples share task_ids after the run.
- [ ] AC-M2: ENGB #16 / FIRB #13 (reordered wording) appears as a tier-2
      candidate, not tier-1.
- [ ] AC-M3: FFT1 #10 vs ENGB #9 ends related_not_equivalent; FIRB #11 vs
      ENGB #9 ends a_subsumes_b with ENGB as subsumer.
- [ ] AC-M4: Zero tier-2 rows reach `confirmed` without `human_reviewed_at`.
- [ ] AC-M5: Every equivalence row has method, and tier-2 rows have score +
      adjudication_note.
- [ ] AC-M6: Run is reproducible: rerunning on unchanged corpus produces an
      identical task_equivalences table (embedding model + version pinned).
- [ ] AC-M7: A generated human-review checklist (Markdown) lists every
      'probable' pair with both verbatim texts, positions, categories, score,
      and the adjudication note.
- [ ] AC-M8: ENGB #1, CRWB #1, FIRB #1 share one task_id after normalization
      step 5; FFT1 #1 does not share it.

## NTFT bridge candidates (F2 ntft-bridge, 2026-11-02)

**Implements:** `src/ptb/match.py --ntft-bridge`, `src/ptb/adjudicate.py`,
`src/ptb/review_sheet.py export --bridge ntft`. Feature spec:
`docs/F2_ntft_bridge.md`.

**Problem.** The tier-2 layer above found only 3 candidate pairs with one
NTFT (`source_documents.official = 0`) side and one NWCG (`official = 1`)
side, all three adjudicated related_not_equivalent, and no tier-1 task_id is
shared across that boundary. So no NTFT task can ever be satisfied through an
NWCG qualification. The bridge is a second, separately stored candidate layer
that targets exactly the cross-boundary pairs the 0.80 cut misses.

**Rules.**
- **Side filter.** A pair is a bridge candidate iff one task_id has >= 1
  occurrence in an `official = 0` position and the other task_id has >= 1
  occurrence in an `official = 1` position (evaluated over each task_id's
  full occurrence list; a task_id shared by both populations counts on
  either side — currently none exists). Same-side pairs are never bridge
  candidates.
- **Threshold.** `CANDIDATE_THRESHOLD_NTFT = 0.60` (initial value; the final
  value after the volume rule below is recorded in this section's changelog).
  Justification: the two task-book populations are written in different
  registers — NTFT books in a technology/competency vocabulary ("platform",
  "sensor", "model", "autonomy stack"), NWCG books in incident-operations
  vocabulary — so the embedding cosine systematically underestimates
  behavioral overlap across the boundary (95 NTFT tasks x 2,408 NWCG tasks
  produced 3 pairs at >= 0.80, every one rejected). Lowering the cut buys
  recall; precision is still gated by adjudication and human review, and the
  honesty contract is unchanged because nothing reaches `confirmed` without
  `human_reviewed_at`.
- **Volume rule.** If the 0.60 run yields more than 400 candidates, raise the
  cut to 0.65, rerun, and record the final threshold in the changelog.
- **Output.** `data/ntft_candidates.json`, same schema as
  `data/tier2_candidates.json` plus a top-level `"bridge": "ntft"`. The bridge
  is never merged into `tier2_candidates.json`, which stays byte-identical;
  any pair whose `pair_key` already exists in the tier-2 candidate set is
  excluded from the bridge (AC-B2), so each pair lives in exactly one layer.
  No grounded seed pairs apply to the bridge.
- **Method string** for bridge rows contains `ntft-bridge; cosine>=0.60`
  (the final threshold), so bridge rows are distinguishable from tier-2 rows
  in `task_equivalences.method` without a schema change.
- **Verdicts** are appended to `data/adjudications.json` with
  `"bridge": "ntft"` on each entry (same keying, same append-only store).
  equivalent/subsumption verdicts land as tier 2 `status='probable'`; the
  adjudicator never writes `confirmed`. Only the human review
  (`review_sheet.py ingest` or `adjudicate.py promote`) promotes to
  `confirmed` (sets `human_reviewed_at`) or demotes to `rejected`.
  related_not_equivalent -> tier 3 `status='rejected'`, as for tier 2.
- **Rubric.** Rules 1-5 apply unchanged. Restated for this boundary, because
  NTFT and NWCG books share nouns while describing different jobs:
  *operating a platform is not supervising people* — "operate the UAS
  platform during ignition" vs "supervise firing operations" is rule 1
  (action level), related_not_equivalent, however many words they share.
  Rule 6 (category framing, 2026-07-12 changelog) is applied by judgement in
  the note, not mechanically: the NTFT books' COMPETENCY categories are a
  different taxonomy from NWCG category names, so category disjointness is
  structural across this boundary and is not by itself evidence. The
  `context.py --apply` demotion rule is therefore never run over bridge
  pairs. Doubt -> related_not_equivalent (rule 5) still governs.
- **Human review.** `review_sheet.py export --bridge ntft` writes
  `reports/ntft_review_sheet.xlsx` listing every bridge `probable` pair sorted
  by score descending, with the standard columns plus NWCG position code(s),
  NTFT position code(s), and NTFT task level (`position_tasks.level`). The
  decision column accepts Confirm / Reject / Not sure; `ingest` is shared with
  the tier-2 sheet and keys on `pair_key`.

**Acceptance criteria (from docs/F2_ntft_bridge.md).**
- [ ] AC-B1: every bridge candidate has one official=0 side and one
      official=1 side.
- [ ] AC-B2: no bridge candidate duplicates a tier-2 pair_key.
- [ ] AC-B3: all bridge candidates adjudicated; counts by relation printed;
      0 confirmed before human review.
- [ ] AC-B4: CFMD prerequisites resolve to FBAN and LTAN (schema.spec.md
      changelog).
- [ ] AC-B5: after ingest, >= 1 confirmed equivalence touching an NTFT task;
      every confirmed row has human_reviewed_at.
- [ ] AC-B6: gap.py shows >= 1 NTFT position with a slot satisfied via
      equivalence for the CRWB profile.
- [ ] AC-B7: upstream pytest green; default pipeline unchanged
      (`tier2_candidates.json` byte-identical).

## Changelog

- 2026-11-03 (corpus refresh re-run): the pipeline in "Re-running the
  pipeline" was exercised end to end for the first time, after the
  2026-11-02 refresh replaced 12 positions' task books (10 republished as
  Next Gen, FEMO/FOBS split, REAF new) and corrected FAL3 #15-17
  (extraction.spec.md changelog). Thresholds, model and revision pins are
  unchanged. Outcome: 2,472 distinct tasks (was 2,503) → 1,410 candidate
  pairs incl. the 3 grounded seeds (was 1,352); 1,237 pairs carried their
  existing text-keyed verdict across the rebuild untouched, 115 verdicts in
  `data/adjudications.json` now describe texts no longer in the corpus
  (kept — the store is append-only), and 173 genuinely new pairs were
  adjudicated by Claude against rules 1-6 (46 equivalent, 40 subsumes, 87
  related_not_equivalent), then rule 6 was applied mechanically
  (`context.py --apply --protect-file <every pair already probable before
  the refresh>`) over the new pairs only, demoting 37; no pre-refresh
  verdict changed. Final table: 1,410 rows — 547 tier-2 probable, 863
  tier-3 rejected, 0 confirmed (human review still pending; the regenerated
  `reports/tier2_review_checklist.md` and `reports/tier2_review_sheet.xlsx`
  list the 547). (The extraction re-audit's FAL1 fix merged two
  wrongly-extracted texts into existing ones, which is why the counts are
  one lower than in the first run of this re-run: 2,473/1,411/548.) Adjudicator convention recorded for the briefing family
  that dominates the new pairs: "conduct and/or participate in X" is
  satisfied by participation, so against "participate in X" it is
  equivalent, and a side that requires conducting subsumes it (rules 1-3);
  briefing pairs whose named sources share no role stay
  related_not_equivalent per the Phase 4 briefing-source policy.

- 2026-11-02 (F2 ntft-bridge): added the "NTFT bridge candidates" section —
  a second candidate layer (`match.py --ntft-bridge`, output
  `data/ntft_candidates.json`, `CANDIDATE_THRESHOLD_NTFT = 0.60`) restricted
  to pairs with one official=0 and one official=1 side, adjudicated under the
  same rubric with rule 6 applied by judgement rather than by the mechanical
  context rule, and reviewed on a separate sheet
  (`reports/ntft_review_sheet.xlsx`). The tier-2 threshold (0.80), its
  artifact, and the default pipeline are unchanged. Final bridge threshold:
  recorded below once the volume rule has been applied.

- 2026-07-12 (context rule, SME-calibrated): added rubric rule 6 — **category
  framing governs over wording**: a candidate pair whose two sides' task-book
  category families share nothing (e.g. "Gather, analyze, and validate" vs
  "Ensure relevant information is exchanged" — doing vs overseeing) is
  related_not_equivalent even when the wording matches, because the books
  frame materially different behavioral contexts. Evidence: SME review of the
  first 51 checklist rows (6 "Unlikely", 4 "Not sure"); the codified rule
  (src/ptb/context.py) reproduced 5/6 of her Unlikely calls with 1 false
  alarm on her 41 confirms, while broader role-based variants mis-flagged
  6/41 and were rejected. Applied 2026-07-12 with the user's approval of
  aggressive narrowing: 304 rule demotions + 1 explicit SME demotion; her 41
  confirms protected. Each objective also carries a Bloom's-taxonomy level
  (src/ptb/blooms.py -> data/blooms.json); a Bloom gap >= 2 or a
  cross-domain + role-altitude split marks surviving pairs "Check context
  first" on the review sheet without auto-demotion.
- 2026-07-10 (Phase 4 build): (1) relation set gained `b_subsumes_a` —
  the schema's `task_a_id < task_b_id` ordering cannot otherwise represent a
  subsumer holding the larger id, and this spec's own rubric case 3 (ENGB #8
  subsumes CRWB #19) is exactly that case in the current build (task ids
  339 > 162); see schema.spec.md changelog same date. (2) Added the grounded
  seed-pair mechanism: FFT1#10/ENGB#9 measures cosine 0.244 and the
  CRWB#14 firing-triple pairs measure 0.651/0.549 — all below the 0.80 cut —
  yet AC-M3 and rubric case 4 require their verdicts recorded, so these
  spec-named pairs are always adjudicated regardless of score. The 0.80
  threshold itself is unchanged. (3) Documented the re-run pipeline and the
  text-keyed (task-id-independent) verdict/confirmation stores.
- 2026-07-09: Initial version. Normalization step 5 (IPS cross-reference
  stripping) added same day after spec-checker audit found ENGB#1/FIRB#1
  tier-1 claim unsatisfiable without it. Abbreviation table seeded with
  (aars)≡(aar).
