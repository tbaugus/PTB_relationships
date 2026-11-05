"""Structuring for enhanced_gdoc (FireTech) Position Task Books.

Unlike the two NWCG PDF formats, this document is a clean DOCX with real
tables — each of the 11 positions is a fixed, repeating sequence of
paragraph headings and tables in document order, so this parser walks
paragraphs/tables in order rather than reconstructing layout from word
coordinates.
"""

from __future__ import annotations

import re

import pdfplumber
from docx import Document
from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

POSITION_TITLE_RE = re.compile(r"^NWCG Position Task Book\s*[—-]\s*(.+?)\s*\(([A-Za-z0-9]+)\)\s*$")
VALID_LEVELS = {"Aspirant", "Beginner", "Journey", "Expert"}


def _iter_block_items(doc):
    parent_elm = doc.element.body if isinstance(doc, _Document) else doc._element
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_rows(table: Table) -> list[list[str]]:
    return [[c.text.strip() for c in row.cells] for row in table.rows]


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _build_page_index(pdf_path: str) -> list[tuple[int, str]]:
    """(page_number, whitespace-collapsed page text) for every page, for
    provenance lookup — the DOCX has no native pagination, so per-task page
    numbers are recovered from the companion PDF export (spec's designated
    "page-provenance reference" for this format)."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            pages.append((i, _collapse(page.extract_text() or "")))
    return pages


def _find_page(verbatim_text: str, page_index: list[tuple[int, str]]) -> int:
    needle = _collapse(verbatim_text)
    for page_number, page_text in page_index:
        if needle and needle in page_text:
            return page_number
    # Fall back to a shortened prefix in case of a mid-sentence PDF line-wrap
    # artifact the DOCX doesn't have.
    if len(needle) > 20:
        prefix = needle[:20]
        for page_number, page_text in page_index:
            if prefix in page_text:
                return page_number
    return 1


def parse_attaches_to(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse an "Attaches to:" line. "+" joins anchors that are all required;
    "/" lists alternatives for one anchor (CFMD "FBAN / LTAN"). Returns the
    flat code list (every value resolves to a positions.code; F2 AC-B4) and
    the alternative groups (schema.spec.md changelog 2026-11-04)."""
    body = text.split(":", 1)[1] if ":" in text else text
    flat: list[str] = []
    groups: list[list[str]] = []
    for part in body.split("+"):
        codes = [t.strip() for t in part.split("/") if t.strip()]
        flat.extend(codes)
        if len(codes) > 1:
            groups.append(codes)
    return flat, groups


def structure_enhanced(docx_path: str, pdf_path: str | None = None) -> dict:
    doc = Document(docx_path)
    blocks = list(_iter_block_items(doc))

    code_definitions: dict[str, str] = {}
    for block in blocks:
        if isinstance(block, Table):
            rows = _table_rows(block)
            if rows and len(rows[0]) == 2 and all(re.match(r"^[A-Z/]+$", r[0]) for r in rows if r[0]):
                code_definitions = {r[0]: r[1] for r in rows}
                break

    # Find each position's start index (the title paragraph).
    starts = []
    for i, block in enumerate(blocks):
        if isinstance(block, Paragraph):
            m = POSITION_TITLE_RE.match(block.text.strip())
            if m:
                starts.append((i, m.group(1).strip(), m.group(2).strip()))
    starts.append((len(blocks), None, None))

    positions = []
    all_tasks = []

    for idx in range(len(starts) - 1):
        start_i, title, code = starts[idx]
        end_i = starts[idx + 1][0]
        section = blocks[start_i + 1 : end_i]

        attaches_to: list[str] = []
        attaches_to_alternatives: list[list[str]] = []
        i = 0
        if i < len(section) and isinstance(section[i], Paragraph):
            text = section[i].text.strip()
            if text.startswith("Attaches to:"):
                attaches_to, attaches_to_alternatives = parse_attaches_to(text)
                i += 1
            elif text.startswith("No NWCG anchor"):
                i += 1

        facts: dict[str, str] = {}
        while i < len(section) and not isinstance(section[i], Table):
            i += 1
        if i < len(section) and isinstance(section[i], Table):
            for row in _table_rows(section[i]):
                if len(row) == 2:
                    facts[row[0]] = row[1]
            i += 1

        required_training = []
        while i < len(section) and not isinstance(section[i], Table):
            i += 1
        if i < len(section) and isinstance(section[i], Table):
            rows = _table_rows(section[i])
            for row in rows[1:]:
                if len(row) == 3:
                    required_training.append({"training": row[0], "source_provider": row[1], "approx_cost": row[2]})
            i += 1

        qualification_stack = {}
        while i < len(section) and not isinstance(section[i], Table):
            i += 1
        if i < len(section) and isinstance(section[i], Table):
            rows = _table_rows(section[i])
            for row in rows[1:]:
                if len(row) == 2:
                    qualification_stack[row[0]] = row[1]
            i += 1

        task_rows: list[list[str]] = []
        while i < len(section) and not isinstance(section[i], Table):
            i += 1
        if i < len(section) and isinstance(section[i], Table):
            task_rows = _table_rows(section[i])
            i += 1

        employers_by_sector = {}
        workforce_estimate = None
        while i < len(section) and not isinstance(section[i], Table):
            i += 1
        if i < len(section) and isinstance(section[i], Table):
            rows = _table_rows(section[i])
            for row in rows[1:]:
                if len(row) == 2:
                    employers_by_sector[row[0]] = row[1]
            i += 1
        while i < len(section):
            if isinstance(section[i], Paragraph) and section[i].text.strip().lower().startswith(
                "approx. number performing"
            ):
                workforce_estimate = section[i].text.strip()
                break
            i += 1

        positions.append(
            {
                "code": code,
                "title": title,
                "provisional_code": False,
                "requirements_text": facts.get("Prerequisite"),
                "attaches_to": attaches_to,
                "attaches_to_alternatives": attaches_to_alternatives,
                "extra_fields": {
                    "required_experience": facts.get("Required experience"),
                    "physical_fitness": facts.get("Physical fitness"),
                    "currency": facts.get("Currency"),
                    "required_training": required_training,
                    "qualification_stack": qualification_stack,
                    "employers_by_sector": employers_by_sector,
                    "workforce_estimate": workforce_estimate,
                },
            }
        )

        category = ""
        behavior = ""
        for row in task_rows[1:]:
            if not row or not row[0]:
                continue
            label = row[1] if len(row) > 1 else row[0]
            if label.startswith("COMPETENCY:"):
                category = label
                continue
            if label.startswith("Behavior:"):
                behavior = label[len("Behavior:") :].strip()
                continue
            if not row[0].strip().isdigit():
                continue
            level = row[3].strip() if len(row) > 3 else None
            all_tasks.append(
                {
                    "position_code": code,
                    "task_number": int(row[0].strip()),
                    "category": category,
                    "behavior": behavior,
                    "level": level if level in VALID_LEVELS else None,
                    "verbatim_text": row[1].strip(),
                    "code_raw": row[2].strip(),
                    "code_alternatives": row[2].strip().split("/"),
                    "clarifications": [],
                    "page": 1,
                }
            )

    if pdf_path:
        page_index = _build_page_index(pdf_path)
        for t in all_tasks:
            t["page"] = _find_page(t["verbatim_text"], page_index)

    return {
        "positions": positions,
        "tasks": all_tasks,
        "code_definitions": code_definitions,
    }
