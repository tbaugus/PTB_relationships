# PTB Relationships System — Build Plan

**Goal:** A repeatable system that (1) reveals which objectives/tasks are shared across
firefighter positions from NWCG Position Task Books, so a candidate who completes
position X can be shown "do tasks A, B, C (+ course/prereq requirements) and you also
qualify for position Y," and (2) produces an evaluative report of which fields each
document format captures and which it lacks (no imputation).

**Decisions made (2026-07-09):**

| Decision | Choice |
|---|---|
| Corpus | All PDFs linked from the NWCG PTB catalog page (following embedded links) + Google Doc of enhanced PTBs |
| Database | SQLite now; schema written in portable SQL for Postgres later |
| Extraction | Hybrid: pdfplumber raw extraction → Claude structures to schema-validated JSON → spec-checker audits vs. source before DB load |
| Equivalence policy | 3 tiers: exact (auto), semantic+adjudicated (needs one-time human sign-off), rejected (audit only) |
| Qualification scope | PTB task overlap core + thin `position_requirements` layer from PMS 310-1 (courses, prerequisite positions) |
| Format-gap output | `field_coverage` matrix in SQLite + regenerable Claude-written Markdown assessment |

**Method:** Spec-driven development. No implementation step begins until its spec has
acceptance criteria; a read-only **spec-checker sub-agent** audits every step's output
against the spec before it counts as done.

---

## Repository layout

```
PTB relationships/
├── PLAN.md                      # this file
├── specs/
│   ├── acquisition.spec.md      # corpus download: sources, completeness, provenance
│   ├── extraction.spec.md       # per-format field contracts, JSON schema, validation rules
│   ├── schema.spec.md           # SQL schema + invariants (FKs, uniqueness, provenance)
│   ├── matching.spec.md         # equivalence tiers, thresholds, adjudication rubric
│   ├── gap-analysis.spec.md     # the "closest positions" query contract + examples
│   └── format-gaps.spec.md      # field-coverage matrix rules; absent-from-format vs blank
├── .claude/agents/
│   └── spec-checker.md          # read-only audit sub-agent (definition below)
├── corpus/
│   ├── raw/                     # downloaded PDFs + exported Google Doc (never edited)
│   └── manifest.json            # url, sha256, download date, format tag per file
├── src/ptb/
│   ├── acquire.py               # scrape catalog page, download PDFs, build manifest
│   ├── extract.py               # pdfplumber raw text/tables per document
│   ├── structure/               # Claude-assisted structuring → pydantic models → JSON
│   ├── models.py                # pydantic schemas (the extraction contract in code)
│   ├── db.py                    # schema DDL, loaders (parameterized, portable SQL)
│   ├── match.py                 # tier-1 exact matching + embedding candidate generation
│   ├── adjudicate.py            # prepares candidate pairs for Claude review; records verdicts
│   ├── gap.py                   # closest-positions query functions (pure, app-callable)
│   └── report.py                # field_coverage matrix + Markdown gap report generation
├── data/ptb.sqlite
├── extracted/                   # one validated JSON per document (audit trail)
├── reports/format_gaps.md       # generated, never hand-edited
└── tests/                       # pytest: each spec's acceptance criteria as tests
```

## Database schema (core)

```sql
source_documents(id, filename, url, sha256, format,        -- 'nwcg_nextgen' | 'nwcg_legacy' | 'enhanced_gdoc'
                 ptb_pms_number, downloaded_at)
positions(id, code, title, source_document_id)              -- e.g. ENGB, FFT1
tasks(id, canonical_text, normalized_text)                  -- one row per distinct task
position_tasks(id, position_id, task_id, task_number,       -- number as printed in the PTB
               verbatim_text, page, behaviors_json,         -- provenance back to source
               evaluation_context)                          -- e.g. required setting (wildfire/RX/simulation)
task_equivalences(id, task_a_id, task_b_id, tier,           -- 1 exact | 2 adjudicated | 3 rejected
                  method, similarity_score, adjudication_note,
                  human_reviewed_at, status)                 -- 'confirmed' | 'probable' | 'rejected'
position_requirements(id, position_id, kind,                 -- 'course' | 'prerequisite_position' | 'other'
                      value, source)                         -- sourced from PMS 310-1
position_implications(id, holding_position_id,               -- PMS 310-1 "qualified as X also qualifies as Y"
                      implied_position_id, source)
field_coverage(id, format, field_name, status)               -- 'captured' | 'absent_from_format' | 'present_but_blank_in_samples'
-- future (app phase): candidates,
--   candidate_completions(candidate_id, position_task_id, completed_at, evaluator),
--   candidate_qualifications(candidate_id, position_id, qualified_at),
--   candidate_courses(candidate_id, course_code, completed_at)
```

