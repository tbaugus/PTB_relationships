# Operating the PTB Relationships System

This is a reference for running the system day-to-day. For how it was built, see `PLAN.md`; for the underlying rules, see `specs/*.md`.

## What you have

A SQLite database (`data/ptb.sqlite`) built from 99 Position Task Book documents (NWCG Next Gen, NWCG Legacy, and 11 draft "FireTech" positions), plus two pure-Python query layers on top of it:

- **`src/ptb/gap.py`** — given a candidate's held qualifications, completed courses, and completed tasks, tells you which positions they're closest to qualifying for, and exactly which tasks/requirements remain (or are already waived via a prerequisite chain).
- **`src/ptb/report.py`** — tells you what each of the three document formats can and cannot tell you (`reports/format_gaps.md`).

Nothing here makes a certification decision. Every gap-analysis result carries the disclaimer: *"This report shows demonstrated-task overlap and requirement gaps only... not a certification decision."*

## Running a gap-analysis query

```
py src/ptb/gap.py --qual ENGB --course S-230 --task 12:wildfire --limit 10
```

- `--qual` — a position code the candidate already holds (repeatable: `--qual ENGB --qual FFT1`)
- `--course` — a completed course code (repeatable)
- `--task` — a completed task, as `position_task_id:context` where context is one of `wildfire`, `prescribed_fire`, `incident`, `simulation`, `rare_event`, `other`, `developmental` (repeatable). `position_task_id` is the `position_tasks.id` row in the database — look it up with `sqlite3 data/ptb.sqlite "select id, task_number, verbatim_text from position_tasks where position_id = (select id from positions where code='ENGB')"`.
- `--json` — print structured output instead of the text report (for feeding into another tool)

The output ranks positions by fewest remaining gaps, and separately calls out which requirements were waived and *why* (`implied_by ENGB` or `conferred_by ENGB`), so a reviewer can see and override the reasoning.

For programmatic use (a future app, a notebook, a script), call `closest_positions(profile)` from `src.ptb.gap` directly — it's a pure function over an open `sqlite3.Connection`, no side effects.

## Regenerating the corpus (only when NWCG source documents change)

Run in this exact order; each step is idempotent and safe to re-run:

```
py src/ptb/acquire.py               # re-scrape NWCG catalog, download changed PDFs
py src/ptb/acquire_requirements.py  # re-scrape qualification-requirements pages
py src/ptb/extract.py               # re-run structuring on every corpus/raw document
py src/ptb/db.py                    # rebuild data/ptb.sqlite from extracted/*.json
py src/ptb/match.py                 # regenerate tier-2 candidate pairs
py src/ptb/adjudicate.py            # apply existing verdicts; flags any brand-new pairs
py src/ptb/report.py                # regenerate reports/format_gaps.md
```

If `adjudicate.py` exits with code 2, it found pairs never adjudicated before — hand `data/pending_adjudication.json` to Claude to adjudicate against `specs/matching.spec.md`'s rubric, then re-run. Existing human confirmations (`data/confirmations.json`) and Claude verdicts (`data/adjudications.json`) are keyed by task text, so they survive a full rebuild automatically.

## The human-review step (tier-2 task equivalences)

863 "probable" task-equivalence pairs are pending your one-time sign-off — until reviewed, `gap.py` treats them as *not* satisfying anything (conservative default).

**Technical reviewer:**
```
py src/ptb/adjudicate.py promote <pair_key> confirm --note "..."
py src/ptb/adjudicate.py promote <pair_key> reject --note "..."
```
Work through `reports/tier2_review_checklist.md`, highest-similarity pairs first.

**Non-technical / SME reviewer (spreadsheet):**
```
py src/ptb/review_sheet.py export                          # writes reports/tier2_review_sheet.xlsx
# upload to Google Sheets, have the SME fill the Confirm/Reject/Not-sure column, download as .xlsx
py src/ptb/review_sheet.py ingest <downloaded.xlsx> --reviewer "Name"
```
Safe to re-ingest a corrected sheet — newest decision per pair wins. Rows left "Not sure" or blank stay probable and reappear on the next export.

## Things to never hand-edit

`extracted/*.json`, `reports/format_gaps.md`, `reports/tier2_review_checklist.md`, `data/ptb.sqlite`, `corpus/manifest.json` — all regenerated. If one looks wrong, fix the script that produces it (`extract.py`, `report.py`, `adjudicate.py`, `db.py`, `acquire.py` respectively) and re-run. `data/adjudications.json` and `data/confirmations.json` are the only hand-safe (append-only) data files, and even those are normally written by `adjudicate.py`/`review_sheet.py`, not edited directly.

## Known caveats to communicate to anyone using this

- Zero tier-2 pairs are confirmed yet (your review is still pending) — until then, `gap.py`'s "remaining gaps" counts are the *most conservative* possible reading; they will shrink as you confirm equivalent tasks.
- Draft "FireTech" positions (`enhanced_gdoc`, `official=False`) are illustrative, not real NWCG qualifications — `gap.py` labels them `(draft position — not an official NWCG standard)` in every report; don't let anyone mistake one for a real pathway.
- Seven codes (AREP, EDRC, FFT2, IARR, OPS3, PIOT, REAF) have qualification requirements but no PTB in this corpus, so they never appear as a "closest position" target.
