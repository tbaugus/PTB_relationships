# Spec: Corpus Acquisition

**Implements:** `src/ptb/acquire.py`, `src/ptb/acquire_requirements.py` (Phase 1)
**Status of fixtures:** 5 fixture documents downloaded 2026-07-09 (FFT1, ENGB, CRWB, FIRB, LOFR) — see `corpus/manifest.json`.

## Purpose

Download every NWCG Position Task Book plus the enhanced-PTB Google Doc into
`corpus/raw/`, with complete provenance in `corpus/manifest.json`, repeatably.

## Sources

1. **Catalog page:** https://www.nwcg.gov/training/nwcg-position-task-books-catalog
   — every linked PTB PDF (hosted on `fs-prod-nwcg.s3.us-gov-west-1.amazonaws.com`,
   URLs carry `VersionId` query params that MUST be preserved in the manifest).
   As of 2026-07-09 the catalog lists ~96 task books.
2. **Enhanced PTBs Google Doc:**
   https://docs.google.com/document/d/1rVGMJR67eftCjEcaoQuYDNBleoM7EOI9/edit
   — exported successfully 2026-07-09 (PDF + DOCX, 11 draft "FireTech"
   positions) after the owner enabled link sharing. The acquisition script
   still must detect an HTML response masquerading as a PDF/DOCX (check magic
   bytes, not extension) and record status `blocked` rather than saving junk —
   sharing could regress. Both export formats are kept: DOCX is the preferred
   extraction source, PDF the page-provenance reference.
3. **Companion standards (one level of embedded links):** Next Gen PTBs
   reference an Incident Position Standards document (PMS 350-xxx) that holds
   task descriptions, behaviors, and knowledge. Acquisition follows these
   references and downloads each referenced PMS 350-xxx PDF, recorded with
   `role: "companion_standards"` and linked to its PTB by PMS number.
