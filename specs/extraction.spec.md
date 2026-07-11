# Spec: Document Extraction & Structuring

**Implements:** `src/ptb/extract.py`, `src/ptb/structure/`, `src/ptb/models.py` (Phase 2)
**Method:** pdfplumber raw text (deterministic) → Claude structures to JSON →
pydantic validation → spec-checker audit → only then eligible for DB load.

## Formats (grounded in fixtures, 2026-07-09)

### `nwcg_nextgen` (fixtures: FFT1 311-14, ENGB 311-103, CRWB 311-98, FIRB 311-105)
Detection: text contains "INSTRUCTIONS FOR NWCG NEXT GENERATION POSITION TASK
BOOK" or "NWCG POSITION EVALUATION TABLE".
Structure: signature page (initiation / verification / agency certification);
instructions; **position evaluation table** = the task list, organized under
**category headers** (observed: "Leadership Level N, <name> (Convey ...)",
"Prepare and Mobilize", "Build the Team", "Supervise and Direct Work
Assignments", "Perform <Position>-Specific Duties", "Perform Fireline Duties",
"Communicate and Coordinate", "Manage Risk", "Document", "Demobilize" —
category sets VARY by position; do not hardcode); each task has a printed
**task number** and an **evaluation-context CODE**; four rating columns
(ratings N/O, D, M, E — a certification needs M or E on every task); one or
more **position evaluation record** form pages.
CODE vocabulary: `I`, `W`, `RX`, `R`, `S`, `O`, `ALL`, and slash-combinations
(e.g. `W/RX`, `W/RX/S`). `ALL` observed on CRWB task 1. Store the raw code
string AND the parsed list of alternatives.
Companion doc reference: "NWCG Incident Position Standards ... PMS 350-xxx"
— capture the PMS 350 number as `ips_reference`.

### `nwcg_legacy` (fixture: LOFR 311-05, June 2010)
Detection: cover reads "NWCG Task Book for the Position of:" and task pages
have the column header block "TASK / CODE / EVAL. RECORD # / EVALUATOR:
Initial & date upon completion of task".
Structure: tasks are numbered sequentially and grouped under **"Behavior:"
headings** (competency statements), not Next Gen categories; tasks may have
**sub-bullets** that are examples/clarification and explicitly NOT evaluated
("Evaluate the numbered tasks ONLY. DO NOT evaluate bullets") — capture
bullets as `clarifications`, never as tasks; completion is per-task evaluator
initial + date (no M/E rating scale); cover states task books "build on tasks
from previous prerequisite position task books" — legacy tasks may assume
prerequisite content that Next Gen restates.

### `enhanced_gdoc` (fixture: enhanced_ptbs_gdoc.pdf/.docx, exported 2026-07-09)
Detection: header "FireTech Position Task Books" / sections beginning
"NWCG Position Task Book — <title> (<code>)".
One document, ELEVEN draft positions (UAIS, AIML, RSEN, and eight more; some
lack a printed code — assign provisional codes, flagged in extra_fields).
**Provenance flag:** the document self-describes as "illustrative, NWCG-styled
drafts ... NOT official NWCG standards" — extraction records `official: false`
and every downstream surface must carry the draft label.
Task structure: tasks grouped under **COMPETENCY** headings (with a
descriptive sentence) then **Behavior:** subheadings — a two-level hierarchy
(store as `category` = competency, `behavior` = subheading; legacy uses
behavior only, nextgen category only). Completion is legacy-style per-task
evaluator initials + date with Eval Rec #. Each task also carries a **Level**
tier ∈ {Aspirant, Beginner, Journey, Expert}.
Position-level fields unique to this format: `attaches_to` (links to official
NWCG position codes — e.g. UAIS → UASP + FIRB), `prerequisite` (text naming
official positions + qualified/trainee status), `required_experience`,
`physical_fitness`, `currency` (e.g. "RT-373 (triennial)"),
`required_training[]` (each with source/provider and approx. cost),
`qualification_stack` (tier → qualifications), `employers_by_sector`,
`workforce_estimate`. "≥X" thresholds are deliberate placeholders — preserve
verbatim, never invent numbers.
**Code vocabulary caution:** this format REDEFINES `O` as "Developmental /
non-incident setting (framework extension)" — not NWCG's "any situation".
Extraction stores each format's code definitions; matching/gap logic must not
treat enhanced-`O` as interchangeable with NWCG-`O` (see matching.spec.md
context matrix note). Preferred extraction source is the DOCX (real structure,
no PDF text-flow artifacts); the PDF is the fallback and page-provenance
reference.

## Extraction pitfalls (observed in fixtures — the JSON must get these right)

