# Spec: Database Schema

**Implements:** `src/ptb/db.py` DDL (Phase 3)
**Engine:** SQLite now; DDL restricted to Postgres-portable SQL (no SQLite-only
types; INTEGER/TEXT/REAL; ISO-8601 TEXT dates; named FK constraints;
`PRAGMA foreign_keys = ON` in every connection).

## Tables

```sql
source_documents(
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  format TEXT NOT NULL CHECK (format IN ('nwcg_nextgen','nwcg_legacy','enhanced_gdoc')),
  role TEXT NOT NULL DEFAULT 'ptb'
       CHECK (role IN ('ptb','companion_standards','qualification_standard')),
  official INTEGER NOT NULL DEFAULT 1 CHECK (official IN (0,1)),
       -- 0 for enhanced_gdoc drafts; app surfaces MUST label these
  pms_number TEXT,
  edition_date TEXT,
  downloaded_at TEXT NOT NULL
);

positions(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,           -- ENGB, FFT1, ...
  title TEXT NOT NULL,
  provisional_code INTEGER NOT NULL DEFAULT 0 CHECK (provisional_code IN (0,1)),
       -- 1 when we assigned the code (some enhanced positions print none)
  source_document_id INTEGER NOT NULL REFERENCES source_documents(id)
);

tasks(                                  -- canonical: one row per distinct normalized text
  id INTEGER PRIMARY KEY,
  canonical_text TEXT NOT NULL,         -- representative verbatim form
  normalized_text TEXT NOT NULL UNIQUE  -- per matching.spec.md normalization
);

position_tasks(
  id INTEGER PRIMARY KEY,
  position_id INTEGER NOT NULL REFERENCES positions(id),
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  task_number INTEGER NOT NULL,         -- as printed in the PTB
  category TEXT NOT NULL,               -- nextgen category / legacy Behavior / enhanced COMPETENCY
  behavior TEXT,                        -- enhanced_gdoc second-level grouping; NULL otherwise
  level TEXT CHECK (level IN ('Aspirant','Beginner','Journey','Expert') OR level IS NULL),
                                        -- enhanced_gdoc progression tier; NULL otherwise
  verbatim_text TEXT NOT NULL,
  code_raw TEXT NOT NULL,               -- 'W/RX'
  code_alternatives TEXT NOT NULL,      -- JSON array text: ["W","RX"]
  clarifications TEXT NOT NULL DEFAULT '[]',  -- JSON array text (legacy bullets)
  page INTEGER NOT NULL,
  UNIQUE (position_id, task_number)
);

task_equivalences(
  id INTEGER PRIMARY KEY,
  task_a_id INTEGER NOT NULL REFERENCES tasks(id),
  task_b_id INTEGER NOT NULL REFERENCES tasks(id),
  relation TEXT NOT NULL CHECK (relation IN ('equivalent','a_subsumes_b','b_subsumes_a','related_not_equivalent')),
  tier INTEGER NOT NULL CHECK (tier IN (1,2,3)),
  method TEXT NOT NULL,                 -- 'normalized_text' | 'embedding+adjudication'
  similarity_score REAL,                -- NULL for tier 1
  adjudication_note TEXT,
  human_reviewed_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('confirmed','probable','rejected')),
  CHECK (task_a_id < task_b_id),        -- symmetric dedup; ordering is by id only —
                                        -- subsumption direction is carried by the
                                        -- relation value (a_subsumes_b | b_subsumes_a)
  UNIQUE (task_a_id, task_b_id)
);

position_requirements(
  id INTEGER PRIMARY KEY,
  position_id INTEGER NOT NULL REFERENCES positions(id),
  kind TEXT NOT NULL CHECK (kind IN ('course','prerequisite_position',
       'training','experience','fitness','currency','other')),
       -- 'course'/'prerequisite_position' evaluated by gap satisfaction rules;
       -- 'training'/'experience'/'fitness'/'currency' are DISPLAY-ONLY for now
       -- (no candidate data to evaluate them against) — see gap-analysis.spec.md
  value TEXT NOT NULL,                  -- 'S-230' | 'FFT1' | free text
  detail TEXT,                          -- JSON: e.g. {"source_provider": ..., "approx_cost": ...}
  source TEXT NOT NULL,                 -- e.g. 'PMS 310-1 (Oct 2025)' | 'enhanced_gdoc UAIS section'
  UNIQUE (position_id, kind, value)
);

position_implications(
  id INTEGER PRIMARY KEY,
  holding_position_id INTEGER NOT NULL REFERENCES positions(id),
  implied_position_id INTEGER NOT NULL REFERENCES positions(id),
  source TEXT NOT NULL,
  CHECK (holding_position_id <> implied_position_id),
  UNIQUE (holding_position_id, implied_position_id)
);

field_coverage(
  id INTEGER PRIMARY KEY,
  format TEXT NOT NULL,
  field_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('captured','absent_from_format','present_but_blank_in_samples')),
  evidence TEXT NOT NULL,               -- doc + page citations backing the status
  UNIQUE (format, field_name)
);
```

