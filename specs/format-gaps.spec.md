# Spec: Format-Gap Evaluation

**Implements:** `src/ptb/report.py` (Phase 6)
**Principle:** evaluate, never impute. The output states what each format
captures, what it structurally lacks, and what reconciling would take —
it never fills a missing value.

## Field inventory (grounded in fixtures; extraction's `fields_observed` uses these names)

Document-level: `signature_page_initiation`, `signature_page_verification`,
`signature_page_certification`, `edition_date`, `ips_reference`,
`prerequisite_buildup_statement` (legacy cover: "builds on tasks from previous
prerequisite position task books"), `trainee_ips_review_checkbox`,
`trainee_iqcs_number`.

Task-level: `task_number`, `task_category` (Next Gen functional category),
`task_behavior_grouping` (legacy "Behavior:" heading), `evaluation_context_code`,
`task_clarification_bullets`, `performance_rating_scale` (N/O-D-M-E),
`per_task_completion_date`, `per_task_evaluator_initials`,
`per_assignment_rating_columns`.

Evaluation-record-level: `virtual_assignment_flag`, `ips_reviewed_flag`,
`evaluator_position_on_incident`, `evaluator_iqcs_number`,
`evaluator_relevant_qualification`, `incident_name`, `incident_reference_code`,
`assignment_duration`, `incident_kind`, `management_type`,
`rx_complexity_level`, `fbps_fuel_model_group`, `location_geographic_area`,
`evaluator_recommendation_block`, `remarks_narrative`.

Enhanced-format additions (observed in enhanced_ptbs_gdoc, 2026-07-09 —
statuses for the two NWCG formats to be verified, expected absent_from_format
in both): `task_level_tier`, `task_competency_grouping` (two-level
competency→behavior hierarchy), `attaches_to_positions`,
`prerequisite_statement`, `required_experience`, `physical_fitness_requirement`,
`currency_requirement`, `required_training_list`, `training_source_provider`,
`training_approx_cost`, `qualification_stack_by_tier`, `employers_by_sector`,
`workforce_estimate`, `officiality_disclaimer`, `code_definitions_block`
(the format restates code meanings — and redefines `O`).

The inventory grows as extraction meets new formats; additions are appended
here with the observing document cited.

## Grounded expectations (must appear in the matrix exactly like this)

- `performance_rating_scale`: captured in nwcg_nextgen; **absent_from_format**
  in nwcg_legacy (legacy is binary completion — this is the single largest
  semantic gap between formats and the narrative must discuss it).
- `per_task_completion_date` + `per_task_evaluator_initials`: captured in
  nwcg_legacy; absent_from_format in nwcg_nextgen (Next Gen records ratings
  per assignment column, not per-task dates).
- `task_clarification_bullets`: captured in nwcg_legacy; absent in nextgen
  (moved to the external IPS document — `ips_reference` is the inverse).
- `virtual_assignment_flag`, `fbps_fuel_model_group`, `management_type`:
  captured in nwcg_nextgen; verify legacy evaluation-record pages before
  assigning status (do not assume).
- `trainee_ips_review_checkbox`: captured in ENGB/FFT1/FIRB but CRWB uses a
  footnote instead — the matrix is per-FORMAT, so this becomes `captured`
  for nwcg_nextgen with the intra-format variance NOTED in evidence and
  narrative (variance within a format is a first-class finding).
- `task_level_tier`, `currency_requirement`, `physical_fitness_requirement`,
  `required_training_list` (with source + cost), `qualification_stack_by_tier`:
  captured in enhanced_gdoc; expected absent_from_format in BOTH NWCG formats
  (verify, don't assume) — the narrative must discuss that the enhanced format
  is the only one modeling progression tiers, currency, and training cost,
  i.e., the candidate-facing readiness fields the NWCG formats externalize to
  PMS 310-1 or omit entirely.
- `per_task_completion_date`/`per_task_evaluator_initials`: also captured in
  enhanced_gdoc (it uses legacy-style completion), making nwcg_nextgen the
  odd one out on per-task dates.
- `officiality_disclaimer`: captured ONLY in enhanced_gdoc; the narrative must
  state that enhanced positions are drafts, not NWCG standards, and that the
  app must label them as such wherever surfaced.
- `code_definitions_block`: the enhanced format redefines code `O`
  (developmental/non-incident) vs NWCG `O` (any situation) — a semantic
  collision the narrative must flag for anyone comparing contexts across
  formats.

## Matrix rules

- One row per (format, field_name) covering the full inventory ×
  {nwcg_nextgen, nwcg_legacy, enhanced_gdoc}.
- Status semantics: `captured` = the format's structure includes the field;
  `absent_from_format` = structurally missing (would require a format change);
  `present_but_blank_in_samples` = structure exists, no sampled instance
  fills it. **Blank ≠ absent — conflating them is a spec violation.**
- Every row's `evidence` cites ≥ 1 document + page. `absent_from_format`
  requires evidence that the whole format was checked (all corpus documents
  of that format, stated in evidence).
- All three formats are now available (enhanced_gdoc unblocked 2026-07-09);
  should a format ever be unavailable, it gets NO rows and is listed as
  pending — absence of rows ≠ absence of fields.

## Narrative report (`reports/format_gaps.md`, generated)

Sections: (1) corpus + format census; (2) the matrix, rendered; (3) per-format
assessment — what the format alone can and cannot tell you about a candidate;
(4) cross-format reconciliation analysis — for each field captured in one
format and absent in another: what is lost when candidate histories span
formats, and what reconciling would require (e.g., legacy completions carry
no performance rating: any unified candidate model must either treat legacy
completion as rating-unknown or M-equivalent — presented as OPTIONS with
trade-offs, never chosen silently); (5) intra-format variance findings;
(6) explicit statement that no values were imputed. Regenerated whole from
the database on every run; a regeneration stamp (date + corpus hash) at top.

## Acceptance criteria

- [ ] AC-F1: Matrix covers the full inventory × all three formats.
- [ ] AC-F2: All grounded expectations above appear exactly as stated
      (including the enhanced-format rows and the `O`-code collision note).
- [ ] AC-F3: Every `absent_from_format` row's evidence enumerates the
      documents checked; every row cites document + page.
- [ ] AC-F4: No `present_but_blank_in_samples` is used where structure is
      genuinely missing (spot-check against fixtures).
- [ ] AC-F5: The report contains reconciliation options with trade-offs for
      the rating-scale gap, and contains no imputed values (checker greps
      for value-filling language and verifies section 6).
- [ ] AC-F6: Report regenerates byte-identically from an unchanged database
      (except the regeneration stamp).