Invariants (enforced in schema.spec.md and tests):
- Every `position_tasks` row has page-level provenance to a file in `corpus/raw/`.
- `task_equivalences` is symmetric-deduplicated (a<b), and no tier-2 row reaches
  `status='confirmed'` without `human_reviewed_at`.
- `field_coverage` never conflates absent-from-format with present-but-blank.

## Phases

> Counts inside Phases 0-6 describe the corpus as acquired 2026-07-09.
> The corpus was refreshed on 2026-11-02 — see "Corpus refresh" after Phase 6
> for the current counts and the drift that refresh recorded.

### Phase 0 — Specs (before any code) — **DONE 2026-07-09, pending your review**
Six specs written in `specs/` with acceptance criteria and worked examples grounded
in 5 downloaded fixtures (FFT1, ENGB, CRWB, FIRB = Next Gen format; LOFR = legacy
2010 format). Spec-checker agent defined in `.claude/agents/spec-checker.md`.
Key findings that shaped the specs:
- The corpus has two NWCG formats: **Next Gen** (position evaluation table,
  N/O-D-M-E ratings per assignment, external Incident Position Standards PMS 350-x
  for task detail) and **legacy** (Behavior-grouped tasks, per-task evaluator
  initials + date, inline clarification bullets, no rating scale). Plus the
  enhanced Google Doc format (third format, pending access).
- Identical task text recurs across positions with DIFFERENT evaluation-context
  codes (O/I/W/RX/R/S/ALL) — equivalence and context-satisfaction are separate
  concerns (matching.spec.md vs gap-analysis.spec.md).
- Google Doc unblocked and exported 2026-07-09 (PDF + DOCX in corpus/raw/):
  11 "FireTech" positions — the **NTFT (Novel Thinking Fire Tech)** set
  (UAS ignition, geospatial, detection ML, robotics, autonomy, fire modeling)
  that chain into official NWCG positions via prerequisites/attaches-to. The
  enhanced format contributes fields no NWCG format has (per-task Level tiers,
  training + cost, qualification stacks, currency, fitness, workforce
  estimates) — now in the format-gaps field inventory — and self-describes as
  NOT official NWCG standards, so `official=0` provenance runs through schema,
  gap output, and app surfaces. In rendered output these are labeled
  "NTFT standard" (owner terminology, 2026-07-12; centralized in
  `gap.DRAFT_LABEL`); `official=0`/`draft=True` remain the structural markers
  that keep them distinct from NWCG-official positions. It also redefines
  code `O`; handled in matching/gap specs.
**Exit:** specs reviewed by you; fixture documents chosen. ✅ downloads + specs done.

### Phase 1 — Acquisition — **DONE 2026-07-09, spec-checker: ALL PASS**
`acquire.py` scrapes the catalog page with requests + beautifulsoup4, follows embedded
links, downloads every PDF into `corpus/raw/`, records manifest entries. Google Doc
exported (File → Download → PDF and DOCX) into the same corpus with manifest entries.
**Check:** spec-checker verifies manifest completeness against the live catalog page
link list, no zero-byte files, hashes recorded.

136 documents acquired: 98 NWCG catalog PTBs, 11 FireTech PTBs (enhanced Google Doc,
PDF + DOCX), 36 companion PMS 350-xxx Incident Position Standards. Plus, added
2026-07-09 via `acquire_requirements.py`: 116 per-position PMS 310-1 qualification
requirements pages (see below) — 252 source documents total.

