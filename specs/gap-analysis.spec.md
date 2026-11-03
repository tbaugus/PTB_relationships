# Spec: Gap Analysis (the product query)

**Implements:** `src/ptb/gap.py` (Phase 5)
**Form:** pure Python functions over the SQLite database — no framework,
no I/O side effects — so any future app backend can call them. Plus a CLI demo.

## Honesty contract (governs all output wording)

The system reports **demonstrated-task overlap and requirement gaps**, not
certification decisions. Agencies certify; a new PTB is still issued and
completed per agency policy. Output language must say what remains ("tasks
you have not yet demonstrated an equivalent of"), never "you are qualified."
Additionally, PTB completion is only part of qualification — course and
prerequisite requirements are always included in gap output (never omitted).

## Input

```python
CandidateProfile(
    held_qualifications: list[str],   # position codes, e.g. ["ENGB"]
    completed_courses: list[str],     # e.g. ["S-230"]
    completed_task_ids: list[CompletedTask],  # from open PTBs:
        # CompletedTask(position_task_id, context)  where context ∈
        # {wildfire, prescribed_fire, incident, simulation, rare_event, other}
)
```

Phase 5 has no candidate data; profiles are constructed synthetically in
tests and the CLI (`--qual ENGB --course S-230`).

## Satisfaction rules (evaluated in order; first hit wins, derivation recorded)

A target position's task-slot (position_tasks row) is **satisfied** when:
1. **direct-task:** the candidate completed that exact position_task, OR a
   position_task sharing its task_id (tier-1), OR one linked by a confirmed
   equivalence with relation `equivalent`, OR one that **subsumes** it
   (`a_subsumes_b` where the completed task is `a`, or `b_subsumes_a` where
   the completed task is `b`) — AND the completion
   context satisfies the target slot's code per the matrix in
   matching.spec.md. Subsumption never runs backwards: completing the
   narrower task does not satisfy the broader one.
2. **implied-by-qualification:** the slot's task_id appears (by the same
   task/equivalence logic) among the position_tasks of a held qualification,
   or of any position reachable from held qualifications through
   position_implications / prerequisite chains. Context codes are treated as
   satisfied (the qualification certifies performance in that position's
   required contexts). Derivation: `implied_by: <position>`.
A course/prerequisite requirement is **satisfied** when:
3. **direct-credential:** it appears in completed_courses / held_qualifications.
4. **implied:** it appears in the requirement chain (recursive) of any held
   qualification. Derivation: `implied_by: <position>`.
5. **conferred:** position_implications grants it from a held qualification.
   Derivation: `conferred_by: <position>`.

Nothing satisfied under rules 1–5 is a **gap**. Nothing in a gap list may be
satisfiable under rules 1–5 (no re-demanding).

Requirement kinds `training`/`experience`/`fitness`/`currency` (populated
mainly by the enhanced format) are **display-only**: listed informationally in
output (`info_requirements`), never evaluated as satisfied/gap — there is no
candidate data to evaluate them against yet. The output carries a fixed
disclaimer noting currency/fitness are not assessed.

**Draft-position labeling:** any position whose source document has
`official = 0` (the enhanced FireTech positions) must be marked `draft: true`
in output, and rendered output must label it distinctly (owner-directed label
2026-07-12: "NTFT standard", where NTFT = Novel Thinking Fire Tech — the
owning organization's own designation;
`official = 0` and `draft: true` remain the load-bearing structural markers so
these positions are never intermixed silently with NWCG-official ones). The
rendered label is centralized in `gap.DRAFT_LABEL`.

**Cross-format context caution:** the enhanced format's `O` code means
"developmental/non-incident", not NWCG's "any situation". The context matrix
applies per the CODE's OWN format's definition; enhanced-`O` slots are
satisfied by a `developmental` context (add it to CompletedTask contexts),
which does NOT satisfy NWCG-`O` slots' broader meaning in reverse — NWCG `O`
is satisfied by any context including developmental.

**Data currency (honesty contract):** every rendered report states what
edition of the source data it describes. `gap.data_currency(conn)` reads
`source_documents` and returns the corpus download date (max
`downloaded_at`), the NWCG task-book edition range (min/max `edition_date`
over `official = 1` ptb rows) and the NTFT draft's date; `format_report()`
prints it as a "Data as of:" line directly under the disclaimer, and
`app.py` shows the same line as a caption. A reader must never have to guess
whether a task cites the edition NWCG publishes today.

## Output

```python
closest_positions(profile, limit=None) -> list[PositionGap]

PositionGap(
    position: str, title: str,
    total_slots: int,
    satisfied: list[SatisfiedSlot],    # each with derivation + (for tier-2) equivalence id
    gaps_tasks: list[GapSlot],         # verbatim text, category, code_raw
    gaps_context_only: list[Slot],     # task demonstrated but not in a code-satisfying context
    gaps_requirements: list[GapReq],   # unsatisfied courses/prereqs
    satisfied_requirements: list[SatisfiedReq],  # with derivations
)
```
Ranked ascending by (len(gaps_tasks) + len(gaps_context_only) +
len(gaps_requirements)), ties by fewer gaps_tasks. Positions already held or
conferred are excluded. `gaps_context_only` is distinct from `gaps_tasks`
because the candidate's remaining work differs (get evaluated in the right
context vs learn/demonstrate a new task).

## Worked example (fixture ground truth — becomes the primary pytest)

