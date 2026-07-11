# Format-Gap Evaluation

> Generated: 2026-07-11 &middot; corpus hash: `8932ca5034749688`
> Regenerated whole by `src/ptb/report.py` from `extracted/*.json` on every run. Never hand-edited - fix the classifier in report.py and regenerate.

## 1. Corpus & format census

- **NWCG Next Gen** (`nwcg_nextgen`): 39 document(s), 39 position(s), 864 task(s)
- **NWCG Legacy** (`nwcg_legacy`): 59 document(s), 70 position(s), 3201 task(s)
- **Enhanced (FireTech draft)** (`enhanced_gdoc`): 1 document(s), 11 position(s), 95 task(s)

## 2. Field-coverage matrix

Status legend: **captured** = the format's structure includes the field; **absent** = structurally missing
from the format (would require a format change); **blank-in-samples** = the structure exists but no sampled
document instance fills it. Blank is never conflated with absent - see the evidence appendix (section 7) for
the direct extraction evidence behind every cell.

| Field | NWCG Next Gen | NWCG Legacy | Enhanced (FireTech draft) |
|---|---|---|---|
| **Document-level** |  |  |  |
| `signature_page_initiation` | captured | captured | absent |
| `signature_page_verification` | captured | captured | captured |
| `signature_page_certification` | captured | captured | captured |
| `edition_date` | captured | captured | absent |
| `ips_reference` | captured | absent | absent |
| `prerequisite_buildup_statement` | absent | captured | absent |
| `trainee_ips_review_checkbox` | captured | absent | absent |
| `trainee_iqcs_number` | captured | absent | absent |
| **Task-level** |  |  |  |
| `task_number` | captured | captured | captured |
| `task_category` | captured | absent | absent |
| `task_behavior_grouping` | absent | captured | captured |
| `evaluation_context_code` | captured | captured | captured |
| `task_clarification_bullets` | absent | captured | absent |
| `performance_rating_scale` | captured | absent | absent |
| `per_task_completion_date` | absent | captured | captured |
| `per_task_evaluator_initials` | absent | captured | captured |
| `per_assignment_rating_columns` | captured | absent | absent |
| **Evaluation-record-level** |  |  |  |
| `virtual_assignment_flag` | captured | absent | absent |
| `ips_reviewed_flag` | captured | absent | absent |
| `evaluator_position_on_incident` | captured | captured | captured |
| `evaluator_iqcs_number` | captured | absent | absent |
| `evaluator_relevant_qualification` | captured | captured | absent |
| `incident_name` | captured | captured | captured |
| `incident_reference_code` | captured | captured | captured |
| `assignment_duration` | captured | captured | absent |
| `incident_kind` | captured | captured | absent |
| `location_geographic_area` | captured | captured | absent |
| `management_type` | captured | captured | captured |
| `rx_complexity_level` | captured | captured | captured |
| `fbps_fuel_model_group` | captured | captured | absent |
| `evaluator_recommendation_block` | captured | captured | captured |
| `remarks_narrative` | captured | absent | captured |
| **Enhanced-format additions** |  |  |  |
| `task_level_tier` | absent | absent | captured |
| `task_competency_grouping` | absent | absent | captured |
| `attaches_to_positions` | absent | absent | captured |
| `prerequisite_statement` | absent | absent | captured |
| `required_experience` | absent | absent | captured |
| `physical_fitness_requirement` | absent | absent | captured |
| `currency_requirement` | absent | absent | captured |
| `required_training_list` | absent | absent | captured |
| `training_source_provider` | absent | absent | captured |
| `training_approx_cost` | absent | absent | captured |
| `qualification_stack_by_tier` | absent | absent | captured |
| `employers_by_sector` | absent | absent | captured |
| `workforce_estimate` | absent | absent | captured |
| `officiality_disclaimer` | absent | absent | captured |
| `code_definitions_block` | captured | captured | captured |

## 3. Per-format assessment

### NWCG Next Gen (`nwcg_nextgen`)

39 documents, 864 tasks in this corpus.

