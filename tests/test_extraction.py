"""specs/extraction.spec.md AC-E10 — a legacy task's category is the full
printed "Behavior:" heading, wrapped continuation lines included.

Reads the committed extracted/*.json and the corpus PDFs (corpus/raw, the
same files db.py's provenance check already needs), never the network.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pdfplumber
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

EXTRACTED_DIR = REPO_ROOT / "extracted"
RAW_DIR = REPO_ROOT / "corpus" / "raw"


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.fixture(scope="module")
def legacy_docs() -> list[dict]:
    docs = []
    for path in sorted(EXTRACTED_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["document"]["format"] == "nwcg_legacy":
            docs.append(doc)
    assert docs, "no nwcg_legacy documents in extracted/"
    return docs


def _tasks(docs: list[dict], filename: str, position: str) -> dict[int, dict]:
    doc = next(d for d in docs if d["document"]["filename"] == filename)
    return {t["task_number"]: t for t in doc["tasks"] if t["position_code"] == position}


# --- AC-E10 grounded examples ------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "position", "task_numbers", "expected"),
    [
        (
            "pms-311-05_LOFR.pdf",
            "LOFR",
            [4, 5, 6],
            "Ensure availability, qualifications, and capabilities of resources to complete assignment.",
        ),
        (
            "pms311-118_FAL1.pdf",
            "FAL1",
            [21, 22, 24],
            "Follow established procedures and/or safety procedures relevant to given assignment.",
        ),
    ],
)
def test_ac_e10_wrapped_heading_examples(legacy_docs, filename, position, task_numbers, expected) -> None:
    tasks = _tasks(legacy_docs, filename, position)
    for n in task_numbers:
        assert tasks[n]["category"] == expected, f"{position} #{n}: {tasks[n]['category']!r}"


def test_ac_e10_ict3_heading_not_truncated(legacy_docs) -> None:
    categories = {t["category"] for t in _tasks(legacy_docs, "pms311-02_ICT3.pdf", "ICT3").values()}
    assert "Follow established procedures and/or safety procedures relevant to given assignment." in categories
    assert not any(c.endswith(" given") for c in categories)


# --- AC-E10 corpus-wide invariant --------------------------------------------


# What may legitimately follow a complete "Behavior:" heading in the
# whitespace-collapsed page text: the first task's printed number (any
# number — PSC3 #39 is printed but omitted by extraction under INV-7), or
# the page footer or bare page number (end of the page text) when the
# heading is the last line on its page and its tasks start on the next
# page (SOFC page 5 -> 6; PSC3 page 15 -> 16).
AFTER_HEADING_RE = r" (\d+\.|Additional Evaluation Record Sheets|Evaluate the numbered tasks|\d+$)"


def test_ac_e10_every_legacy_category_is_a_full_heading(legacy_docs) -> None:
    """For every distinct (document, position, category), the text of the
    heading's page (a task's own page, or the page before it) contains
    "Behavior: <category>" verbatim and immediately followed by a task
    number or the page footer. A category cut short of the heading's end
    cannot match, because the heading's remaining words would sit where the
    number or footer must be."""
    failures = []
    for doc in legacy_docs:
        filename = doc["document"]["filename"]
        pdf_path = RAW_DIR / filename
        if not pdf_path.exists():
            pytest.skip(f"{filename} not in corpus/raw (run src/ptb/acquire.py)")
        groups: dict[tuple[str, str], list[dict]] = {}
        for t in doc["tasks"]:
            groups.setdefault((t["position_code"], t["category"]), []).append(t)
        with pdfplumber.open(pdf_path) as pdf:
            page_text: dict[int, str] = {}

            def text_of(page: int) -> str:
                if page not in page_text:
                    page_text[page] = _collapse(pdf.pages[page - 1].extract_text() or "")
                return page_text[page]

            for (position, category), tasks in groups.items():
                needle = re.compile(re.escape(f"Behavior: {category}") + AFTER_HEADING_RE)
                pages = sorted({p for t in tasks for p in (t["page"] - 1, t["page"]) if p >= 1})
                if not any(needle.search(text_of(p)) for p in pages):
                    failures.append((filename, position, category))
    assert not failures, "\n".join(f"{f}: {p} {c!r}" for f, p, c in failures)