Future app-phase tables (`candidates`, `candidate_completions`,
`candidate_qualifications`, `candidate_courses`) join on `position_tasks.id`,
`positions.id` — nothing above may change to accommodate them.

## Invariants (each becomes a pytest + spec-checker SQL check)

- INV-1: Every `position_tasks` row's (verbatim_text, page) is traceable to a
  `source_documents` row via its position, and the file exists in `corpus/raw/`.
- INV-2: No tier-2 `task_equivalences` row has `status='confirmed'` with
  `human_reviewed_at IS NULL`. Tier-1 rows may auto-confirm.
- INV-3: `tasks.normalized_text` is unique; two `position_tasks` rows in
  different positions with identical normalized text share one `task_id`
  (this IS tier-1 sharing; no equivalence row needed for identical task_id).
- INV-4: `task_equivalences` rows always reference two DIFFERENT task ids
  (identical text is handled by shared task_id per INV-3).
- INV-5: Every position has ≥ 1 task; every task is referenced by ≥ 1
  position_tasks row (no orphans).
- INV-6: `code_alternatives` parses as JSON and is a non-empty subset of
  {I, W, RX, R, S, O, ALL}.
- INV-7: Task numbers per position are exactly 1..N (COUNT = MAX = N), with a
  documented exception for task numbers whose source PDF prints the task
  text but leaves the evaluation-context code cell genuinely blank: Phase 2
  (PLAN.md) verified by direct source-PDF character inspection that this is
  not a parser bug, and `src/ptb/models.py`'s `Task.code_alternatives`
  validator correctly refuses to invent a code, so extraction omits that
  task_number rather than fabricate one (PLAN's "don't impute" rule takes
  priority over gapless numbering). The only positions where this applies:
  PSC3 (missing #17, #39; 68 rows, max 70), PSCC (missing #39; 44 rows, max
  45), FSCC (missing #26; 33 rows, max 34). Any position outside this list
  must still satisfy COUNT = MAX = N exactly; a new gap appearing anywhere
  else is a real bug, not a repeat of this exception.
- INV-8: `level` and `behavior` are non-NULL for every task of an
  enhanced_gdoc position and NULL for every task of NWCG-format positions;
  every enhanced_gdoc source_document has `official = 0`.

## Acceptance criteria

- [ ] AC-S1: DDL executes on a fresh SQLite database without error, and also
      passes a syntax check against Postgres grammar (no engine-specific SQL).
- [ ] AC-S2: All seven invariants have corresponding automated checks in
      `tests/`, and all pass after fixture load.
- [ ] AC-S3: Loading the 5 fixtures produces: 5 ptb source_documents, ≥ 5
      positions, and shared task_ids across ENGB/FFT1/FIRB for at least
      "Apply the Risk Management Process." and "Gather critical information
      pertinent to the assignment." (tier-1 sharing via INV-3).
- [ ] AC-S4: Attempting to violate each CHECK/UNIQUE constraint in a test
      raises an IntegrityError (constraints actually enforce).

## Changelog

- 2026-11-02 (corpus refresh): (1) `source_documents.edition_date` is now
  populated for every row and stored as ISO-8601 `YYYY-MM` (or
  `YYYY-MM-DD`), honouring the "ISO-8601 TEXT dates" rule in this spec's
  header that the previous printed-form values ("JUNE 2009") did not. The
  loader converts the extraction layer's verbatim printed month, and when
  extraction has none (the enhanced Google Doc prints no edition line) it
  falls back to the manifest's `edition_date` (the DOCX core-properties
  `modified` timestamp, recorded by acquisition with its source). The
  printed month and the manifest's `edition_date` must agree on year-month,
  else the load raises; where NWCG's catalog and the PDF disagree,
  acquisition has already chosen the printed month and recorded the
  conflict on the entry (acquisition.spec.md AC-A12), so the DB value is
  always the document's own edition. No DDL change. (2) Known-gap list: PMS 311-112 (REAF, July
  2025) is now in the corpus, so REAF has a `positions` row and its
  requirements load; six requirements-only codes remain (AREP, EDRC, FFT2,
  IARR, OPS3, PIOT), and the two skipped `position_implications` pairs
  (DIVS→OPS3, ICT3→OPS3) are unchanged. (3) FEMO and FOBS are now two
  `source_documents` rows (`pms311-71_FEMO.pdf`, `pms311-30_FOBS.pdf`,
  both Next Gen) instead of one shared legacy row; the retired combined
  book is not loaded (acquisition.spec.md "Corpus refresh"). (4) INV-7's
  exception list is re-verified on the refreshed corpus: none of PSC3,
  PSCC, FSCC was republished, so the list is expected to be unchanged; if a
  refresh ever republishes one of them with the blank cell fixed, the
  exception for that position is removed here in the same change.