**Captures** (28 fields): `signature_page_initiation`, `signature_page_verification`, `signature_page_certification`, `edition_date`, `ips_reference`, `trainee_ips_review_checkbox`, `trainee_iqcs_number`, `task_number`, `task_category`, `evaluation_context_code`, `performance_rating_scale`, `per_assignment_rating_columns`, `virtual_assignment_flag`, `ips_reviewed_flag`, `evaluator_position_on_incident`, `evaluator_iqcs_number`, `evaluator_relevant_qualification`, `incident_name`, `incident_reference_code`, `assignment_duration`, `incident_kind`, `location_geographic_area`, `management_type`, `rx_complexity_level`, `fbps_fuel_model_group`, `evaluator_recommendation_block`, `remarks_narrative`, `code_definitions_block`.

**Structurally absent** (19 fields): `prerequisite_buildup_statement`, `task_behavior_grouping`, `task_clarification_bullets`, `per_task_completion_date`, `per_task_evaluator_initials`, `task_level_tier`, `task_competency_grouping`, `attaches_to_positions`, `prerequisite_statement`, `required_experience`, `physical_fitness_requirement`, `currency_requirement`, `required_training_list`, `training_source_provider`, `training_approx_cost`, `qualification_stack_by_tier`, `employers_by_sector`, `workforce_estimate`, `officiality_disclaimer`.

On its own, a Next Gen PTB tells you *how well* a trainee performed each task (N/O-D-M-E per assignment) but not *when* any individual task was actually completed - that granularity was traded away for the assignment-level rating scale. Task detail itself lives in the companion PMS 350-xxx Incident Position Standards, not this document.


### NWCG Legacy (`nwcg_legacy`)

59 documents, 3201 tasks in this corpus.

**Captures** (23 fields): `signature_page_initiation`, `signature_page_verification`, `signature_page_certification`, `edition_date`, `prerequisite_buildup_statement`, `task_number`, `task_behavior_grouping`, `evaluation_context_code`, `task_clarification_bullets`, `per_task_completion_date`, `per_task_evaluator_initials`, `evaluator_position_on_incident`, `evaluator_relevant_qualification`, `incident_name`, `incident_reference_code`, `assignment_duration`, `incident_kind`, `location_geographic_area`, `management_type`, `rx_complexity_level`, `fbps_fuel_model_group`, `evaluator_recommendation_block`, `code_definitions_block`.

**Structurally absent** (24 fields): `ips_reference`, `trainee_ips_review_checkbox`, `trainee_iqcs_number`, `task_category`, `performance_rating_scale`, `per_assignment_rating_columns`, `virtual_assignment_flag`, `ips_reviewed_flag`, `evaluator_iqcs_number`, `remarks_narrative`, `task_level_tier`, `task_competency_grouping`, `attaches_to_positions`, `prerequisite_statement`, `required_experience`, `physical_fitness_requirement`, `currency_requirement`, `required_training_list`, `training_source_provider`, `training_approx_cost`, `qualification_stack_by_tier`, `employers_by_sector`, `workforce_estimate`, `officiality_disclaimer`.

On its own, a legacy PTB tells you *when* each task was completed and by whom (initials + date, per task) but carries no performance-quality signal beyond a bare completion mark - there is no way to distinguish a task performed adequately from one performed exceptionally. Remarks are pushed out to a separate 'Individual Performance Evaluation' attachment rather than living inline.


### Enhanced (FireTech draft) (`enhanced_gdoc`)

1 documents, 95 tasks in this corpus.

**Captures** (29 fields): `signature_page_verification`, `signature_page_certification`, `task_number`, `task_behavior_grouping`, `evaluation_context_code`, `per_task_completion_date`, `per_task_evaluator_initials`, `evaluator_position_on_incident`, `incident_name`, `incident_reference_code`, `management_type`, `rx_complexity_level`, `evaluator_recommendation_block`, `remarks_narrative`, `task_level_tier`, `task_competency_grouping`, `attaches_to_positions`, `prerequisite_statement`, `required_experience`, `physical_fitness_requirement`, `currency_requirement`, `required_training_list`, `training_source_provider`, `training_approx_cost`, `qualification_stack_by_tier`, `employers_by_sector`, `workforce_estimate`, `officiality_disclaimer`, `code_definitions_block`.

