"""Extraction & structuring orchestrator (Phase 2).

For every corpus/raw PTB document (role == "ptb"): detect its format, run the
matching structurer in src/ptb/structure/, validate the result against the
pydantic contract in models.py, and write extracted/<filename>.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb.models import Task as TaskModel  # noqa: E402
from ptb.models import DocumentMeta, ExtractedDocument, FieldObserved, Position
from ptb.structure.enhanced import structure_enhanced
from ptb.structure.legacy import structure_legacy
from ptb.structure.nextgen import structure_nextgen

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "corpus" / "raw"
MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"
EXTRACTED_DIR = REPO_ROOT / "extracted"

NEXTGEN_MARKER = "INSTRUCTIONS FOR NWCG NEXT GENERATION POSITION TASK BOOK"
NEXTGEN_MARKER_2 = "NWCG POSITION EVALUATION TABLE"
LEGACY_MARKER_RE = re.compile(r"NWCG Task Book for the Positions? of:")
ENHANCED_MARKER = "FireTech Position Task Books"

# Month name is case-insensitive: Next Gen books print "SEPTEMBER 2026",
# several legacy books print "October 2018" (extraction.spec.md changelog
# 2026-11-02). The printed form is stored verbatim; db.py normalizes to ISO.
EDITION_DATE_RE = re.compile(
    r"PMS\s*[\d-]+\s+((?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December) \d{4})",
    re.IGNORECASE,
)
# Mirrors structure/nextgen.py's IPS_REFERENCE_RE; used only to locate which
# page an already-extracted ips_reference value came from, for a page
# citation in fields_observed (format-gaps.spec.md's evidence rule).
IPS_REFERENCE_CITATION_RE = re.compile(r"PMS\s*350-\d+[A-Za-z]?")

FIELD_MARKERS = {
    # nwcg_nextgen markers grounded in the fixture ENGB (pms311-103_ENGB.pdf):
    # signature page = page 1; instructions = pages 2-3; position evaluation
    # table = pages 5-7; position evaluation record form = pages 8+.
    "nwcg_nextgen": [
        ("signature_page_initiation", "Initiation"),
        ("signature_page_verification", "Verification"),
        ("signature_page_certification", "Agency Certification"),
        ("trainee_iqcs_number", "IQCS/IQS#:"),
        ("code_definitions_block", "codes are defined as:"),
        # Position-evaluation-TABLE checkbox ("Box to be checked by trainee.");
        # distinct from ips_reviewed_flag below, which is a per-record Yes/No
        # field on the position evaluation RECORD form. CRWB uses a footnote
        # instead of this checkbox (PLAN.md Phase 0 finding) - intra-format
        # variance, not a format-absence.
        ("trainee_ips_review_checkbox", "(Box to be checked by trainee.)"),
        ("performance_rating_scale", "N/O = No opportunity"),
        ("per_assignment_rating_columns", "CODE Record Number"),
        ("virtual_assignment_flag", "Virtual Assignment"),
        ("ips_reviewed_flag", "Incident Position Standards Reviewed"),
        ("evaluator_position_on_incident", "Evaluator Position on Incident/Event:"),
        ("evaluator_iqcs_number", "IQCS/IQS #"),
        ("incident_name", "Incident/Event Name:"),
        ("incident_reference_code", "Reference (Incident Number/Fire Code):"),
        ("assignment_duration", "Duration:"),
        ("incident_kind", "Incident Kind:"),
        ("location_geographic_area", "Location (include Geographic Area"),
        ("management_type", "Management Type:"),
        ("rx_complexity_level", "Prescribed Fire Complexity Level"),
        ("fbps_fuel_model_group", "FBPS Fuel Model"),
        ("evaluator_recommendation_block", "(Initial only one line as appropriate)"),
        ("remarks_narrative", "Remarks on Individual Performance"),
        ("evaluator_relevant_qualification", "Relevant Qualification"),
    ],
    # nwcg_legacy markers grounded in the fixture LOFR (pms-311-05_LOFR.pdf):
    # signature/verification/certification = pages 1-2; instructions = pages
    # 3-5; evaluation record form = pages 18+. Confirmed absent on this
    # fixture (no marker added, see format-gaps.spec.md narrative):
    # performance_rating_scale, per_assignment_rating_columns,
    # virtual_assignment_flag, ips_reviewed_flag, trainee_iqcs_number,
    # evaluator_iqcs_number (0 "IQCS" occurrences anywhere in this 2010-era
    # fixture, confirmed on a random sample of other legacy documents too -
    # legacy identifies the evaluator by name/agency only, no IQCS number
    # field), remarks_narrative (legacy points to a separate "Individual
    # Performance Evaluation" attachment instead of an inline remarks field).
    "nwcg_legacy": [
        ("signature_page_initiation", "Task Book Initiated By:"),
        ("signature_page_verification", "Verification/Certification of Completed Task Book"),
        ("signature_page_certification", "Agency Certification"),
        ("prerequisite_buildup_statement", "builds on tasks from previous prerequisite position task books"),
        ("code_definitions_block", "codes are defined as:"),
        ("per_task_evaluator_initials", "EVALUATOR:"),
        ("evaluator_position_on_incident", "Evaluator Position on Incident/Event:"),
        ("incident_name", "Incident/Event Name:"),
        ("incident_reference_code", "Reference (Incident Number/Fire Code):"),
        ("assignment_duration", "Duration:"),
        ("incident_kind", "Incident Kind:"),
        ("location_geographic_area", "Location (include Geographic Area"),
        ("management_type", "Management Type"),
        ("rx_complexity_level", "Prescribed Fire Complexity Level"),
        ("fbps_fuel_model_group", "FBPS Fuel Model"),
        ("evaluator_recommendation_block", "(Initial only one line as appropriate)"),
        ("per_task_completion_date", "Initial & date"),
        ("evaluator_relevant_qualification", "Relevant Qualification"),
    ],
    # enhanced_gdoc markers grounded in enhanced_ptbs_gdoc.pdf: page 1 intro;
    # page 2 shared Evaluation Record template (per-assignment fields); each
    # position's own section ends with a "Final Evaluator's Verification"
    # (numbered recommendation options) + "Agency Certification" block - the
    # verification/certification phases exist, per-position, rather than as
    # one document-wide signature page. No rating-scale grid, and several
    # evaluation-record fields the NWCG formats have are simply not asked on
    # this draft's one shared record template - confirmed absent on this
    # document (0 occurrences checked across full text), no marker added:
    # virtual_assignment_flag, ips_reviewed_flag, evaluator_iqcs_number,
    # trainee_iqcs_number, performance_rating_scale,
    # per_assignment_rating_columns, incident_kind, location_geographic_area,
    # assignment_duration, fbps_fuel_model_group,
    # evaluator_relevant_qualification (0 occurrences; the format's
    # certification block names no specific qualification field). No separate initiation
    # phase either (no marker for signature_page_initiation): trainee
    # identification lives only in the generic per-assignment Evaluation
    # Record template, not a one-time initiation event. No
    # prerequisite_buildup_statement marker: the format has its own distinct
    # per-position "Prerequisite" field instead, captured structurally via
    # positions.requirements_text.
    "enhanced_gdoc": [
        ("officiality_disclaimer", "NOT official NWCG standards"),
        ("code_definitions_block", "Task code definitions"),
        ("per_task_completion_date", "Eval Rec #"),
        ("per_task_evaluator_initials", "Initials & Date"),
        ("task_level_tier", "Level"),
        ("evaluator_position_on_incident", "Evaluator name / position on"),
        ("incident_name", "Incident / event name"),
        ("incident_reference_code", "Reference (incident code /"),
        ("management_type", "Management Type (circle"),
        ("rx_complexity_level", "Complexity (circle one)"),
        ("remarks_narrative", "Record of performance /"),
        ("signature_page_verification", "Final Evaluator"),
        ("signature_page_certification", "Agency Certification"),
        ("evaluator_recommendation_block", "performed under my"),
    ],
}


def detect_format(full_text: str) -> str | None:
    if ENHANCED_MARKER in full_text:
        return "enhanced_gdoc"
    if NEXTGEN_MARKER in full_text or NEXTGEN_MARKER_2 in full_text:
        return "nwcg_nextgen"
    if LEGACY_MARKER_RE.search(full_text):
        return "nwcg_legacy"
    return None


def find_fields_observed(pages_text: list[str], fmt: str) -> list[FieldObserved]:
    """Marker match is whitespace-normalized: pdfplumber's line-wrap point for
    a given sentence varies by document (font/margin differences), so a
    marker phrase can straddle a '\\n' in one document and not another (e.g.
    "codes are defined as:" wraps as "codes\\nare defined as:" in some PTBs).
    Collapsing all whitespace runs to single spaces before matching makes
    marker detection robust to that layout variance without changing what
    text must actually be present."""
    observed = []
    for field_name, marker in FIELD_MARKERS.get(fmt, []):
        marker_norm = re.sub(r"\s+", " ", marker)
        for i, text in enumerate(pages_text, start=1):
            if marker_norm in re.sub(r"\s+", " ", text):
                observed.append(FieldObserved(field_name=field_name, page=i))
                break
    return observed


def find_edition_date(full_text: str) -> str | None:
    m = EDITION_DATE_RE.search(full_text)
    return m.group(1) if m else None


def find_page_for_pattern(pages_text: list[str], pattern: re.Pattern) -> int | None:
    """First 1-indexed page whose text matches `pattern` - used to give
    document-level fields (edition_date, ips_reference) a page citation for
    format-gaps.spec.md's evidence rule, without adding a new DocumentMeta
    field. Recorded as a `fields_observed` entry alongside the existing
    document.edition_date/document.ips_reference structural values."""
    for i, text in enumerate(pages_text, start=1):
        if pattern.search(text):
            return i
    return None


def split_position_titles(doc_title: str, position_codes: list[str]) -> list[str]:
    if len(position_codes) > 1 and " or " in doc_title:
        parts = [p.strip() for p in doc_title.split(" or ")]
        if len(parts) == len(position_codes):
            return parts
    return [doc_title] * len(position_codes)


def build_nwcg_document(entry: dict) -> ExtractedDocument | None:
    path = RAW_DIR / entry["filename"]
    with pdfplumber.open(path) as pdf:
        pages_text = [p.extract_text() or "" for p in pdf.pages]
        full_text = "\n".join(pages_text)
        fmt = detect_format(full_text)
        if fmt not in ("nwcg_nextgen", "nwcg_legacy"):
            return None

        position_codes = entry["position_codes"]
        if fmt == "nwcg_nextgen":
            raw_tasks, ips_reference = structure_nextgen(pdf, position_codes)
        else:
            raw_tasks = []
            ips_reference = None
            for code in position_codes:
                tasks, ips = structure_legacy(pdf, code)
                raw_tasks.extend(tasks)
                ips_reference = ips_reference or ips

        page_count = len(pdf.pages)

    titles = split_position_titles(entry["title"], position_codes)
    positions = [
        Position(code=code, title=title, provisional_code=False)
        for code, title in zip(position_codes, titles)
    ]
    tasks = [TaskModel(**t) for t in raw_tasks]
    fields_observed = find_fields_observed(pages_text, fmt)
    edition_date = find_edition_date(full_text)
    if edition_date is not None:
        page = find_page_for_pattern(pages_text, EDITION_DATE_RE)
        if page is not None:
            fields_observed.append(FieldObserved(field_name="edition_date", page=page))
    if ips_reference is not None:
        page = find_page_for_pattern(pages_text, IPS_REFERENCE_CITATION_RE)
        if page is not None:
            fields_observed.append(FieldObserved(field_name="ips_reference", page=page))

    document = DocumentMeta(
        filename=entry["filename"],
        sha256=entry["sha256"],
        pms_number=entry.get("pms_number"),
        format=fmt,
        position_codes=position_codes,
        title=entry["title"],
        edition_date=edition_date,
        ips_reference=ips_reference,
        official=entry.get("official", True),
        page_count=page_count,
    )
    return ExtractedDocument(document=document, positions=positions, tasks=tasks, fields_observed=fields_observed)


def build_enhanced_document(docx_entry: dict, pdf_entry: dict) -> ExtractedDocument:
    docx_path = RAW_DIR / docx_entry["filename"]
    pdf_path = RAW_DIR / pdf_entry["filename"]
    result = structure_enhanced(str(docx_path), str(pdf_path))

    with pdfplumber.open(pdf_path) as pdf:
        pages_text = [p.extract_text() or "" for p in pdf.pages]
        page_count = len(pdf.pages)

    positions = [
        Position(
            code=p["code"],
            title=p["title"],
            provisional_code=p["provisional_code"],
            requirements_text=p["requirements_text"],
            attaches_to=p["attaches_to"],
            attaches_to_alternatives=p.get("attaches_to_alternatives") or None,
            extra_fields={k: v for k, v in p["extra_fields"].items() if v not in (None, {}, [])},
        )
        for p in result["positions"]
    ]
    tasks = [TaskModel(**t) for t in result["tasks"]]
    fields_observed = find_fields_observed(pages_text, "enhanced_gdoc")

    document = DocumentMeta(
        filename=docx_entry["filename"],
        sha256=docx_entry["sha256"],
        pms_number=None,
        format="enhanced_gdoc",
        position_codes=[p["code"] for p in result["positions"]],
        title=docx_entry["title"],
        edition_date=None,
        ips_reference=None,
        official=False,
        page_count=page_count,
    )
    return ExtractedDocument(
        document=document,
        positions=positions,
        tasks=tasks,
        fields_observed=fields_observed,
        extra_fields={"code_definitions": result["code_definitions"]},
    )


def validate_pages(doc: ExtractedDocument) -> list[str]:
    errors = []
    for t in doc.tasks:
        if not (1 <= t.page <= doc.document.page_count):
            errors.append(f"task {t.position_code}#{t.task_number} page {t.page} out of range [1,{doc.document.page_count}]")
    for f in doc.fields_observed:
        if not (1 <= f.page <= doc.document.page_count):
            errors.append(f"fields_observed {f.field_name} page {f.page} out of range")
    return errors


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    documents = [d for d in manifest["documents"] if d.get("role") == "ptb"]
    EXTRACTED_DIR.mkdir(exist_ok=True)

    gdoc_docx = next((d for d in documents if d["filename"].endswith(".docx")), None)
    gdoc_pdf = next((d for d in documents if d["filename"] == "enhanced_ptbs_gdoc.pdf"), None)
    nwcg_docs = [d for d in documents if not d["filename"].startswith("enhanced_ptbs_gdoc")]

    # A document NWCG no longer publishes (manifest `retired[]`, e.g. the
    # combined FEMO-FOBS legacy book) must not linger in the audit trail,
    # or db.py would load it and INV-1 would fail on its deleted raw file.
    live_json_names = {f"{d['filename']}.json" for d in documents}
    for stale in sorted(EXTRACTED_DIR.glob("*.json")):
        if stale.name not in live_json_names:
            stale.unlink()
            print(f"  removed stale {stale.name} (no role=ptb manifest entry; see manifest retired[])", file=sys.stderr)

    ok, failed = 0, []

    for entry in nwcg_docs:
        try:
            extracted = build_nwcg_document(entry)
            if extracted is None:
                failed.append((entry["filename"], "format detection failed"))
                continue
            page_errors = validate_pages(extracted)
            if page_errors:
                failed.append((entry["filename"], "; ".join(page_errors)))
                continue
            out_path = EXTRACTED_DIR / f"{entry['filename']}.json"
            out_path.write_text(extracted.model_dump_json(indent=2), encoding="utf-8")
            ok += 1
        except ValidationError as e:
            failed.append((entry["filename"], str(e)))
        except Exception as e:  # noqa: BLE001
            failed.append((entry["filename"], f"{type(e).__name__}: {e}"))

    if gdoc_docx and gdoc_pdf:
        try:
            extracted = build_enhanced_document(gdoc_docx, gdoc_pdf)
            page_errors = validate_pages(extracted)
            if page_errors:
                failed.append((gdoc_docx["filename"], "; ".join(page_errors)))
            else:
                out_path = EXTRACTED_DIR / f"{gdoc_docx['filename']}.json"
                out_path.write_text(extracted.model_dump_json(indent=2), encoding="utf-8")
                ok += 1
        except ValidationError as e:
            failed.append((gdoc_docx["filename"], str(e)))
        except Exception as e:  # noqa: BLE001
            failed.append((gdoc_docx["filename"], f"{type(e).__name__}: {e}"))

    print(f"Extracted: {ok}  Failed: {len(failed)}", file=sys.stderr)
    for fn, reason in failed:
        print(f"  FAIL {fn}: {reason[:300]}", file=sys.stderr)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
