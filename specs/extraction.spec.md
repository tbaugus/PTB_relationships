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
      once the task-number, evaluation-code and (enhanced) Level tokens that
      pdfplumber interleaves into wrapped task text (pitfall 1: "...crew,
      equipment, and 5 O vehicles.") are removed from the page text — and
      nothing else is removed: no hallucinated, merged, or paraphrased
      tasks, and no heading or bullet text absorbed into a task.
- [ ] AC-E4: Task numbers are complete and consecutive from 1 to N with no
      gaps or duplicates per position, with exactly the documented exception
      of schema.spec.md INV-7: PSC3 #17 and #39, PSCC #39, FSCC #26 are
      printed with a genuinely blank evaluation-code cell (verified by
      source-PDF character inspection, PLAN.md Phase 2), and extraction
      omits them rather than invent a code. Any other gap is a failure.
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

## Changelog

- 2026-11-03 (spec-checker audit of the refreshed corpus — three forced
  fixes, two of them pre-existing parser errors on books the refresh did
  not touch): (1) AC-E3 now states the token-interleaving reading the Phase
  2 audit applied (pdfplumber inlines the number/code/Level tokens into
  wrapped text; after the fixes below 2,551 of 4,062 tasks differ from the
  raw page only by those tokens and the other 1,511 are plain substrings) and AC-E4 now carries the INV-7 blank-code exception that
  schema.spec.md and PLAN.md already recorded on 2026-07-09 — both are the
  spec catching up to accepted decisions, not relaxations: under the stated
  reading 4,061 of 4,062 tasks matched before the fixes and the one that
  did not was a real bug, (2) below; all 4,062 match after them. (2) `structure/legacy.py`: a "Behavior:" heading is a
  section break at any indent. FAL1 (pms311-118) prints its page-12 heading
  at the text column, so the margin-only test read it as a continuation of
  the task still open from page 11 — FAL1 #20 ended with "Behavior: Follow
  established procedures...", #23 likewise, #22's last bullet absorbed
  "Behavior: Make appropriate decisions...", and #21-24 carried the wrong
  category. The heading now closes the open task; the same fix corrected
  HLCO-ATGS #111 (last bullet had absorbed "Behavior: Plan for
  demobilization...") and #112's category. (3)
  `structure/nextgen.py`: comma-separated printed codes ("I, S", "I, W, RX"
  in INCM #4/#10/#11/#14/#16, ABRO #6-#9, RADO #7/#11) were cut to their
  last element because the code-word filter dropped the comma-bearing
  tokens; `code_raw` now preserves the printed form and
  `split_code_alternatives()` parses either separator (gap.py's context
  matrix splits the same way). Known, deliberately unchanged: wrapped
  multi-line legacy "Behavior:" headings are still captured as their first
  line only (362 of 1,040 distinct legacy (document, position, category)
  values end mid-sentence after these fixes) — a
  pre-existing limitation outside this refresh, recorded as a follow-up.

  2026 template): two fixes to `structure/nextgen.py`, both grounded in the
  refreshed PDFs. (a) `_find_column_bands()` now only accepts "Record" /
  "Number" grid-header words that sit RIGHT of the CODE header: FOBS #9
  ("Record relevant or appropriate features on a map.") begins a task with
  the word "Record", which collapsed the code band and silently dropped
  every task after page 5 (FOBS and FEMO parsed 3 of 15 tasks each).
  (b) Text lines and code words are now assigned to the task whose
  table ROW (bounded by the page's horizontal rulings,
  `page.horizontal_edges`) contains them, with nearest-anchor kept only as
  the fallback for pages without rulings: a task's number is vertically
  centred in its row, so the last line of a long wrapped task can lie
  nearer the NEXT task's number (GISS #59, five lines — its tail
  "products not contained in the incident directory structure)" was
  attached to #60). Regression over the 38 unchanged Next Gen documents:
  37 re-extract byte-identically; FAL3 (pms311-119, unchanged upstream)
  changes at tasks 15-17, and the page shows the new reading is the
  correct one — #16 is "Perform the required elements of a procedural
  sizeup, and any critical considerations that could affect each element."
  followed by its seven bullets, which the old nearest-anchor rule had
  split across #15 (tail) and #17 (head). That was a pre-existing
  extraction error on the 2026-07 corpus, not a change in NWCG's text; the
  three FAL3 verbatim texts change in `extracted/` and `data/ptb.sqlite`
  accordingly, and any tier-2 verdict keyed by the old wrong texts drops out
  per matching.spec.md's text-keyed re-run rule.
- 2026-11-02 (corpus refresh): (1) `EDITION_DATE_RE` now matches the
  month name case-insensitively. Seven legacy books print a mixed-case
  month ("PMS 311-20 October 2018": HEBM, IRIN, ICPI, INVF, INVL, FWPT and
  the pre-refresh ATIM), and the upper-case-only pattern left their
  `document.edition_date` null — a parser miss, not a format absence;
  the printed value is still stored verbatim (e.g. "October 2018"), and
  normalization to ISO happens at DB load (schema.spec.md changelog, same
  date). (2) `extract.py` deletes any `extracted/<filename>.json` whose
  filename has no `role: "ptb"` entry in `corpus/manifest.json` (the
  retired `pms311-30_FEMO-FOBS.pdf.json` after this refresh), printing each
  deletion, so the audit trail only ever describes documents NWCG publishes
  today; `db.py` would otherwise load the retired book, and INV-1 would then
  fail because its raw file is gone. (3) The refreshed corpus changes the
  per-format population (9 books moved legacy → Next Gen — CREP, STAM, ORDM,
  RCDM, COMP, COST, GISS, DECK, ATIM; FAL2 was already Next Gen and only
  changed edition; FEMO and FOBS are now two Next Gen documents; REAF is
  new), so historical counts quoted
  in earlier changelog entries (e.g. "59 nwcg_legacy documents") describe
  the 2026-07 corpus, not the current one. No fixture changed; AC-E1..E9
  are re-verified by the spec-checker on the refreshed corpus, and any
  parser change the September 2026 Next Gen template forces is recorded as
  its own entry below.
- 2026-07-11 (Phase 6 forced fix): `extract.py`'s `FIELD_MARKERS` gained
  ~40 additional marker entries per format (signature-page phases,
  performance-rating scale, per-assignment/per-task evaluator fields,
  evaluation-record incident/event fields, code-definitions block,
  prerequisite-buildup statement), and renamed two existing field names to
  match format-gaps.spec.md's field inventory verbatim: `fbps_fuel_model` →
  `fbps_fuel_model_group`, `level_rating` → `task_level_tier`. Also
  corrected a mislabeled entry: the nwcg_nextgen marker text "Incident
  Position Standards Reviewed" (a per-evaluation-record Yes/No field) had
  been filed under `trainee_ips_review_checkbox`; it is now filed under the
  new, correct field name `ips_reviewed_flag`, and
  `trainee_ips_review_checkbox` is regrounded in its own marker, "(Box to be
  checked by trainee.)" — the position-evaluation-table checkbox the
  field inventory actually describes. Triggered by format-gaps.spec.md's
  AC-F2/AC-F3: report.py must ground every field_coverage row in direct
  extraction evidence, and most of the inventory's evaluation-record-level
  fields had no `fields_observed` entry at all prior to this fix. Every new
  marker is a literal substring verified present (or, for absences, verified
  absent) in the ENGB, LOFR, and enhanced_ptbs_gdoc fixtures before being
  added; see `src/ptb/extract.py`'s `FIELD_MARKERS` comments for the
  per-format absence rationale. No task/position/document structural field
  changed; `tasks`/`positions`/`position_tasks` counts are unaffected, only
  `fields_observed` entries were added/renamed. `tests/test_schema.py`,
  `test_matching.py`, `test_gap.py` re-run unaffected (fields_observed is
  not read by db.py, match.py, or gap.py).