**Structurally absent** (18 fields): `signature_page_initiation`, `edition_date`, `ips_reference`, `prerequisite_buildup_statement`, `trainee_ips_review_checkbox`, `trainee_iqcs_number`, `task_category`, `task_clarification_bullets`, `performance_rating_scale`, `per_assignment_rating_columns`, `virtual_assignment_flag`, `ips_reviewed_flag`, `evaluator_iqcs_number`, `evaluator_relevant_qualification`, `assignment_duration`, `incident_kind`, `location_geographic_area`, `fbps_fuel_model_group`.

On its own, an enhanced_gdoc entry tells you the most about *readiness*: training source, approximate cost, a four-tier progression stack, and currency - none of which any NWCG PTB carries in the document itself (NWCG defers all of this to the external PMS 310-1 qualification-requirements pages). It is explicitly NOT an official qualification record: every downstream use must carry the draft/`official=false` label.



## 4. Cross-format reconciliation analysis

**Performance-rating gap (`performance_rating_scale`).** Next Gen (captured) records an N/O-D-M-E rating per task per assignment; legacy (absent_from_format) and enhanced_gdoc (absent_from_format) record only a binary completion mark (evaluator initials + date). A candidate whose history spans a legacy PTB and a Next Gen PTB cannot be given one rating-quality score across their whole career. Reconciling requires an explicit, human-made choice between at least these options, each with a real trade-off:
  1. **Treat legacy completions as rating-unknown.** Preserves honesty (no rating was ever recorded) but means any 'average performance rating' query silently excludes legacy-era tasks, understating candidates with older career history.
  2. **Treat legacy completions as M-equivalent ('Meets').** Lets every task contribute to a single rollup score, but M was never actually assigned - this imputes a value the source data does not contain, which cuts against this whole project's no-imputation principle and should only be adopted with that trade-off stated explicitly wherever the number is shown.
  3. **Keep two separate fields (completion + rating-if-known) and never collapse them into one score.** Most faithful to the source data; pushes the interpretation burden onto whatever UI or report consumes candidate history, which must display 'rating unknown' rather than a blank.
This project takes no position on which option a future app should choose - it is recorded here so that whoever builds the candidate-facing rollup makes the choice consciously.

**Task-detail externalization (`task_clarification_bullets` / `ips_reference`).** These two fields are mirror images of each other: legacy inlines clarifying detail as sub-bullets under each task and cites no external standard; Next Gen strips clarifying detail out of the task list entirely and points to the companion PMS 350-xxx Incident Position Standards instead. A tool that wants to show 'what does this task actually mean' has to look in two different places depending on which format produced the PTB - either the task's own `clarifications` array, or a fetch of the cited IPS document (which this corpus does not contain and would need to be acquired separately).

**Readiness fields the NWCG formats externalize (`task_level_tier`, `currency_requirement`, `physical_fitness_requirement`, `required_training_list`, `qualification_stack_by_tier`).** Only enhanced_gdoc captures these inside the PTB document itself. For the two official NWCG formats this data is not simply missing from the corpus - it lives in each position's PMS 310-1 qualification-requirements page (see `position_requirements` in the database, loaded from a wholly separate acquisition source). Reconciling a unified 'readiness' view therefore means joining two different documents for NWCG positions (PTB + PMS 310-1 page) but reading only one for enhanced_gdoc positions - a real structural asymmetry, not a gap to be filled inside this report.

**`O`-code definition collision (`code_definitions_block`).** All three formats capture a code_definitions_block (each restates what its codes mean), but the definitions are not interchangeable: NWCG's Next Gen and legacy formats both define `O` = 'Other: any situation (classroom, simulation, daily job, incident, prescribed fire, etc.)', while enhanced_gdoc redefines `O` = 'Developmental / non-incident setting (engineering & development roles) - framework extension' (see enhanced_ptbs_gdoc.pdf p.1). A task coded `O` in an enhanced_gdoc draft position does NOT mean the same thing as a task coded `O` in an official NWCG PTB. matching.spec.md's context-satisfaction rules already treat these as distinct per-format vocabularies; this report flags it again here because it is exactly the kind of silent misread a naive cross-format rollup could introduce if someone joined the two formats' `O`-coded tasks without checking which code_definitions_block produced them.

