# F2 — ntft-bridge (runs in a clone of tbaugus/PTB_relationships, branch `ntft-bridge`)

## Problem
`data/ptb.sqlite` has 0 task equivalences touching any NTFT (official=0) position. The lattice connects PTB and FireTech only via 9 prerequisite edges. ASOP, ASWE, FDMS, FDSO, RBFE, SNTK have no NWCG link.

## User story
As a crew boss, when I look at Detection Systems Operator (FDSO), I see which of its tasks I have already demonstrated in NWCG positions, with the equivalence human-confirmed.

## Scope (reuse the existing pipeline; change defaults for nothing)
1. Inventory first, no changes: count pairs in `data/tier2_candidates.json` / `data/adjudications.json` with exactly one official=0 side; grep src/ and data/ for existing NTFT-specific logic; list official=0 `prerequisite_position` values that do not resolve to a `positions.code`. Report, then STOP for "proceed".
2. `specs/matching.spec.md`: append "NTFT bridge candidates". Rules: candidate iff one side has ≥1 official=0 occurrence and the other ≥1 official=1 occurrence; `CANDIDATE_THRESHOLD_NTFT = 0.60` (register differs; record justification); output `data/ntft_candidates.json` (same schema + `"bridge":"ntft"`); never merged into tier2; method string contains "ntft-bridge; cosine>=0.60"; verdicts land as `status='probable'`, never `confirmed`.
3. `match.py --ntft-bridge` flag → side filter + NTFT threshold + alternate output. Default behaviour unchanged; `tier2_candidates.json` stays byte-identical.
4. Run it. If > 400 candidates, raise to 0.65, rerun, record final threshold.
5. Adjudicate every candidate against the existing rubric; append to `adjudications.json` with `"bridge":"ntft"`. Conservative: operating a platform ≠ supervising people, even with shared nouns. `adjudicate.py apply`.
6. Fix CFMD prerequisite "FBAN / LTAN" → two rows FBAN, LTAN at the source JSON; note in schema.spec.md changelog; rebuild DB; re-apply.
7. `review_sheet.py export --bridge ntft` → `reports/ntft_review_sheet.xlsx` sorted by score, extra columns: NWCG position code(s), NTFT position code(s), NTFT task level. STOP — the human reviews the sheet.
8. After the human returns the sheet: `review_sheet.py ingest <path> --reviewer "Tabitha Baugus"`; `adjudicate.py apply`; verify confirmed > 0 with human_reviewed_at set; run `gap.py --qual CRWB --qual FFT1 --course S-230 --limit 15` and show NTFT slots satisfied via equivalence.
9. Commit, push branch, open PR with `gh pr create`, merge with `gh pr merge --squash` after the human says "merge". Then in firecorps-poc: `git subtree pull --prefix vendor/ptb_relationships https://github.com/tbaugus/PTB_relationships main --squash`, re-copy `data/ptb.sqlite`, update `vendor/UPSTREAM_SHA`, rerun F1 tests.

## Acceptance criteria
- AC-B1 every candidate has one official=0 side and one official=1 side.
- AC-B2 no candidate duplicates a tier2 pair_key.
- AC-B3 all candidates adjudicated; counts by relation printed; 0 confirmed before human review.
- AC-B4 CFMD prerequisites resolve to FBAN and LTAN.
- AC-B5 after ingest: ≥ 1 confirmed equivalence touching an NTFT task; every confirmed row has human_reviewed_at.
- AC-B6 gap.py shows ≥ 1 NTFT position with a slot satisfied via equivalence for the CRWB profile.
- AC-B7 upstream pytest green; default pipeline unchanged.

## Human involvement
Exactly two moments: "proceed" after the inventory, and the spreadsheet review (Confirm / Reject / Not sure per row; when in doubt, Not sure). Then "merge".