1. Text-flow reordering: pdfplumber emits task text, then number, then code on
   separate lines ("Travel to and check in at assignment.\n3\nI"). Task
   number/text/code association must be reconstructed, not assumed in-order.
2. Multi-line task text must be stitched (CRWB task 15 spans 4 lines, with
   code "W/\nRX" split across lines → `W/RX`).
3. Encoding: smart quotes (’), checkbox glyphs (☐), and cp1252-unmappable
   characters occur; all text handling is UTF-8; extraction must not crash or
   silently drop characters (FIRB's review-checkbox glyph is dropped by
   pdfplumber — the checkbox field is detected by its sentence, not the glyph).
4. Prefix-splitting artifacts: mid-word splits like "an d" (ENGB task 1)
   appear in raw text; verbatim_text preserves the raw form; normalized_text
   repairs whitespace only (see matching.spec.md for normalization).
5. Repeated table headers on every page must not become tasks or categories.
6. Category header lines can interleave with column labels ("CODE", "Record
   Number", "1 2 3 4") — strip column furniture from category names.

## Output contract (one JSON per document → `extracted/<filename>.json`)

```
document: { filename, sha256, pms_number, format, position_codes[], title,
            edition_date, ips_reference?, official, page_count }
positions: [ { code, title, provisional_code?,   # true when code assigned by us
               requirements_text?, attaches_to[]?,  # enhanced_gdoc extras
               extra_fields? } ]                 # training/cost, stack, currency, ...
tasks: [ { position_code,          # owning position (multi-position docs)
            task_number,           # as printed
            category,              # nextgen category / legacy behavior / enhanced competency
            behavior,              # enhanced_gdoc only; null otherwise
            level,                 # enhanced_gdoc tier; null otherwise
            verbatim_text,         # exactly as extracted, stitched
            code_raw,              # e.g. "W/RX"
            code_alternatives[],   # e.g. ["W","RX"]
            clarifications[],      # legacy sub-bullets; [] for nextgen
            page } ]               # 1-indexed page of the task row
fields_observed: [ { field_name, page } ]   # feeds format-gaps analysis
extra_fields: { }                  # format-specific extras, free-form
```

`fields_observed` records which form fields the document actually contains
(e.g. `virtual_assignment_flag`, `fbps_fuel_model`, `evaluator_iqcs_number`,
`per_task_completion_date`, `trainee_ips_review_checkbox`) against the field
inventory in format-gaps.spec.md.

## Acceptance criteria

- [ ] AC-E1: Format detection assigns every corpus document exactly one format;
      fixtures resolve to: FFT1/ENGB/CRWB/FIRB → `nwcg_nextgen`, LOFR →
      `nwcg_legacy`.
- [ ] AC-E2: Task counts match ground truth on fixtures: ENGB = 24, FFT1 = 25,
      FIRB = 17, CRWB = 36 (verified by spec-checker audit 2026-07-09),
      LOFR = count of numbered tasks only (bullets excluded).
- [ ] AC-E3: Every task's `verbatim_text`, whitespace-collapsed, is a
      substring of the whitespace-collapsed raw text of its recorded page
      (no hallucinated, merged, or paraphrased tasks).
- [ ] AC-E4: Task numbers are complete and consecutive from 1 to N with no
      gaps or duplicates per position.
- [ ] AC-E5: Every task has a non-empty code_raw whose alternatives ⊆
      {I, W, RX, R, S, O, ALL}; spot checks: ENGB task 22 → R;
      FFT1 task 13 → W/RX/S; CRWB task 1 → ALL.
- [ ] AC-E6: Legacy sub-bullets appear only in `clarifications`, never as
      tasks (spot-check LOFR task 10's nine bullets — one top-level "•" item
      plus eight nested "-" sub-items, corrected 2026-07-09 from an initial
      miscount of seven during Phase 0 spec-writing; verified directly
      against the source PDF's extracted text).
- [ ] AC-E7: Category/behavior attribution correct on spot checks: ENGB task
      13 ("Supervise and participate in firing operations") → "Perform Engine
      Boss, Single Resource-Specific Duties"; LOFR task 14 → Behavior
      "Understand and comply with ICS concepts and principles."
- [ ] AC-E8: JSON validates against the pydantic models with zero coercion
      warnings; every page reference is within [1, page_count].
- [ ] AC-E9 (enhanced_gdoc): 11 positions extracted; `official=false`;
      spot checks: UAIS has 14 tasks, task 10 → code R + Level Expert +
      behavior "Respond to abnormal conditions"; UAIS attaches_to includes
      UASP and FIRB; every task has a Level ∈ {Aspirant, Beginner, Journey,
      Expert}; "≥X" placeholders preserved verbatim; the format's own `O`
      code definition captured, distinct from NWCG's.