**Officiality (`officiality_disclaimer`).** Enhanced_gdoc positions are drafts, not NWCG standards; `document.official=false` is the only place that distinction lives in the data. Any surface that merges enhanced_gdoc positions with official NWCG positions (e.g. the gap-analysis 'closest positions' query) must keep carrying and displaying this flag - collapsing it away would let a draft, illustrative position look like a real qualification pathway.


## 5. Intra-format variance findings

- `trainee_ips_review_checkbox` in NWCG Next Gen: observed in 24/39 documents, not all - intra-format variance, not a bug (see evidence appendix).
- `ips_reviewed_flag` in NWCG Next Gen: observed in 23/39 documents, not all - intra-format variance, not a bug (see evidence appendix).
- `ips_reference` in NWCG Next Gen: observed in 37/39 documents, not all - intra-format variance, not a bug (see evidence appendix).
- `prerequisite_buildup_statement` in NWCG Legacy: observed in 4/59 documents, not all - intra-format variance, not a bug (see evidence appendix).
- `edition_date` in NWCG Legacy: observed in 52/59 documents, not all - intra-format variance, not a bug (see evidence appendix).

## 6. No imputed values

Every status and evidence string above was read directly from `extracted/*.json` - either a `fields_observed`
marker match with a page citation, or a first-class field already present on the Task/Position/DocumentMeta
extraction models (models.py). No field's status was inferred from general knowledge of NWCG PTBs without a
direct evidence citation; where the extraction layer's own fields_observed detectors did not yet cover a
field required by this spec, `extract.py`'s marker set was extended (documented in
`specs/extraction.spec.md`'s Changelog) and grounded in a literal, page-verified substring from the fixture
PDFs before any row here was generated. No cell was filled with a default, a guess, or a value carried over
from a different format.

## 7. Evidence appendix (every field &times; format cell)

### `signature_page_initiation`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.1 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.1 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `signature_page_verification`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.1 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.2 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.4 (observed in all 1/1 enhanced_gdoc documents)

### `signature_page_certification`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.1 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.2 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.5 (observed in all 1/1 enhanced_gdoc documents)

### `edition_date`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.1 edition_date='MAY 2024'
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.1 edition_date='JUNE 2010'; intra-format variance: 52/59 documents have a parseable edition date
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx); enhanced_ptbs_gdoc.pdf has 0 occurrences of 'PMS' anywhere (no PMS-numbered edition-date convention exists for this draft format) and build_enhanced_document() hardcodes edition_date=None without attempting extraction - a genuine format difference, not sample blankness

### `ips_reference`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.2 ips_reference='350-98'; 2 documents have no companion IPS (pms311-119_FAL3.pdf, pms311-91_FAL2.pdf - confirmed no PMS 350-xxx standard exists, see PLAN.md Phase 1 known gaps)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more); 0 have ips_reference - legacy externalizes task detail via inline clarification bullets instead of an external IPS reference
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx); 0 have ips_reference - enhanced_gdoc drafts cite no official external IPS document

### `prerequisite_buildup_statement`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen documents (pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.1; intra-format variance: observed in 4/59 nwcg_legacy documents (checked all 59: pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `trainee_ips_review_checkbox`
- **NWCG Next Gen** (captured): pms311-103_ENGB.pdf p.5; intra-format variance: observed in 24/39 nwcg_nextgen documents (checked all 39: pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `trainee_iqcs_number`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.1 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `task_number`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.5 task #1 (task_number required non-null on every task)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.6 task #1 (task_number required non-null on every task)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 task #1 (task_number required non-null on every task)

### `task_category`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.5 category='Leadership Level 2, New Leader (Convey Intent)' (Next Gen functional category heading)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more); the `category` JSON slot holds the legacy Behavior: heading text (task_behavior_grouping), not a Next Gen functional category
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx); e.g. enhanced_ptbs_gdoc.docx p.3 category='COMPETENCY: Assume position responsibilities. Successfully a'...; the `category` slot holds a COMPETENCY heading (task_competency_grouping), not a Next Gen functional category