- 2026-07-11 (Phase 6 forced fix, follow-up after spec-checker audit):
  `find_fields_observed()` was changed to whitespace-normalize both the
  marker text and each page's text before substring matching (collapsing
  all runs of whitespace, including `\n`, to a single space). Some marker
  phrases straddle a pdfplumber line-wrap point in one document but not
  another (e.g. "codes are defined as:" wraps as "codes\nare defined
  as:" in some PTBs and "The codes\nare defined as:" in others,
  depending on that document's own line width) - without normalization,
  `code_definitions_block` under-matched (42/59 nwcg_legacy documents
  instead of the true 59/59). This changes matching behavior, not marker
  content: no marker's required text changed, only how line breaks
  within that text are tolerated.
- 2026-07-11 (Phase 6 forced fix, second follow-up): `build_nwcg_document()`
  now also appends `fields_observed` entries named `edition_date` and
  `ips_reference` with a real page number (found by re-scanning
  `pages_text` for `EDITION_DATE_RE`/`IPS_REFERENCE_CITATION_RE`, the same
  patterns already used to compute the structural `document.edition_date`/
  `document.ips_reference` values), whenever those values are non-null.
  Triggered by spec-checker audit AC-F3: `report.py`'s document-level
  classifiers for these two fields previously cited only a filename, since
  `DocumentMeta` carries no page number for these document-wide values -
  format-gaps.spec.md requires every row to cite document + page. No
  DocumentMeta field changed; `document.edition_date`/`document.ips_reference`
  values are identical to before, this only adds a page citation alongside
  them.
