"""Phase 6 acceptance tests: specs/format-gaps.spec.md AC-F1 through AC-F6."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import report  # noqa: E402

REPORT_PATH = REPO_ROOT / "reports" / "format_gaps.md"


@pytest.fixture(scope="module")
def corpus() -> report.Corpus:
    return report.Corpus()


@pytest.fixture(scope="module")
def rows(corpus: report.Corpus) -> list[dict]:
    return report.build_field_coverage(corpus)


@pytest.fixture(scope="module")
def lookup(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return report._row_lookup(rows)


# --- AC-F1: matrix covers the full inventory x all three formats ------------


def test_ac_f1_full_inventory_times_all_formats(rows: list[dict]) -> None:
    seen = {(r["format"], r["field_name"]) for r in rows}
    expected = {(fmt, field) for fmt in report.FORMATS for field in report.FIELD_INVENTORY}
    assert seen == expected


def test_ac_f1_every_row_has_valid_status(rows: list[dict]) -> None:
    valid = {"captured", "absent_from_format", "present_but_blank_in_samples"}
    for r in rows:
        assert r["status"] in valid


# Copied verbatim from format-gaps.spec.md's "Field inventory" section, so a
# field silently dropped from report.py's FIELD_INVENTORY (as
# location_geographic_area was until a spec-checker audit caught it) fails
# this test even though it can't fail test_ac_f1_full_inventory_times_all_formats
# (that test only checks self-consistency against report.py's own list).
SPEC_FIELD_INVENTORY = {
    "signature_page_initiation",
    "signature_page_verification",
    "signature_page_certification",
    "edition_date",
    "ips_reference",
    "prerequisite_buildup_statement",
    "trainee_ips_review_checkbox",
    "trainee_iqcs_number",
    "task_number",
    "task_category",
    "task_behavior_grouping",
    "evaluation_context_code",
    "task_clarification_bullets",
    "performance_rating_scale",
    "per_task_completion_date",
    "per_task_evaluator_initials",
    "per_assignment_rating_columns",
    "virtual_assignment_flag",
    "ips_reviewed_flag",
    "evaluator_position_on_incident",
    "evaluator_iqcs_number",
    "evaluator_relevant_qualification",
    "incident_name",
    "incident_reference_code",
    "assignment_duration",
    "incident_kind",
    "management_type",
    "rx_complexity_level",
    "fbps_fuel_model_group",
    "evaluator_recommendation_block",
    "remarks_narrative",
    "location_geographic_area",
    "task_level_tier",
    "task_competency_grouping",
    "attaches_to_positions",
    "prerequisite_statement",
    "required_experience",
    "physical_fitness_requirement",
    "currency_requirement",
    "required_training_list",
    "training_source_provider",
    "training_approx_cost",
    "qualification_stack_by_tier",
    "employers_by_sector",
    "workforce_estimate",
    "officiality_disclaimer",
    "code_definitions_block",
}


def test_ac_f1_matches_spec_field_inventory_verbatim() -> None:
    assert set(report.FIELD_INVENTORY) == SPEC_FIELD_INVENTORY


# --- AC-F2: grounded expectations appear exactly as stated ------------------


def test_ac_f2_performance_rating_scale(lookup: dict) -> None:
    assert lookup[("nwcg_nextgen", "performance_rating_scale")]["status"] == "captured"
    assert lookup[("nwcg_legacy", "performance_rating_scale")]["status"] == "absent_from_format"


def test_ac_f2_per_task_completion_and_initials(lookup: dict) -> None:
    for field in ("per_task_completion_date", "per_task_evaluator_initials"):
        assert lookup[("nwcg_legacy", field)]["status"] == "captured"
        assert lookup[("nwcg_nextgen", field)]["status"] == "absent_from_format"
        # "nextgen odd one out": also captured in enhanced_gdoc
        assert lookup[("enhanced_gdoc", field)]["status"] == "captured"


def test_ac_f2_task_clarification_bullets(lookup: dict) -> None:
    assert lookup[("nwcg_legacy", "task_clarification_bullets")]["status"] == "captured"
    assert lookup[("nwcg_nextgen", "task_clarification_bullets")]["status"] == "absent_from_format"


def test_ac_f2_virtual_flag_fuel_model_management_type(lookup: dict) -> None:
    # Grounded expectation requires these captured in nextgen, and legacy
    # verified (not assumed) rather than defaulted to any particular value.
    for field in ("virtual_assignment_flag", "fbps_fuel_model_group", "management_type"):
        assert lookup[("nwcg_nextgen", field)]["status"] == "captured"
    # Verified against the actual legacy fixture text:
    assert lookup[("nwcg_legacy", "virtual_assignment_flag")]["status"] == "absent_from_format"
    assert lookup[("nwcg_legacy", "fbps_fuel_model_group")]["status"] == "captured"
    assert lookup[("nwcg_legacy", "management_type")]["status"] == "captured"


def test_ac_f2_trainee_ips_review_checkbox_intra_format_variance(lookup: dict) -> None:
    r = lookup[("nwcg_nextgen", "trainee_ips_review_checkbox")]
    assert r["status"] == "captured"
    assert "variance" in r["evidence"]


def test_ac_f2_enhanced_only_readiness_fields(lookup: dict) -> None:
    for field in (
        "task_level_tier",
        "currency_requirement",
        "physical_fitness_requirement",
        "required_training_list",
        "qualification_stack_by_tier",
    ):
        assert lookup[("enhanced_gdoc", field)]["status"] == "captured"
        assert lookup[("nwcg_nextgen", field)]["status"] == "absent_from_format"
        assert lookup[("nwcg_legacy", field)]["status"] == "absent_from_format"


def test_ac_f2_officiality_disclaimer_only_enhanced(lookup: dict) -> None:
    assert lookup[("enhanced_gdoc", "officiality_disclaimer")]["status"] == "captured"
    assert lookup[("nwcg_nextgen", "officiality_disclaimer")]["status"] == "absent_from_format"
    assert lookup[("nwcg_legacy", "officiality_disclaimer")]["status"] == "absent_from_format"


def test_ac_f2_o_code_collision_note_in_report() -> None:
    text = REPORT_PATH.read_text(encoding="utf-8")
    assert "`O`-code" in text or "O-code" in text.replace("`", "")
    assert "Developmental" in text
    assert "any situation" in text


# --- AC-F3: absent_from_format enumerates documents checked; every row cites
#            document + page (or an explicit "checked all N documents") -----


def test_ac_f3_absent_rows_enumerate_documents_checked(rows: list[dict]) -> None:
    for r in rows:
        if r["status"] == "absent_from_format":
            assert re.search(r"checked all \d+ \S+ (documents|tasks|positions)", r["evidence"]), r


def test_ac_f3_captured_rows_cite_a_document_and_page(rows: list[dict], corpus: "report.Corpus") -> None:
    all_filenames = {d["document"]["filename"] for fmt in report.FORMATS for d in corpus.docs(fmt)}
    for r in rows:
        if r["status"] == "captured":
            assert any(fn in r["evidence"] for fn in all_filenames), r
            assert re.search(r"p\.\d+", r["evidence"]), r


# --- AC-F4: no present_but_blank_in_samples where structure is genuinely
#            missing -------------------------------------------------------


def test_ac_f4_no_blank_status_currently_needed(rows: list[dict]) -> None:
    # Every field this corpus has evidence for is either genuinely captured
    # or genuinely absent; nothing currently on record is "structure exists
    # but 0 samples fill it" (edition_date/enhanced_gdoc was reclassified to
    # absent_from_format: enhanced_ptbs_gdoc.pdf has 0 "PMS" occurrences at
    # all, so the PMS-numbered edition-date convention doesn't exist for this
    # format - that's a structural absence, not sample blankness). If a
    # future corpus change legitimately introduces a blank case, update this
    # test to name it explicitly rather than loosening it to "any blanks ok".
    blanks = [r for r in rows if r["status"] == "present_but_blank_in_samples"]
    assert blanks == []


def test_ac_f4_task_level_tier_absent_not_blank_for_nwcg(lookup: dict) -> None:
    # 0/N samples but the Level tier concept does not exist at all in these
    # formats' task rows (no format change could retroactively add a value
    # to a printed PTB that never had a Level column) -> absent, not blank.
    assert lookup[("nwcg_nextgen", "task_level_tier")]["status"] == "absent_from_format"
    assert lookup[("nwcg_legacy", "task_level_tier")]["status"] == "absent_from_format"


# --- AC-F5: reconciliation options with trade-offs; no imputed values ------


def test_ac_f5_reconciliation_options_present() -> None:
    text = REPORT_PATH.read_text(encoding="utf-8")
    assert "rating-unknown" in text
    assert "M-equivalent" in text
    assert "trade-off" in text or "trade-offs" in text


def test_ac_f5_no_imputed_values_section_present() -> None:
    text = REPORT_PATH.read_text(encoding="utf-8")
    assert "No imputed values" in text
    assert "No cell was filled with a default" in text


def test_ac_f5_no_value_filling_language(rows: list[dict]) -> None:
    forbidden = ("probably", "likely contains", "presumably", "assumed to be", "default value of")
    text = REPORT_PATH.read_text(encoding="utf-8").lower()
    for phrase in forbidden:
        assert phrase not in text
    for r in rows:
        for phrase in forbidden:
            assert phrase not in r["evidence"].lower()


# --- AC-F6: byte-identical regeneration except the stamp --------------------


def _strip_stamp(text: str) -> str:
    return re.sub(r"^> Generated: .*$", "> Generated: STAMP", text, count=1, flags=re.MULTILINE)


def test_ac_f6_regenerates_identically_except_stamp(corpus: "report.Corpus", rows: list[dict]) -> None:
    first = report.render_report(corpus, rows, generated_at="2020-01-01")
    second = report.render_report(corpus, rows, generated_at="2099-12-31")
    assert _strip_stamp(first) == _strip_stamp(second)


def test_ac_f6_committed_report_matches_current_render(corpus: "report.Corpus", rows: list[dict]) -> None:
    on_disk = _strip_stamp(REPORT_PATH.read_text(encoding="utf-8"))
    rendered = _strip_stamp(report.render_report(corpus, rows, generated_at="irrelevant"))
    assert on_disk == rendered


# --- field_coverage DB table -------------------------------------------------


def test_field_coverage_written_to_db(tmp_path, corpus: "report.Corpus", rows: list[dict]) -> None:
    from ptb import db as db_module

    db_path = tmp_path / "test.sqlite"
    conn = db_module.connect(db_path)
    db_module.init_schema(conn)
    report.write_field_coverage(conn, rows)
    count = conn.execute("SELECT COUNT(*) FROM field_coverage").fetchone()[0]
    assert count == len(rows)
    one = conn.execute(
        "SELECT status FROM field_coverage WHERE format='nwcg_nextgen' AND field_name='performance_rating_scale'"
    ).fetchone()
    assert one["status"] == "captured"
    conn.close()