**Known gaps (tracked in `corpus/manifest.json` → `pending[]`, regenerated fresh on
every `acquire.py`/`acquire_requirements.py` run — rerun to reconfirm current state):**
- **PMS 310-1 (qualification requirements) — resolved 2026-07-09.** The PMS 310-1
  document itself turned out to be a general policy narrative with no per-position
  data and no single PDF — the actual per-position requirements (required training,
  required experience, physical fitness, currency relationships) live on each
  position's own `nwcg.gov/positions/<slug>/qualification-requirements` page,
  reachable from the Position Catalog (116 positions). `src/ptb/acquire_requirements.py`
  scrapes the catalog and each position's page, saving raw HTML to
  `corpus/raw/requirements/<code>.html` and structured JSON to
  `extracted/requirements/<code>.json`, ready for Phase 3 to load into
  `position_requirements`. Spec-checker: AC-A8/AC-A9 ALL PASS. One caveat carried
  into specs/acquisition.spec.md: these pages embed a rotating announcements widget
  unrelated to the requirements content, so the raw HTML's hash (unlike every other
  acquisition source) is not stable across reruns — the structured JSON output is
  the stable, idempotent artifact instead.
- **PMS 311-91 (FAL2, Intermediate Faller) and PMS 311-119 (FAL3, Basic Faller) —
  resolved, no action needed.** Verified manually 2026-07-09: neither PTB's text
  contains any reference to a PMS 350-xxx standard, and NWCG's publication pages for
  `pms350-91` and `pms350-119` both 404. These two positions genuinely have no
  companion Incident Position Standards document; this is a confirmed absence, not
  an acquisition miss.

### Phase 2 — Extraction & structuring — **DONE 2026-07-09, spec-checker: ALL PASS**
Per document: pdfplumber raw text/word-position extraction → deterministic
format-specific Python parsers (`src/ptb/structure/nextgen.py`, `legacy.py`,
`enhanced.py`) → pydantic validation (`src/ptb/models.py`) → `extracted/<doc>.json`.
Format detection tags each document. (Note: implemented as deterministic positional
parsers rather than LLM-assisted structuring per PLAN.md's original hybrid-method
description — this scaled better across 98 real documents with per-document layout
quirks; the output contract and spec-checker gate are unchanged.)
**Check:** spec-checker compares each JSON against raw text: task counts match,
random verbatim spot-checks are exact substrings of source text, every task has a page.
Failures block DB load.

99 extracted JSON files (98 NWCG PDFs + 1 combined enhanced_gdoc), 4,160 tasks total.
**Known gaps (4 tasks out of 4,160, verified via source-PDF character inspection as
genuinely blank code cells, not parser bugs):** PSC3 tasks 17 and 39, PSCC task 39,
FSCC task 26.