4. **PMS 310-1 position qualification requirements (`src/ptb/acquire_requirements.py`):**
   PMS 310-1 itself (nwcg.gov/publications/pms310-1) is a general policy
   narrative with no per-position data and no single downloadable PDF — the
   `pending`/`blocked` path anticipated for this source in an earlier revision
   of this spec does not apply; there is nothing to mark blocked because a
   working alternate path exists. The actual per-position PMS 310-1 elements
   (required training, required experience, physical fitness level, currency
   relationships, other training) live on each position's own
   `nwcg.gov/positions/<slug>/qualification-requirements` page, reachable from
   the Position Catalog (nwcg.gov/positions/position-catalog, 116 positions as
   of 2026-07-09). Acquisition scrapes the catalog for `(code, title, slug)`,
   fetches each position's requirements page, and records it with
   `role: "qualification_standard"`, `pms_number: "310-1"`,
   `position_codes: [<code>]`. Raw HTML goes to `corpus/raw/requirements/<code>.html`;
   the parsed structure goes to `extracted/requirements/<code>.json` (ready for
   Phase 3's `position_requirements` load) — this parse step normally belongs
   to Phase 2, but is done here alongside the fetch since, for this source,
   download and structuring are a single simple per-position HTTP GET + parse
   with no intermediate raw-text-extraction stage worth separating out.
   **Idempotence exception:** unlike every other source in this spec, these
   pages embed page-wide dynamic content unrelated to the requirements data
   (a rotating "NWCG Latest Announcements" widget), so the raw HTML's sha256
   changes on nearly every fetch and cannot gate re-download the way AC-A7
   requires elsewhere — every run rewrites every raw HTML file and manifest
   entry for this source. The structured JSON output, parsed only from the
   stable "Qualification Requirements" section, is unaffected and *is*
   byte-identical across reruns; AC-A8 checks that property instead.

## Manifest contract (`corpus/manifest.json`)

Each document entry has: `filename`, `position_codes` (list — some PTBs cover
multiple positions, e.g. PMS 311-10 covers STCR/STEQ/STEN/TFLD), `title`,
`pms_number`, `format` (assigned later by extraction; acquisition writes
`"unclassified"`), `url` (with VersionId, except source 4's pages — not
S3-hosted, no VersionId concept), `sha256`, `downloaded_at`,
`role` (`"ptb"` | `"companion_standards"` | `"qualification_standard"`),
`fixture` (bool). Failures/blocked sources go under `pending` with a reason.

## Rules

- `corpus/raw/` files are never edited; re-acquisition overwrites only when the
  remote hash differs, and the manifest keeps the prior hash in a
  `superseded` list so revisions are detectable.
- Filenames: `<pms-number-normalized>_<POSITIONCODES>.pdf` (e.g.
  `pms311-103_ENGB.pdf`).
- Politeness: sequential downloads, no parallel hammering, identifying
  User-Agent; NWCG content is public domain (US federal work).
- The script is idempotent: a second run with nothing changed downloads
  nothing and leaves the manifest byte-identical except `generated`.

## Corpus refresh (added 2026-11-02)

A refresh is a full rerun of `acquire.py` then `acquire_requirements.py`
against the live NWCG catalog. Nothing is pinned to an earlier edition: the
manifest describes what NWCG publishes **today**, and every difference from
the previous manifest is recorded in the manifest itself, never absorbed
silently. A refresh is followed by the full downstream pipeline
(extract → db → match → adjudicate → report), per matching.spec.md's
"Re-running the pipeline".

### Per-document currency fields

Every `documents` entry carries, in addition to the manifest contract above:

- `edition_date` — ISO-8601 `YYYY-MM` (or `YYYY-MM-DD` when the source gives
  a day). Taken, in this order of preference, from: the catalog's
  "Date Published" column (catalog PTBs; it is already `YYYY-MM`) — unless
  it disagrees with the month printed on the PDF's page 1, in which case the
  printed month wins and the entry carries `edition_date_conflict`
  (observed 2026-11-02 on two otherwise unchanged books: EQTR, catalog
  2016-09 vs printed September 2024; FELB, catalog 2024-07 vs printed June
  2024); the
  "PMS <n> <Month YYYY>" line printed on page 1 (companion standards and
  PMS 310-1 — scanned with pdfplumber at download time, month name
  case-insensitive); the DOCX core-properties `modified` timestamp for the
  enhanced Google Doc (the export's only date — the document prints none).
  `edition_date_source` names which of these produced the value. A document
  with none of them records `null`, never a guess. Qualification-requirement
  web pages (source 4) have no published date and record `null` with
  `edition_date_source: "none"`.
- `page_count` for PDFs, so a republished edition's size change is visible
  in the manifest diff (e.g. STAM 17 → 11 pages, legacy → Next Gen).

### Change detection (per live catalog row, in `acquire.py`)

Identity of a document across refreshes is **(role, PMS number)** for
catalog PTBs and companion standards, and the filename for the Google Doc
exports — never the URL: NWCG renames its S3 keys between editions
(`taskbook/pms-311-16.pdf` → `taskbook/pms311-16.pdf`, September 2026), so a
URL-keyed match would silently lose the prior entry and its history.

- **Unchanged** — on-disk sha256 equals the manifest's: no download, entry
  kept verbatim (AC-A7).
- **Revised** — same identity, different content hash: the raw file is
  overwritten and the prior `{sha256, downloaded_at, url, edition_date}`
  is appended to the entry's `superseded` list. `edition_date`,
  `page_count` and `url` are refreshed from the live source.
- **Split / renamed** — the live row's position-code set differs from the
  prior entry's (e.g. PMS 311-30 was FEMO + FOBS in one legacy book; the
  September 2026 catalog lists 311-30 as FOBS alone and FEMO as the new
  311-71). The filename convention `<pms>_<CODES>.pdf` is derived from the
  live row, so the new book gets a new filename; the prior filename's entry
  is **retired** (below) with `superseded_by` naming every live filename
  that now covers one of its position codes.
- **Retired** — any prior `documents` entry whose identity no longer appears
  in the live catalog (or, for companion standards, is no longer referenced
  by any live Next Gen PTB) moves to the top-level `retired[]` list as
  `{filename, pms_number, position_codes, role, sha256, downloaded_at, url,
  edition_date, retired_at, reason, superseded_by}`. Its raw file is deleted
  from `corpus/raw/` and `extract.py` deletes the matching
  `extracted/<filename>.json`, so `db.py` can never load a book NWCG no
  longer publishes. Archived copies (Wayback Machine or similar) are NEVER
  used to keep a retired book in the corpus. `retired[]` is append-only
  across refreshes.
- **New** — a live row with no prior identity is downloaded and recorded as
  an ordinary entry (e.g. PMS 311-112 REAF, July 2025 — previously one of
  the seven "requirements page but no PTB" codes in PLAN.md).
- **Format change** — a book republished in a different format (legacy →
  Next Gen, the September 2026 batch) needs nothing from acquisition
  (`format` is assigned by extraction), but its companion-standards
  discovery now runs because the catalog hint reads "Next Gen", which is
  how PMS 350-12/-43/-44/-47/-48/-71/-93 enter the corpus.
- **Duplicate catalog rows** — the catalog can list one PMS number twice
  (311-12 CREP, two S3 keys, 2026-11-02). Identical content is one
  document: a single entry, the extra link kept under `alternate_urls`.
  Different content is a catalog conflict: the first row is kept and the
  second goes under `pending` with the reason. Never two entries for one
  filename.
- **Publication-page PDF links** — a companion standard's or PMS 310-1's
  PDF is accepted only when the link names the publication (`pms350-12`,
  `pms-350-51`); a publications page can link unrelated PDFs (the
  `pms310-1` page's only PDF is a mailing-list flyer), and recording one
  as the standard would be a false provenance claim. With no such link the
  document stays under `pending` with the reason.
- **Qualification-requirement pages** (source 4) — upstream wording drift
  (e.g. "Completion and Certification of NWCG Position Task Book for X" in
  `required_experience`) is tolerated: pages are re-scraped, re-parsed and
  re-committed; no `superseded` history is kept for them (idempotence
  exception above). A catalog position whose page disappears goes under
  `pending` with a reason.
- **Google Doc export nondeterminism** — the PDF export's hash can change
  while the DOCX export's does not (observed 2026-11-02). The DOCX is the
  extraction source, so a PDF-only hash change triggers no re-extraction;
  the entry is treated as *revised* (new hash recorded, prior hash under
  `superseded`) and the refresh log flags it as "pdf-only; docx unchanged".

Every run ends with a refresh summary on stderr: counts of unchanged /
revised / new / retired / pending, listing each revised, new and retired
filename. `acquire.py --verify-urls` additionally issues a HEAD request for
every `documents` entry's stored URL and reports any that does not return
HTTP 200 (used by AC-A10; not part of the default idempotent run, since it
is ~250 network requests that change nothing).

## Acceptance criteria

- [ ] AC-A1: Every PTB PDF link on the live catalog page has a corresponding
      manifest entry and a file in `corpus/raw/` whose sha256 matches.
- [ ] AC-A2: No file in `corpus/raw/` is zero-byte, HTML-content, or missing
      from the manifest.
- [ ] AC-A3: Every manifest entry for an S3-hosted document (all `role: "ptb"`
      catalog entries and `companion_standards`) preserves its `VersionId` in
      `url`. Exempt: the enhanced-PTB Google Doc export entries (source 2 —
      not S3 objects, no `VersionId`, verified instead by magic bytes) and
      source 4's per-position qualification-requirements pages (ordinary
      nwcg.gov webpages, not S3 objects).
- [ ] AC-A4: Multi-position PTBs carry all their position codes (spot-check
      PMS 311-10 → STCR, STEQ, STEN, TFLD; PMS 311-34 → FACL, COML, FDUL,
      GSUL, SPUL; PMS 311-18 → HLCO, ATGS).
- [ ] AC-A5: Every Next Gen PTB's referenced PMS 350-xxx standards document is
      present with `role: "companion_standards"`, or listed under `pending`
      with a reason.
- [ ] AC-A6: The Google Doc is present as exported PDF and DOCX with real
      (non-HTML, magic-byte-verified) content; if sharing regresses, recorded
      as `pending/blocked` with reason instead. ✅ satisfied 2026-07-09.
- [ ] AC-A7: Running `acquire.py` twice in a row produces no new downloads
      and no manifest diff (idempotence). This does not apply to
      `acquire_requirements.py` (source 4) — see AC-A8.
- [ ] AC-A8: Every position listed in the live NWCG Position Catalog has a
      manifest entry with `role: "qualification_standard"`,
      `pms_number: "310-1"`, a raw HTML file in `corpus/raw/requirements/`,
      and a structured JSON file in `extracted/requirements/`, or is listed
      under `pending` with a reason. Running `acquire_requirements.py` twice
      in a row produces byte-identical `extracted/requirements/*.json` files
      (the structured output), even though the raw HTML and its recorded
      sha256 are expected to differ between runs (see source 4's idempotence
      exception above) — that difference alone is not a failure.
- [ ] AC-A10 (refresh): after a refresh, `acquire.py --verify-urls` reports
      zero `documents` entries whose stored URL fails to return HTTP 200,
      and no PDF linked from the live catalog is missing from `documents`
      (AC-A1 re-run).
- [ ] AC-A11 (refresh): every filename present in the previous committed
      manifest's `documents` and absent from the new one appears in
      `retired[]` with a `reason` and a `superseded_by` list; every retired
      filename is absent from `corpus/raw/` and from `extracted/`.
- [ ] AC-A12 (refresh): every `role: "ptb"` and `role:
      "companion_standards"` entry has a non-null `edition_date` in
      `YYYY-MM` or `YYYY-MM-DD` form and an `edition_date_source`; for every
      catalog PTB the catalog's "Date Published" month equals the month
      printed on the PDF's page 1, OR the entry records the disagreement
      explicitly as `edition_date_conflict: {catalog, printed}` with the
      printed value chosen (the PDF is the document; the catalog column is
      metadata about it). A disagreement that is neither equal nor recorded
      is a FAIL — never a silent preference.
- [ ] AC-A9: Every `extracted/requirements/<code>.json` file's
      `required_experience_prereq_codes` never contains that same file's own
      `position_code` (no self-referential prerequisite).

## Changelog

- 2026-11-02 (corpus refresh): added the "Corpus refresh" section and
  AC-A10..A12. Triggered by the first re-acquisition since 2026-07-09, which
  found: 10 catalog PTBs republished (CREP, STAM, ORDM, RCDM, COMP, COST,
  GISS, DECK, ATIM as September 2026 Next Gen editions of what were
  2009/2022/2025 legacy books; FAL2 January → July 2026); the combined
  legacy `pms311-30_FEMO-FOBS.pdf` withdrawn upstream (its versioned S3 URL
  now returns NoSuchKey) and replaced by `pms311-30_FOBS.pdf` plus the new
  `pms311-71_FEMO.pdf`; new documents `pms311-112_REAF.pdf`, companion
  standards PMS 350-12/-43/-44/-47/-48/-71/-93/-112 (PMS 350-16/-30/-77/-85,
  cited by the September 2026 STAM/FOBS/GISS/DECK books, have no
  publication page yet — HTTP 404 — and stay under `pending`); the
  catalog listing CREP twice with identical content; the `pms310-1`
  publications page linking only an unrelated flyer (no PMS 310-1 PDF
  exists; the per-position pages remain the only source 4 path); a
  PDF-only hash change of the Google Doc export; and 10 of 116
  qualification-requirement pages with wording-only drift. Manifest schema
  additions: `edition_date`, `edition_date_source`, `page_count` per
  document; top-level `retired[]`; `superseded` entries now also carry
  `url` and `edition_date`. Identity for change detection changed from
  URL to (role, PMS number) because NWCG renamed its S3 keys. The first
  refresh also found two books whose catalog "Date Published" disagrees
  with the edition printed in the PDF (EQTR, FELB — see the currency-fields
  rule); both are recorded as `edition_date_conflict`. The Phase 0
  fixture set (FFT1, ENGB, CRWB, FIRB, LOFR) is unchanged by this refresh
  (hashes verified), so every fixture-grounded criterion in the other
  specs still holds.
