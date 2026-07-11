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

EDITION_DATE_RE = re.compile(r"PMS\s*[\d-]+\s+([A-Z]+ \d{4})")

FIELD_MARKERS = {
    "nwcg_nextgen": [
        ("virtual_assignment_flag", "Virtual Assignment"),
        ("evaluator_iqcs_number", "IQCS/IQS #"),
        ("fbps_fuel_model", "FBPS Fuel Model"),
        ("trainee_ips_review_checkbox", "Incident Position Standards Reviewed"),
    ],
    "nwcg_legacy": [
        ("evaluator_iqcs_number", "IQCS/IQS#"),
        ("fbps_fuel_model", "FBPS Fuel Model Group"),
        ("per_task_completion_date", "Initial & date"),
    ],
    "enhanced_gdoc": [
        ("per_task_completion_date", "Eval Rec #"),
        ("level_rating", "Level"),
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
    observed = []
    for field_name, marker in FIELD_MARKERS.get(fmt, []):
        for i, text in enumerate(pages_text, start=1):
            if marker in text:
                observed.append(FieldObserved(field_name=field_name, page=i))
                break
    return observed


def find_edition_date(full_text: str) -> str | None:
    m = EDITION_DATE_RE.search(full_text)
    return m.group(1) if m else None


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

    document = DocumentMeta(
        filename=entry["filename"],
        sha256=entry["sha256"],
        pms_number=entry.get("pms_number"),
        format=fmt,
        position_codes=position_codes,
        title=entry["title"],
        edition_date=find_edition_date(full_text),
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
