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
- [ ] AC-A9: Every `extracted/requirements/<code>.json` file's
      `required_experience_prereq_codes` never contains that same file's own
      `position_code` (no self-referential prerequisite).