### Phase 3 — Database load — **DONE 2026-07-09, spec-checker: ALL PASS**
`src/ptb/db.py`: DDL from schema.spec.md (verbatim); loader ingests validated
JSONs from `extracted/*.json` into `source_documents`/`positions`/`tasks`/
`position_tasks` (tier-1 dedup via `normalize_text()`, per matching.spec.md's
steps 1-5), and `extracted/requirements/*.json` into `position_requirements`
(course/prerequisite_position/experience/fitness/currency kinds) and
`position_implications` (11 rows, hand-audited against each source file's
"note" field for an explicit grant-of-qualification statement — currency
network fields `currency_maintained_by`/`maintains_currency_for` are loaded
into `position_requirements(kind='currency')` and never treated as
implications, per this phase's known-gaps distinction below).
`tests/test_schema.py` covers AC-S1-S4 and INV-1-8 (44 pytest cases).

`data/ptb.sqlite`: 99 source_documents, 120 positions, 2,503 distinct tasks,
4,160 position_tasks, 2,029 position_requirements, 11 position_implications.

**Known gaps (documented, not bugs):**
- **Seven qualification-requirements-only codes have no PTB** (AREP, EDRC,
  FFT2, IARR, OPS3, PIOT, REAF): `positions` requires a `source_document_id`,
  so these never get a `positions` row and their
  `extracted/requirements/<code>.json` isn't loaded this phase.
- **Two curated position_implications pairs skipped** (DIVS->OPS3,
  ICT3->OPS3) for the same reason: OPS3 has no `positions` row.
- **INV-7 exception, added to schema.spec.md's Changelog this phase:** PSC3
  (missing task #17, #39), PSCC (missing #39), FSCC (missing #26) — source
  PDFs where the evaluation-code cell is genuinely blank in print for that
  task (Phase 2 known gap, confirmed by direct PDF inspection); extraction
  correctly omitted the task rather than invent a code, so these three
  positions' task numbering has real, documented gaps. Locked down by
  `test_inv7_full_corpus_matches_documented_exceptions_exactly` so any other
  or additional gap fails the suite.

### Phase 4 — Matching — **DONE 2026-07-10, pending your one-time human review**
1. Tier 1: join on normalized text / shared task identifiers → auto-confirmed.
   (Done at DB-load time via `tasks.normalized_text`, INV-3 — no equivalence rows.)
2. Tier 2 candidates: `src/ptb/match.py` — sentence-transformers
   `all-MiniLM-L6-v2` (model + exact HF revision hash pinned in the module),
   local CPU, cosine ≥ 0.80 between normalized texts of different task_ids.
   Full corpus: 2,503 distinct tasks → 1,349 candidate pairs + 3 spec-grounded
   seed pairs (below-threshold rubric pairs the spec requires recorded) = 1,352.
3. Claude adjudicated all 1,352 pairs against matching.spec.md's rubric
   (verdicts in `data/adjudications.json`, keyed by normalized-text hash, so
   they survive DB rebuilds): 445 equivalent + 418 subsumption → tier 2
   `status='probable'`; 489 related_not_equivalent → tier 3 `status='rejected'`.
   (44 briefing-source verdicts were demoted to related_not_equivalent across
   two spec-checker audit rounds, which flagged an unsanctioned
   source-abstraction — pairs whose texts name briefing sources with no
   common role are NOT equivalent.)
   Zero rows confirmed — that is exclusively yours.
4. **Your one-time review: work through `reports/tier2_review_checklist.md`**
   (863 probable pairs, highest score first — the near-duplicates at the top
   review fastest). For each pair:
   `py src/ptb/adjudicate.py promote <pair_key> confirm|reject [--note "..."]`
   Decisions land in `data/confirmations.json` (text-keyed, survives rebuilds)
   and re-apply to the DB automatically with `human_reviewed_at` set.
   **Non-technical reviewer alternative (e.g. an SME in Google Sheets):**
   `py src/ptb/review_sheet.py export` writes
   `reports/tier2_review_sheet.xlsx` (Instructions tab + one row per probable
   pair with a Confirm/Reject/Not-sure dropdown); upload to Google Sheets,
   have them fill the two yellow columns, download as .xlsx, then
   `py src/ptb/review_sheet.py ingest <file> --reviewer "Name"` converts
   their decisions into confirmations and re-applies to the DB. "Not sure"
   and blank rows stay probable and reappear on the next export; re-ingesting
   a corrected sheet is safe (newest decision per pair wins).
**Check:** spec-checker audit vs matching.spec.md: ALL PASS (AC-M1–M8);
`tests/test_matching.py` (34 pytest cases) locks every acceptance criterion.
Changelog entries added this phase (see specs/): `b_subsumes_a` relation value
(subsumption direction is carried by the relation value; the a<b row ordering
is dedup only) and the grounded seed-pair mechanism.

**Re-running matching after a corpus change (new position / changed objective):**
```
py src/ptb/acquire.py        # if the change comes from NWCG (refresh corpus)
py src/ptb/extract.py ...    # Phase 2 extraction for changed documents
py src/ptb/db.py             # rebuild data/ptb.sqlite from extracted/
py src/ptb/match.py          # regenerate data/tier2_candidates.json
py src/ptb/adjudicate.py     # apply verdicts -> task_equivalences + checklist
```
Existing verdicts and your confirmations are keyed by task TEXT, not task id,
so they re-apply automatically. If `adjudicate.py` reports pending pairs
(exit code 2), give `data/pending_adjudication.json` to Claude to adjudicate
per the rubric, append to `data/adjudications.json`, and rerun; only genuinely
NEW pairs land on the regenerated checklist for your review. Details:
specs/matching.spec.md § "Re-running the pipeline".

### Phase 5 — Gap analysis (the product query) — **DONE 2026-07-11, spec-checker: ALL PASS**
`gap.py`: `closest_positions(profile) -> ranked list of (position, missing_tasks,
missing_requirements)`, where `profile` is the candidate's full credential set:

```python
CandidateProfile(
    held_qualifications=[...],   # positions already qualified (e.g. ENGB)
    completed_courses=[...],     # courses explicitly on record (e.g. S-230)
    completed_task_ids=[...],    # individual signed-off tasks from open PTBs
)
```

**Requirement-satisfaction rules** (the "never re-demand what they already have" rules):
1. *Direct:* a requirement is satisfied if it appears in the profile
   (course on record, prerequisite position held, task signed off — including
   via a tier-1/confirmed-tier-2 equivalent task).
2. *Implied:* a requirement is satisfied if it appears anywhere in the
   requirement chain of a held qualification, resolved recursively — holding
   ENGB proves S-230 and FFT1 were met even if the profile never lists them.
3. *Conferred:* a position counts as held if `position_implications` says a
   held qualification confers it (PMS 310-1 "also qualifies as" rules).

Every satisfied requirement is returned with its derivation
(`direct` | `implied_by: <position>` | `conferred_by: <position>`) so the app
can display *why* something is waived and a reviewer can override it. Only
requirements satisfied by none of the three rules appear as gaps.

Pure functions over SQLite so any future app backend (FastAPI, etc.) can call
them. Include a CLI demo: `python -m ptb.gap --qual ENGB` → "FIRB: 4 tasks +
S-234 remaining (S-230, FFT1 satisfied — implied by ENGB)".
**Check:** acceptance examples in gap-analysis.spec.md run as pytest cases,
including at least one implied-satisfaction and one conferred-qualification case.

`tests/test_gap.py` covers AC-G1–AC-G8 (9 pytest cases); spec-checker: ALL
PASS. `python -m ptb.gap --qual ENGB` runs as a CLI demo (implemented as
`py src/ptb/gap.py --qual ENGB` on this machine's `py` launcher); the
worked example's #11/#13 satisfaction is read live from
`task_equivalences.status`, so the CLI's exact remaining-count changes as
your Phase 4 tier-2 review progresses (currently 0 confirmed, so FIRB shows
7 gaps_tasks; PLAN's original "4 tasks + S-234" example text above was
illustrative pre-data pseudocode, superseded by the spec's own worked
example).

**Forced Phase 3 fix, applied and documented in place:** AC-G8 (enhanced
draft position UAIS surfacing its prerequisites/training/currency/fitness)
had no data to query — `db.py`'s Phase 3 loader never ingested the
enhanced_gdoc positions' inline `attaches_to`/`extra_fields`, since those
11 FireTech positions have no PMS 310-1 catalog page for the existing
`load_position_requirements()` to read. Added
`db.py::load_enhanced_position_requirements()` (additive, enhanced_gdoc-only,
no DDL change, no Phase 1-4 test broken — 87/87 tests still pass) and
documented it in specs/schema.spec.md's Changelog (2026-07-11 entry) and in
db.py's own docstring. `data/ptb.sqlite` rebuilt and Phase 4's
match.py/adjudicate.py rerun on top of it (reproduced identically: 1,352
rows, 863 probable / 489 rejected / 0 confirmed — unaffected by the fix).

### Phase 6 — Format-gap evaluation — **DONE 2026-07-11, spec-checker: ALL PASS**
`report.py` computes `field_coverage` from the extraction layer (`extracted/*.json`)
and generates `reports/format_gaps.md`: a 47-field × 3-format matrix + narrative on
what each gap means and what reconciling formats would take. Regenerable at any
time (`py src/ptb/extract.py` then `py src/ptb/report.py`); never hand-edited.

`data/ptb.sqlite`'s `field_coverage` table: 141 rows (80 captured, 61
absent_from_format, 0 present_but_blank_in_samples — this corpus currently has
no genuine blank-vs-absent case, since the one candidate, enhanced_gdoc's
`edition_date`, turned out to be a real structural absence: the draft PDF has
zero "PMS" occurrences at all).

**Forced Phase 2 fix, applied and documented in place:** most of the field
inventory's evaluation-record-level fields had no `fields_observed` detector
at all before this phase (extraction only tracked 6 of 47 fields), which would
have forced report.py to guess at ~40 field_coverage rows. Instead,
`extract.py`'s `FIELD_MARKERS` gained ~45 additional marker entries per format,
each a literal substring verified present (or, for claimed absences, verified
absent) directly against the ENGB/LOFR/enhanced_ptbs_gdoc fixtures before being
added, plus a whitespace-normalization fix to `find_fields_observed()` (a
marker phrase can straddle a pdfplumber line-wrap in one document and not
another) and two field-name corrections to match format-gaps.spec.md's
inventory verbatim (`fbps_fuel_model`→`fbps_fuel_model_group`,
`level_rating`→`task_level_tier`) plus one mislabeling fix
(`trainee_ips_review_checkbox`'s marker had actually been evidencing a
different field, `ips_reviewed_flag`). All documented in
specs/extraction.spec.md's Changelog (2026-07-11, three entries). No
task/position/document structural field changed — every one of the 99
regenerated `extracted/*.json` files differs from before in its
`fields_observed` array only.

`tests/test_report.py` covers AC-F1–AC-F6 (21 pytest cases, including a test
that copies format-gaps.spec.md's field inventory verbatim and diffs it
against report.py's own list, added after a spec-checker audit round caught
`location_geographic_area` silently missing from report.py). Full suite:
108/108 passing.

**This was the last phase in this PLAN.** No further phases are planned;
future work is the candidate-facing app layer described in "Future expansion
hooks" below, which is out of scope for this build.

### Corpus refresh — **DONE 2026-11-03** (branch `corpus-refresh`)

The first re-acquisition since 2026-07-09 (counts quoted inside Phases 1-6
above describe the July corpus; this section describes the current one).

**Measured drift (NWCG, as of 2026-11-02):**
- 10 catalog books republished: CREP, STAM, ORDM, RCDM, COMP, COST, GISS,
  DECK, ATIM as **September 2026 Next Gen** editions (they were 2009/2022/
  2025 legacy-format books; task counts fell, e.g. STAM 41 → 21, CREP 30 →
  15), FAL2 January → July 2026.
- The combined legacy `pms311-30_FEMO-FOBS.pdf` was withdrawn (its versioned
  S3 URL returns NoSuchKey) and replaced by `pms311-30_FOBS.pdf` and the new
  `pms311-71_FEMO.pdf` (both September 2026 Next Gen, 15 tasks each). The
  old book is recorded under the manifest's `retired[]` with
  `superseded_by`; no archived copy was used.
- New: `pms311-112_REAF.pdf` (July 2025) — REAF leaves the "requirements but
  no PTB" list (six codes remain); companion standards PMS 350-12/-43/-44/
  -47/-48/-71/-93/-112. PMS 350-16/-30/-77/-85 (cited by STAM/FOBS/GISS/
  DECK) have no publication page yet → `pending`.
- NWCG renamed its S3 keys between editions (`pms-311-16.pdf` →
  `pms311-16.pdf`); the catalog lists CREP twice (identical content; the
  second link is kept as `alternate_urls`); the `pms310-1` publications page
  links only an unrelated flyer, so PMS 310-1 stays a web-scraped source.
- Two unchanged books disagree with the catalog's "Date Published" column
  (EQTR prints September 2024 vs catalog 2016-09; FELB June 2024 vs
  2024-07): the printed edition is used and the conflict recorded on the
  entry (`edition_date_conflict`).
- The Google Doc PDF export's hash changed while the DOCX did not (export
  nondeterminism; nothing re-extracted). 10 of 116 qualification-requirement
  pages changed wording only ("Completion and Certification of NWCG Position
  Task Book for X"; FEMO's now cites PMS 311-71).

**What changed in the build:** acquisition.spec.md gained a "Corpus refresh"
section and AC-A10..A12 (identity by (role, PMS number), `edition_date` /
`edition_date_source` / `page_count` per document, `retired[]`,
`--verify-urls`). extraction: `EDITION_DATE_RE` made case-insensitive (seven
legacy books with "October 2018"-style months had null edition dates — a
parser miss), stale extracted JSON for retired books removed, and two Next
Gen parser fixes forced by the September 2026 template (grid-header
detection right of the CODE column; row assignment by the table's own
horizontal rulings instead of nearest number) — the second also corrected a
pre-existing mis-parse of FAL3 #15-17 (verified against the page); the
spec-checker audit then forced two more pre-existing parser fixes (comma-
separated codes "I, S" in INCM/ABRO/RADO; a next-page "Behavior:" heading
merged into FAL1 #20/#23 and HLCO-ATGS #111). schema:
`source_documents.edition_date` populated for every row as ISO `YYYY-MM`
(manifest fallback for the NTFT draft's DOCX modified date 2026-06-22).
gap-analysis: AC-G9 — a "Data as of:" line in `format_report()` and
`app.py`. blooms.py: five verbs added for new objective texts. gap.py: prerequisite
codes with no task book (FFT2, EDRC, EMT) are no longer re-demanded (audit
finding AC-G2, pre-existing).

**Current corpus (`data/ptb.sqlite`):** 101 source_documents (100 NWCG: 51
Next Gen + 49 Legacy; 1 NTFT), 121 positions, 2,472 distinct tasks, 4,062
position_tasks, 2,125 position_requirements, 11 position_implications.
Manifest: 262 documents (102 ptb incl. the two Google Doc exports, 44
companion standards, 116 requirement pages), 1 retired, 7 pending.
INV-7 exceptions unchanged (PSC3 #17/#39, PSCC #39, FSCC #26).

**Matching re-run:** 1,410 candidate pairs (incl. 3 seeds); 1,237 kept their
text-keyed verdict, 115 stored verdicts now describe texts no longer in the
corpus (kept; append-only), 173 new pairs adjudicated by Claude (46
equivalent, 40 subsumes, 87 related_not_equivalent), then the 2026-07-12
context rule applied to the new pairs only (37 demoted; every pre-refresh
verdict untouched). Final: 547 tier-2 probable, 863 tier-3 rejected, **0
confirmed** — human review of the regenerated checklist/sheet still pending.

**Checks:** spec-checker audits of extraction, schema, matching,
gap-analysis and acquisition specs on the refreshed corpus (verdicts
recorded in the PR); `tests/test_corpus_refresh.py` adds offline tests for
AC-A11/A12, the ISO edition_date rule and AC-G9.

### Follow-up (2026-11-03): full legacy "Behavior:" headings (AC-E10)

The refresh audit left one recorded limitation: `structure/legacy.py` kept
only the first printed line of a wrapped "Behavior:" heading as the
category, so 362 of 1,040 distinct legacy (document, position, category)
values ended mid-sentence (ICT3 "Follow established procedures and/or
safety procedures relevant to given" lacked "assignment."). Fixed spec-first
(extraction.spec.md AC-E10 + changelog, grounded in LOFR page 7 and FAL1
page 12): the parser now appends a heading's continuation lines — printed at
the heading's own indent, one text row below it, before the first task
number — to the category. Regression over the whole corpus: 48 legacy
documents / 1,101 task rows change in `category` only (every new value is
the old one plus a suffix); task counts, `verbatim_text`, `code_raw`,
`clarifications` and `page` are byte-identical on all 101 documents. The 11
headings still without a terminal period (10 unpunctuated, SEMG's ends in a
colon) are printed that way by NWCG. Spec-checker audit of
extraction.spec.md AC-E1..E10 on the result: ALL PASS.
`tests/test_extraction.py` enforces AC-E10 corpus-wide against the PDFs.

Downstream effect on matching: `data/ptb.sqlite`, `data/tier2_candidates.json`
and `reports/tier2_review_checklist.md` regenerated (1,410 candidates, 547
probable, 863 rejected, 0 confirmed — unchanged). Because categories feed
`context.py`'s behavior families, every candidate pair's family sets and
`category_disjoint` result were recomputed against the pre-fix candidates:
**0 of 1,410 pairs changed**, so no verdict was touched and the context rule
was not re-applied. Observed while checking (pre-existing, not caused by this
fix, left alone): four pairs demoted by the context rule in July
(6bf15ea4089f2bab, 6ca240c8fdca5d08, 4f79ebd993a3ce7d, a3123c1c0e2cd1e8)
would not be flagged by today's `CATEGORY_FAMILIES` — their July demotion
predates a later family-regex change; their stored verdicts are append-only
and stand.

## Spec-checker sub-agent (`.claude/agents/spec-checker.md`)

```markdown
---
name: spec-checker
description: Read-only auditor. Verifies a build step's output against its spec.
tools: Read, Grep, Glob, Bash   # Bash for read-only queries (sqlite3, wc) only
---
You are a read-only auditor. You are given a spec file and the artifacts a build
step produced. You never modify files. Verify each acceptance criterion in the
spec against the artifacts, using direct evidence (counts, verbatim comparisons,
SQL invariant queries). Output: PASS/FAIL per criterion with evidence, and an
overall verdict. A single FAIL means the step is not done.
```

Invoked after every phase; a phase is complete only on an all-PASS audit.

## Tools & models (all free / already available)

| Part | Tool | Cost |
|---|---|---|
| Language | Python 3.12 + stdlib sqlite3 | free |
| Scraping | requests, beautifulsoup4 | free |
| PDF extraction | pdfplumber (PyMuPDF fallback for stubborn layouts) | free |
| Validation | pydantic v2 | free |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2`, local CPU | free |
| Structuring/adjudication/reports | Claude in VSCode (this assistant) | your existing plan |
| Testing | pytest | free |
| DB later | Postgres (local or Neon/Supabase free tier) | free tier |

## What NOT to do

- **Don't impute missing fields** — the format-gap output evaluates and reports; it never fills.
- **Don't trust similarity scores as equivalence** — every semantic match passes adjudication + one-time human review before candidates could ever see it.
- **Don't equate task-book completion with qualification** — gap output always includes course/prerequisite requirements from the requirements layer.
- **Don't re-demand satisfied requirements** — anything the candidate holds directly, or that is implied by a held qualification's requirement chain, or conferred by PMS 310-1 implication rules, is reported as satisfied (with its derivation), never as a gap.
- **Don't use a graph database or hosted DB now** — joins on SQLite answer everything at this scale; migrate to Postgres only when the app needs concurrent writes.
- **Don't let LLM output enter the database unvalidated** — pydantic + spec-checker gate every load.
- **Don't run semantic matching at app runtime** — equivalences are precomputed; runtime is plain SQL.
- **Don't hand-edit generated artifacts** (extracted JSON, reports, manifest) — fix the pipeline and regenerate.
- **Don't build the candidate-facing app layer yet** — expose pure Python query functions; the future app wraps them.

## Future expansion hooks (designed-in, not built now)

- `candidates` / `candidate_completions` tables join against `position_tasks` with no schema changes elsewhere.
- Portable SQL → Postgres migration is mechanical; `pgvector`/`sqlite-vec` available if live semantic search is ever wanted.
- Corpus refresh = rerun acquisition; manifest hashes detect changed PTB revisions and scope re-extraction.