### `task_behavior_grouping`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen documents (pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more); Next Gen has no Behavior:-heading grouping level (category only)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.6 category='Ensure readiness for assignment.' (legacy 'Behavior:' heading, stored in the `category` slot per extraction.spec.md's output contract)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 behavior='Ensure readiness for assignment' (Behavior: subheading, stored in the `behavior` slot)

### `evaluation_context_code`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.5 task #1 code_raw='ALL' (code_raw/code_alternatives required non-empty on every task)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.6 task #1 code_raw='O' (code_raw/code_alternatives required non-empty on every task)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 task #1 code_raw='W/RX' (code_raw/code_alternatives required non-empty on every task)

### `task_clarification_bullets`
- **NWCG Next Gen** (absent_from_format): checked all 864 nwcg_nextgen tasks across 39 documents; 0 have clarifications - Next Gen moves task detail to the external IPS document
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.6 task #1 clarifications=['Appropriate references for the incident (e.g., PMS 410-1, Fireline Handbook)'] (1961/3201 legacy tasks have clarification bullets; the rest genuinely have none printed)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 95 enhanced_gdoc tasks across 1 documents; 0 have clarifications - no clarification-bullet structure in this format's task rows

### `performance_rating_scale`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.2 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `per_task_completion_date`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen documents (pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.6 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.1 (observed in all 1/1 enhanced_gdoc documents)

### `per_task_evaluator_initials`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen documents (pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.6 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 (observed in all 1/1 enhanced_gdoc documents)

### `per_assignment_rating_columns`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.5 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `virtual_assignment_flag`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `ips_reviewed_flag`
- **NWCG Next Gen** (captured): pms311-103_ENGB.pdf p.8; intra-format variance: observed in 23/39 nwcg_nextgen documents (checked all 39: pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `evaluator_position_on_incident`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.18 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.2 (observed in all 1/1 enhanced_gdoc documents)

### `evaluator_iqcs_number`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `evaluator_relevant_qualification`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.5 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `incident_name`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.4 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.4 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.2 (observed in all 1/1 enhanced_gdoc documents)

### `incident_reference_code`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.18 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.2 (observed in all 1/1 enhanced_gdoc documents)

### `assignment_duration`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.4 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.4 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `incident_kind`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.4 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.4 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `location_geographic_area`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.18 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `management_type`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.4 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.2 (observed in all 1/1 enhanced_gdoc documents)

### `rx_complexity_level`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.4 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.4 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.2 (observed in all 1/1 enhanced_gdoc documents)

### `fbps_fuel_model_group`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.4 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.5 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (absent_from_format): checked all 1 enhanced_gdoc documents (enhanced_ptbs_gdoc.docx)

### `evaluator_recommendation_block`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.9 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.18 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.4 (observed in all 1/1 enhanced_gdoc documents)

### `remarks_narrative`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.4 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.2 (observed in all 1/1 enhanced_gdoc documents)

### `task_level_tier`
- **NWCG Next Gen** (absent_from_format): checked all 864 nwcg_nextgen tasks across 39 documents; 0 have a Level tier
- **NWCG Legacy** (absent_from_format): checked all 3201 nwcg_legacy tasks across 59 documents; 0 have a Level tier
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 task #1 level='Aspirant' (95/95 enhanced_gdoc tasks carry a Level tier)

### `task_competency_grouping`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen documents (pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more); no two-level competency->behavior hierarchy in this format
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more); no two-level competency->behavior hierarchy in this format
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 category='COMPETENCY: Assume position responsibilities. Successfully a'... + behavior='Ensure readiness for assignment' (two-level COMPETENCY -> Behavior hierarchy)

### `attaches_to_positions`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; 0 have attaches_to
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; 0 have attaches_to
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS attaches_to=['UASP', 'FIRB'] (5/11 enhanced_gdoc positions link to an official NWCG position)

### `prerequisite_statement`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; 0 have requirements_text
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; 0 have requirements_text
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS requirements_text='Unmanned Aircraft System Pilot (UASP), qualified; Firing Boss, Single Resource ('... (11/11 positions)