- 2026-11-02 (F2 ntft-bridge, AC-B4): the enhanced_gdoc source lists CFMD's
  anchor as the single string "FBAN / LTAN", which loaded as one
  `position_requirements(kind='prerequisite_position')` row whose value
  resolved to no `positions.code` (the only unresolved official=0
  prerequisite in the corpus; gap.py silently dropped it from the
  prerequisite graph while still listing it as an unsatisfiable gap). Fixed
  at the source: `extracted/enhanced_ptbs_gdoc.docx.json` now carries
  `attaches_to: ["FBAN", "LTAN"]`, and `structure/enhanced.py` splits
  "Attaches to:" entries on "/" as well as "+" so a re-extraction reproduces
  it. CFMD now has two prerequisite rows, FBAN and LTAN, both resolving.
  Semantic caveat recorded, not changed: the source's "/" reads as
  *either* anchor, but `position_requirements` has no alternative-group
  concept, so gap.py evaluates both rows as required (the conservative
  reading; a CFMD candidate holding only FBAN sees LTAN as a remaining
  requirement). No DDL change.
- 2026-07-11 (Phase 5 forced fix): `db.py` gained
  `load_enhanced_position_requirements()`, loading `position_requirements`
  rows for enhanced_gdoc (FireTech draft) positions from their inline
  `Position.attaches_to` (→ kind='prerequisite_position') and `extra_fields`
  (required_experience → 'experience', physical_fitness → 'fitness',
  currency → 'currency', required_training entries → 'training'). These
  positions were never in scope for `load_position_requirements()` (no PMS
  310-1 qualification-requirements page exists for non-catalog positions),
  so their Phase-2-extracted requirements data sat unloaded in
  `extracted/enhanced_ptbs_gdoc.docx.json` — a Phase 3 completeness gap not
  caught until gap-analysis.spec.md's AC-G8 (UAIS prerequisites/
  training/currency/fitness) had no data to query. No schema (DDL) change;
  `position_requirements` rows for these positions use the existing
  'prerequisite_position'/'experience'/'fitness'/'currency'/'training' kinds
  with `source = 'enhanced_gdoc Position.attaches_to / extra_fields'`.
- 2026-07-10: `task_equivalences.relation` gained the value `b_subsumes_a`
  (Phase 4). The `CHECK (task_a_id < task_b_id)` ordering rule makes the
  original single direction `a_subsumes_b` unable to represent a subsumption
  whose subsumer happens to hold the LARGER task id — and matching.spec.md's
  own grounded rubric example already requires that case: ENGB #8 (task id
  339 in the current build) subsumes CRWB #19 (task id 162), i.e. the
  subsumer is `b`. Direction is now carried entirely by the relation value;
  the a<b CHECK remains purely a dedup ordering. gap-analysis.spec.md rule 1
  amended in step.
- 2026-07-09: INV-7 amended to document the PSC3/PSCC/FSCC blank-code-cell
  exception (4 tasks total) after a Phase 3 spec-checker audit found the
  invariant, as originally worded, unsatisfiable on the full corpus without
  fabricating a code for tasks whose source PDF genuinely prints no code —
  which PLAN.md's "don't impute" rule forbids. This is not a new gap: PLAN.md
  already recorded it as a Phase 2 known gap ("4 tasks out of 4,160 ...
  genuinely blank code cells, not parser bugs") before Phase 3 began; this
  changelog entry is schema.spec.md catching up to that already-accepted
  fact, in the same spirit as matching.spec.md's normalization-step-5 entry.