Profile: `held_qualifications=["ENGB"]`, nothing else.
Against **FIRB** (17 slots):
- Satisfied via implied-by-qualification (tier-1 text sharing with ENGB):
  FIRB #2, #3, #4, #5, #10, #14, #15, #16, #17 — 9 slots — plus FIRB #1
  (Leadership L2), whose tier-1 identity with ENGB #1 depends on
  matching.spec.md normalization step 5 (IPS cross-reference stripping) —
  10 slots total.
- Satisfied via subsumption (ENGB #9 subsumes FIRB #11) once that tier-2
  row is human-confirmed: #11 (a gap while the row is still `probable`).
- Tier-2 dependent (must appear as satisfied only if the ENGB#16/FIRB#13
  equivalence was human-confirmed): #13.
- Expected gaps_tasks: #6 (Determine the Firing Plan), #7 (Ensure proper
  logistics and staging), #8 (Implement the Firing Plan), #9 (Monitor and
  supervise firing operations), #12 (Conclude operations).
- gaps_requirements: FIRB's course/prereq set from PMS 310-1 minus anything
  ENGB's chain implies.
FIRB must outrank (or tie with) CRWB and any unrelated position (e.g. LOFR)
in the ranking for this profile, and LOFR must show near-zero satisfaction.

## Acceptance criteria

- [ ] AC-G1: The ENGB→FIRB worked example passes exactly as specified
      (allowing #11 and #13 to move between satisfied/gap according to
      their tier-2 review outcome, which the test reads from the database:
      #11 rests on the ENGB #9 ⊃ FIRB #11 subsumption and #13 on the
      ENGB #16 / FIRB #13 equivalence, both `probable` until a human
      confirms them — see the 2026-11-03 changelog entry).
- [ ] AC-G2: No gap item is satisfiable by rules 1–5 (property-based test
      over synthetic profiles).
- [ ] AC-G3: Every satisfied item carries a derivation; every tier-2-based
      satisfaction cites a confirmed equivalence row id.
- [ ] AC-G4: Context gating works: a synthetic profile with "Gather critical
      information..." completed in context `other` satisfies FFT1 #2 (code O)
      but NOT FIRB #2 (code W/RX) → appears in gaps_context_only.
- [ ] AC-G5: Subsumption directionality: synthetic completion of FIRB #11
      does NOT satisfy ENGB #9; completion of ENGB #9 satisfies FIRB #11.
- [ ] AC-G6: Output text contains the qualification disclaimer and never the
      unqualified string "you are qualified".
- [ ] AC-G7: Ranking is deterministic and stable across runs.
- [ ] AC-G8: A profile with `held_qualifications=["UASP","FIRB"]` surfaces
      UAIS (enhanced draft) with its prerequisite requirements satisfied
      (derivations shown), `draft: true`, and its training/currency/fitness
      items under info_requirements — none of them counted as gaps.
- [ ] AC-G9: Text output and the test console carry a "Data as of:" line
      naming the corpus download date and the NWCG edition range, derived
      from `source_documents` (never hardcoded); on the refreshed corpus the
      newest NWCG edition shown is `2026-09`.

## Changelog

- 2026-11-03 (spec-checker audit on the refreshed corpus, two forced
  fixes): (1) **Rule 4 for prerequisites without a task book.** `gap.py`
  resolved `prerequisite_position` requirements only through the
  `positions` table, so a code with a requirements page but no PTB (FFT2,
  EDRC, EMT) could never be found in a held qualification's chain and was
  re-demanded: an ENGB holder was shown FFT2 as a remaining requirement for
  FFT1 (and for ICT5, FEMO, HECM, FAL3, UASP) although ENGB → FFT1 → FFT2.
  The requirement-text route already used for courses (the same (kind,
  value) in any held/chained position's requirement set ⇒ `implied_by`
  root) now applies to prerequisite codes too. A pre-existing defect, not
  caused by the refresh; AC-G2's "nothing in a gap list may be
  satisfiable" was violated on the 2026-07 corpus as well. (2) **AC-G1
  wording.** The worked example said FIRB #11 is satisfied "via confirmed
  subsumption", but no tier-2 row has ever been human-confirmed (the review
  is still pending), so #11 sits in gaps exactly like #13. PLAN.md's Phase 5
  record already states that "#11/#13 satisfaction is read live from
  task_equivalences.status"; the AC and the example now say the same. No
  change to the satisfaction rules: a `probable` row still satisfies
  nothing.
- 2026-11-02 (corpus refresh): added the data-currency rule and AC-G9 —
  `gap.data_currency()`, a "Data as of:" line in `format_report()` and in
  `app.py`. Motivated by the first corpus refresh: 12 positions' task books
  were republished (9 in a new format), and a report that cites a task
  without saying which edition it comes from would violate the honesty
  contract. No change to satisfaction rules or ranking.
- 2026-07-12: Owner-directed relabel of `official = 0` (enhanced/FireTech)
  positions from "draft — not an official NWCG standard" to "NTFT standard"
  (centralized in `gap.DRAFT_LABEL`). Display-only: `official = 0`,
  `PositionGap.draft = True`, and the never-intermix-silently requirement are
  unchanged, so AC-G8 and INV-8 still hold. The internal test console
  (`app.py`) also now annotates each displayed objective with its Bloom's
  level (`data/blooms.json`).
- 2026-07-10: Rule 1 subsumption wording extended to cover the
  `b_subsumes_a` relation value added in schema.spec.md /
  matching.spec.md's same-date changelog entries (direction is carried by
  the relation value; the a<b row ordering is dedup only). No behavior
  change to the satisfaction semantics: completing the subsumer satisfies
  the subsumed task, never the reverse.