### `required_experience`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; extra_fields.required_experience absent on all (Required experience lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; extra_fields.required_experience absent on all (Required experience lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS extra_fields.required_experience="Satisfactory performance as UASP on \u2265X incidents; participation in \u2265X ignition operations... (11/11 positions)

### `physical_fitness_requirement`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; extra_fields.physical_fitness absent on all (Physical fitness requirement lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; extra_fields.physical_fitness absent on all (Physical fitness requirement lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS extra_fields.physical_fitness="Light to Moderate."... (11/11 positions)

### `currency_requirement`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; extra_fields.currency absent on all (Currency requirement lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; extra_fields.currency absent on all (Currency requirement lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS extra_fields.currency="RT-373 (triennial); \u22651 aerial ignition mission per 3 years; maintain UASP currency."... (11/11 positions)

### `required_training_list`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; extra_fields.required_training absent on all (Required training list lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; extra_fields.required_training absent on all (Required training list lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS extra_fields.required_training=[{"training": "FAA Part 107 Remote Pilot Certificate", "source_provider": "FAA knowledge test (PSI/C... (11/11 positions)

### `training_source_provider`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; no required_training structure at all (training requirements live on the separate PMS 310-1 qualification-requirements page, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; no required_training structure at all (training requirements live on the separate PMS 310-1 qualification-requirements page, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS required_training[].source_provider='FAA knowledge test (PSI/CATS centers); prep via Pilot Institute / Drone Pilot Ground School'

### `training_approx_cost`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; no required_training structure at all (training requirements live on the separate PMS 310-1 qualification-requirements page, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; no required_training structure at all (training requirements live on the separate PMS 310-1 qualification-requirements page, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS required_training[].approx_cost='$175 test; prep $100–300; recurrent free'

### `qualification_stack_by_tier`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; extra_fields.qualification_stack absent on all (Qualification stack lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; extra_fields.qualification_stack absent on all (Qualification stack lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS extra_fields.qualification_stack={"Aspirant": "Interest in UAS/fire ops; ICS-100; basic fireline & aviation safety awareness.", "Begi... (11/11 positions)

### `employers_by_sector`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; extra_fields.employers_by_sector absent on all (Employers by sector lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; extra_fields.employers_by_sector absent on all (Employers by sector lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS extra_fields.employers_by_sector={"Private": "Drone Amplified (IGNIS); UAS service & prescribed-burn contractors; utility vegetation ... (11/11 positions)

### `workforce_estimate`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen positions across 39 documents; extra_fields.workforce_estimate absent on all (Workforce estimate lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **NWCG Legacy** (absent_from_format): checked all 70 nwcg_legacy positions across 59 documents; extra_fields.workforce_estimate absent on all (Workforce estimate lives on the separate PMS 310-1 qualification-requirements page for these positions, not this PTB document)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.3 position UAIS extra_fields.workforce_estimate="Approx. number performing this work in the USA (any title): ~100\u2013300 and growing (rough estima... (11/11 positions)

### `officiality_disclaimer`
- **NWCG Next Gen** (absent_from_format): checked all 39 nwcg_nextgen documents (pms-311-98_CRWB.pdf, pms311-103_ENGB.pdf, pms311-105_FIRB.pdf, pms311-107_FELB.pdf, + 35 more); document.official is hardcoded true for every NWCG-published document, no disclaimer concept
- **NWCG Legacy** (absent_from_format): checked all 59 nwcg_legacy documents (pms-311-05_LOFR.pdf, pms311-02_ICT3.pdf, pms311-03_ICT4.pdf, pms311-09_DIVS.pdf, + 55 more); document.official is hardcoded true for every NWCG-published document, no disclaimer concept
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.1 document.official=False (self-describes as illustrative draft, NOT an official NWCG standard)

### `code_definitions_block`
- **NWCG Next Gen** (captured): pms-311-98_CRWB.pdf p.3 (observed in all 39/39 nwcg_nextgen documents)
- **NWCG Legacy** (captured): pms-311-05_LOFR.pdf p.3 (observed in all 59/59 nwcg_legacy documents)
- **Enhanced (FireTech draft)** (captured): enhanced_ptbs_gdoc.docx p.1 (observed in all 1/1 enhanced_gdoc documents)

