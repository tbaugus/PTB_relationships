from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import db  # noqa: E402

# The five Phase 0 fixture PTBs named throughout specs/schema.spec.md and
# specs/matching.spec.md (FFT1/ENGB/CRWB/FIRB = Next Gen, LOFR = legacy).
FIXTURE_FILENAMES = [
    "pms311-14_FFT1.pdf.json",
    "pms311-103_ENGB.pdf.json",
    "pms-311-98_CRWB.pdf.json",
    "pms311-105_FIRB.pdf.json",
    "pms-311-05_LOFR.pdf.json",
]


@pytest.fixture(scope="session")
def fixture_db_conn(tmp_path_factory) -> sqlite3.Connection:
    """DB built from only the 5 named fixtures (schema.spec.md AC-S3)."""
    tmp_dir = tmp_path_factory.mktemp("fixture_extracted")
    for filename in FIXTURE_FILENAMES:
        shutil.copy2(db.EXTRACTED_DIR / filename, tmp_dir / filename)

    db_path = tmp_path_factory.mktemp("fixture_db") / "fixtures.sqlite"
    db.build_database(
        db_path=db_path,
        extracted_dir=tmp_dir,
        requirements_dir=tmp_dir / "requirements",  # deliberately empty/nonexistent
    )
    conn = db.connect(db_path)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def full_db_conn(tmp_path_factory) -> sqlite3.Connection:
    """DB built from the entire corpus (needed for the enhanced_gdoc case, INV-8)."""
    db_path = tmp_path_factory.mktemp("full_db") / "full.sqlite"
    db.build_database(db_path=db_path)
    conn = db.connect(db_path)
    yield conn
    conn.close()


@pytest.fixture
def empty_conn() -> sqlite3.Connection:
    """Fresh in-memory DB with schema only, no data."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded_conn(empty_conn: sqlite3.Connection) -> sqlite3.Connection:
    """Minimal valid seed data for constraint-violation tests (AC-S4)."""
    conn = empty_conn
    conn.execute(
        """INSERT INTO source_documents
           (id, filename, url, sha256, format, role, official, pms_number, edition_date, downloaded_at)
           VALUES (1, 'seed.pdf', 'http://example.test/seed.pdf', 'abc123', 'nwcg_nextgen', 'ptb', 1,
                   '311-00', '2026-01-01', '2026-07-09')"""
    )
    conn.execute(
        "INSERT INTO positions (id, code, title, provisional_code, source_document_id) VALUES (1, 'AAAA', 'Position A', 0, 1)"
    )
    conn.execute(
        "INSERT INTO positions (id, code, title, provisional_code, source_document_id) VALUES (2, 'BBBB', 'Position B', 0, 1)"
    )
    conn.execute("INSERT INTO tasks (id, canonical_text, normalized_text) VALUES (1, 'Task One.', 'task one')")
    conn.execute("INSERT INTO tasks (id, canonical_text, normalized_text) VALUES (2, 'Task Two.', 'task two')")
    conn.execute(
        """INSERT INTO position_tasks
           (id, position_id, task_id, task_number, category, behavior, level,
            verbatim_text, code_raw, code_alternatives, clarifications, page)
           VALUES (1, 1, 1, 1, 'Category', NULL, NULL, 'Task One.', 'O', '["O"]', '[]', 1)"""
    )
    conn.commit()
    return conn
