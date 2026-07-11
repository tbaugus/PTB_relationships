"""Tests for specs/schema.spec.md (Phase 3).

Covers AC-S1 through AC-S4 and invariants INV-1 through INV-7 (per the task
brief) plus INV-8 as a bonus check (the schema's Invariants section lists
eight; AC-S2's prose says "seven" — INV-8 is tested anyway since it costs
nothing and the loader already satisfies it).
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import db  # noqa: E402
from ptb.models import VALID_CODES  # noqa: E402

FIXTURE_CODES = {"FFT1", "ENGB", "CRWB", "FIRB", "LOFR"}


# ---------------------------------------------------------------------------
# AC-S1: DDL executes on a fresh SQLite database without error; no
# engine-specific (SQLite-only) SQL.
# ---------------------------------------------------------------------------


def test_ac_s1_ddl_executes_on_fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    db.init_schema(conn)  # raises on error
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "source_documents",
        "positions",
        "tasks",
        "position_tasks",
        "task_equivalences",
        "position_requirements",
        "position_implications",
        "field_coverage",
    }
    assert expected <= tables


SQLITE_ONLY_TOKENS = ["AUTOINCREMENT", "WITHOUT ROWID", "PRAGMA", "`"]


def test_ac_s1_no_sqlite_only_syntax_in_ddl():
    upper = db.SCHEMA_SQL.upper()
    for token in SQLITE_ONLY_TOKENS:
        assert token not in upper, f"DDL contains SQLite-only construct: {token}"
    # Portable data types only (no BLOB/JSON/etc SQLite dynamic-typing extras assumed).
    assert re.search(r"\bSERIAL\b", upper) is None  # Postgres-ism that would be wrong here too


# ---------------------------------------------------------------------------
# AC-S3: loading the 5 fixtures produces 5 ptb source_documents, >=5
# positions, and tier-1 shared task_ids for the two grounded examples.
# ---------------------------------------------------------------------------


def test_ac_s3_fixture_load_counts(fixture_db_conn):
    conn = fixture_db_conn
    n_docs = conn.execute("SELECT COUNT(*) FROM source_documents WHERE role = 'ptb'").fetchone()[0]
    assert n_docs == 5

    n_positions = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    assert n_positions >= 5

    codes = {r[0] for r in conn.execute("SELECT code FROM positions").fetchall()}
    assert FIXTURE_CODES <= codes


@pytest.mark.parametrize(
    "phrase",
    [
        "Apply the Risk Management Process.",
        "Gather critical information pertinent to the assignment.",
    ],
)
def test_ac_s3_tier1_sharing_across_fft1_engb_firb(fixture_db_conn, phrase):
    conn = fixture_db_conn
    rows = conn.execute(
        """
        SELECT p.code, pt.task_id
        FROM position_tasks pt
        JOIN positions p ON p.id = pt.position_id
        WHERE pt.verbatim_text = ? AND p.code IN ('FFT1', 'ENGB', 'FIRB')
        """,
        (phrase,),
    ).fetchall()
    codes_found = {r["code"] for r in rows}
    assert codes_found == {"FFT1", "ENGB", "FIRB"}, f"expected all three positions for {phrase!r}, got {codes_found}"
    task_ids = {r["task_id"] for r in rows}
    assert len(task_ids) == 1, f"expected one shared task_id for {phrase!r}, got {task_ids}"


# ---------------------------------------------------------------------------
# INV-1: every position_tasks row's (verbatim_text, page) is traceable to a
# source_documents row via its position, and the file exists in corpus/raw/.
# ---------------------------------------------------------------------------


def test_inv1_provenance_traceable_to_raw_file(fixture_db_conn):
    conn = fixture_db_conn
    rows = conn.execute(
        """
        SELECT pt.id, pt.verbatim_text, pt.page, sd.filename
        FROM position_tasks pt
        JOIN positions p ON p.id = pt.position_id
        JOIN source_documents sd ON sd.id = p.source_document_id
        """
    ).fetchall()
    assert len(rows) > 0
    for row in rows:
        assert row["verbatim_text"]
        assert row["page"] >= 1
        raw_path = db.CORPUS_RAW_DIR / row["filename"]
        assert raw_path.exists(), f"missing corpus/raw/{row['filename']} for position_tasks.id={row['id']}"


# ---------------------------------------------------------------------------
# INV-2: no tier-2 task_equivalences row has status='confirmed' with
# human_reviewed_at IS NULL. Tier-1 rows may auto-confirm. Vacuously true in
# Phase 3 since task_equivalences is populated in Phase 4 — the query itself
# is the real check and will start mattering the moment rows exist.
# ---------------------------------------------------------------------------


def test_inv2_no_unreviewed_confirmed_tier2(fixture_db_conn):
    conn = fixture_db_conn
    bad = conn.execute(
        """
        SELECT COUNT(*) FROM task_equivalences
        WHERE tier = 2 AND status = 'confirmed' AND human_reviewed_at IS NULL
        """
    ).fetchone()[0]
    assert bad == 0


def test_inv2_constraint_does_not_block_reviewed_tier2_confirm(seeded_conn):
    # A tier-2 row WITH human_reviewed_at must be insertable (the schema
    # itself does not encode INV-2 as a CHECK — see AC-S4 for the
    # complementary "confirmed without review" rejection expectation, which
    # this project enforces at the loader level, not the DDL level).
    seeded_conn.execute(
        """
        INSERT INTO task_equivalences
            (task_a_id, task_b_id, relation, tier, method, similarity_score,
             adjudication_note, human_reviewed_at, status)
        VALUES (1, 2, 'equivalent', 2, 'embedding+adjudication', 0.9, 'note', '2026-07-09', 'confirmed')
        """
    )
    seeded_conn.commit()


# ---------------------------------------------------------------------------
# INV-3: tasks.normalized_text is unique; two position_tasks rows in
# different positions with identical normalized text share one task_id.
# ---------------------------------------------------------------------------


def test_inv3_normalized_text_unique(fixture_db_conn):
    conn = fixture_db_conn
    dupes = conn.execute(
        "SELECT normalized_text, COUNT(*) c FROM tasks GROUP BY normalized_text HAVING c > 1"
    ).fetchall()
    assert dupes == []


def test_inv3_identical_text_shares_task_id_across_positions(fixture_db_conn):
    conn = fixture_db_conn
    # Real dedup must have happened at least once: some normalized_text is
    # used by position_tasks rows belonging to more than one position, all
    # sharing a single task_id (not one task_id per position).
    rows = conn.execute(
        """
        SELECT t.normalized_text, pt.task_id, pt.position_id
        FROM position_tasks pt
        JOIN tasks t ON t.id = pt.task_id
        """
    ).fetchall()
    by_text: dict[str, set] = {}
    task_id_by_text: dict[str, set] = {}
    for r in rows:
        by_text.setdefault(r["normalized_text"], set()).add(r["position_id"])
        task_id_by_text.setdefault(r["normalized_text"], set()).add(r["task_id"])

    shared = {text: positions for text, positions in by_text.items() if len(positions) > 1}
    assert shared, "expected at least one normalized_text shared across positions"
    for text in shared:
        assert len(task_id_by_text[text]) == 1, f"{text!r} spans positions but has multiple task_ids"


# ---------------------------------------------------------------------------
# INV-4: task_equivalences rows always reference two DIFFERENT task ids.
# ---------------------------------------------------------------------------


def test_inv4_no_self_referential_equivalence_rows(fixture_db_conn):
    conn = fixture_db_conn
    bad = conn.execute("SELECT COUNT(*) FROM task_equivalences WHERE task_a_id = task_b_id").fetchone()[0]
    assert bad == 0


def test_inv4_constraint_rejects_equal_task_ids(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError):
        seeded_conn.execute(
            """
            INSERT INTO task_equivalences (task_a_id, task_b_id, relation, tier, method, status)
            VALUES (1, 1, 'equivalent', 1, 'normalized_text', 'confirmed')
            """
        )


# ---------------------------------------------------------------------------
# INV-5: every position has >= 1 task; every task is referenced by >= 1
# position_tasks row (no orphans).
# ---------------------------------------------------------------------------


def test_inv5_no_position_without_tasks(fixture_db_conn):
    conn = fixture_db_conn
    orphan_positions = conn.execute(
        """
        SELECT p.code FROM positions p
        LEFT JOIN position_tasks pt ON pt.position_id = p.id
        WHERE pt.id IS NULL
        """
    ).fetchall()
    assert orphan_positions == []


def test_inv5_no_task_without_position_tasks(fixture_db_conn):
    conn = fixture_db_conn
    orphan_tasks = conn.execute(
        """
        SELECT t.id FROM tasks t
        LEFT JOIN position_tasks pt ON pt.task_id = t.id
        WHERE pt.id IS NULL
        """
    ).fetchall()
    assert orphan_tasks == []


# ---------------------------------------------------------------------------
# INV-6: code_alternatives parses as JSON and is a non-empty subset of
# {I, W, RX, R, S, O, ALL}.
# ---------------------------------------------------------------------------


def test_inv6_code_alternatives_valid(fixture_db_conn):
    conn = fixture_db_conn
    rows = conn.execute("SELECT id, code_alternatives FROM position_tasks").fetchall()
    assert len(rows) > 0
    for row in rows:
        parsed = json.loads(row["code_alternatives"])  # raises if not valid JSON
        assert isinstance(parsed, list)
        assert len(parsed) > 0, f"position_tasks.id={row['id']} has empty code_alternatives"
        assert set(parsed) <= VALID_CODES, f"position_tasks.id={row['id']} has unknown codes: {parsed}"


# ---------------------------------------------------------------------------
# INV-7: task numbers per position are exactly 1..N (COUNT = MAX = N).
# ---------------------------------------------------------------------------


def test_inv7_task_numbers_are_exactly_1_to_n(fixture_db_conn):
    conn = fixture_db_conn
    rows = conn.execute(
        """
        SELECT position_id, COUNT(*) c, MAX(task_number) m, MIN(task_number) mn
        FROM position_tasks
        GROUP BY position_id
        """
    ).fetchall()
    assert len(rows) > 0
    for row in rows:
        assert row["c"] == row["m"], f"position_id={row['position_id']}: count={row['c']} != max={row['m']}"
        assert row["mn"] == 1, f"position_id={row['position_id']}: min task_number={row['mn']} != 1"


# INV-7's documented exception (schema.spec.md Changelog, 2026-07-09): three
# positions have a source PDF task whose evaluation-code cell is genuinely
# blank in print, so extraction correctly omits that task_number rather than
# invent a code. None of the 5 named fixtures are among these three, so this
# needs the full-corpus load. The exact missing numbers are asserted, not
# just "some gap exists," so any *new* or *different* gap fails loudly.
KNOWN_INV7_EXCEPTIONS = {
    "PSC3": {"count": 68, "max": 70, "missing": {17, 39}},
    "PSCC": {"count": 44, "max": 45, "missing": {39}},
    "FSCC": {"count": 33, "max": 34, "missing": {26}},
}


def test_inv7_full_corpus_matches_documented_exceptions_exactly(full_db_conn):
    conn = full_db_conn
    rows = conn.execute(
        """
        SELECT p.code, COUNT(*) c, MAX(pt.task_number) m
        FROM position_tasks pt
        JOIN positions p ON p.id = pt.position_id
        GROUP BY p.id
        """
    ).fetchall()
    assert len(rows) > 0

    violations = {row["code"]: row for row in rows if row["c"] != row["m"]}
    assert set(violations) == set(KNOWN_INV7_EXCEPTIONS), (
        f"INV-7 gaps found at {set(violations)}, expected exactly {set(KNOWN_INV7_EXCEPTIONS)} "
        "(schema.spec.md's documented blank-code-cell exception)"
    )
    for code, expected in KNOWN_INV7_EXCEPTIONS.items():
        row = violations[code]
        assert row["c"] == expected["count"], f"{code}: count={row['c']}, expected {expected['count']}"
        assert row["m"] == expected["max"], f"{code}: max={row['m']}, expected {expected['max']}"

        numbers = {
            r["task_number"]
            for r in conn.execute(
                """
                SELECT pt.task_number FROM position_tasks pt
                JOIN positions p ON p.id = pt.position_id
                WHERE p.code = ?
                """,
                (code,),
            ).fetchall()
        }
        missing = set(range(1, expected["max"] + 1)) - numbers
        assert missing == expected["missing"], f"{code}: missing={missing}, expected {expected['missing']}"


# ---------------------------------------------------------------------------
# INV-8 (bonus, not in the "seven" but present in the spec's Invariants
# list): level/behavior non-NULL iff enhanced_gdoc; every enhanced_gdoc
# source_document has official=0. Needs the enhanced_gdoc doc, which is not
# among the 5 named fixtures, so this uses the full-corpus DB.
# ---------------------------------------------------------------------------


def test_inv8_level_behavior_only_on_enhanced_gdoc(full_db_conn):
    conn = full_db_conn
    bad = conn.execute(
        """
        SELECT pt.id FROM position_tasks pt
        JOIN positions p ON p.id = pt.position_id
        JOIN source_documents sd ON sd.id = p.source_document_id
        WHERE (sd.format = 'enhanced_gdoc' AND (pt.level IS NULL OR pt.behavior IS NULL))
           OR (sd.format != 'enhanced_gdoc' AND (pt.level IS NOT NULL OR pt.behavior IS NOT NULL))
        """
    ).fetchall()
    assert bad == []


def test_inv8_enhanced_gdoc_is_never_official(full_db_conn):
    conn = full_db_conn
    bad = conn.execute("SELECT filename FROM source_documents WHERE format = 'enhanced_gdoc' AND official != 0").fetchall()
    assert bad == []
    has_enhanced = conn.execute("SELECT COUNT(*) FROM source_documents WHERE format = 'enhanced_gdoc'").fetchone()[0]
    assert has_enhanced > 0, "expected the enhanced_gdoc fixture to be present in the full corpus load"


# ---------------------------------------------------------------------------
# AC-S4: attempting to violate each CHECK/UNIQUE constraint raises
# sqlite3.IntegrityError.
# ---------------------------------------------------------------------------


def test_source_documents_format_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO source_documents (filename, url, sha256, format, downloaded_at)
               VALUES ('x.pdf', 'http://x', 'sha', 'bogus_format', '2026-07-09')"""
        )


def test_source_documents_role_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO source_documents (filename, url, sha256, format, role, downloaded_at)
               VALUES ('x.pdf', 'http://x', 'sha', 'nwcg_nextgen', 'bogus_role', '2026-07-09')"""
        )


def test_source_documents_official_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO source_documents (filename, url, sha256, format, official, downloaded_at)
               VALUES ('x.pdf', 'http://x', 'sha', 'nwcg_nextgen', 2, '2026-07-09')"""
        )


def test_source_documents_filename_unique(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute(
            """INSERT INTO source_documents (filename, url, sha256, format, downloaded_at)
               VALUES ('seed.pdf', 'http://x', 'sha', 'nwcg_nextgen', '2026-07-09')"""
        )


def test_positions_code_unique(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute(
            "INSERT INTO positions (code, title, source_document_id) VALUES ('AAAA', 'Dup', 1)"
        )


def test_positions_provisional_code_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            "INSERT INTO positions (code, title, provisional_code, source_document_id) VALUES ('CCCC', 'C', 2, 1)"
        )


def test_positions_source_document_fk(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        seeded_conn.execute(
            "INSERT INTO positions (code, title, source_document_id) VALUES ('DDDD', 'D', 999)"
        )


def test_tasks_normalized_text_unique(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute("INSERT INTO tasks (canonical_text, normalized_text) VALUES ('Task One Dup.', 'task one')")


def test_position_tasks_unique_position_task_number(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute(
            """INSERT INTO position_tasks
               (position_id, task_id, task_number, category, verbatim_text, code_raw, code_alternatives, page)
               VALUES (1, 2, 1, 'Category', 'Task Two.', 'O', '["O"]', 1)"""
        )


def test_position_tasks_level_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO position_tasks
               (position_id, task_id, task_number, category, level, verbatim_text, code_raw, code_alternatives, page)
               VALUES (1, 2, 2, 'Category', 'Wizard', 'Task Two.', 'O', '["O"]', 1)"""
        )


def test_position_tasks_position_fk(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        seeded_conn.execute(
            """INSERT INTO position_tasks
               (position_id, task_id, task_number, category, verbatim_text, code_raw, code_alternatives, page)
               VALUES (999, 2, 2, 'Category', 'Task Two.', 'O', '["O"]', 1)"""
        )


def test_position_tasks_task_fk(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        seeded_conn.execute(
            """INSERT INTO position_tasks
               (position_id, task_id, task_number, category, verbatim_text, code_raw, code_alternatives, page)
               VALUES (1, 999, 2, 'Category', 'Task Two.', 'O', '["O"]', 1)"""
        )


def test_task_equivalences_relation_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO task_equivalences (task_a_id, task_b_id, relation, tier, method, status)
               VALUES (1, 2, 'bogus_relation', 1, 'normalized_text', 'confirmed')"""
        )


def test_task_equivalences_tier_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO task_equivalences (task_a_id, task_b_id, relation, tier, method, status)
               VALUES (1, 2, 'equivalent', 4, 'normalized_text', 'confirmed')"""
        )


def test_task_equivalences_status_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO task_equivalences (task_a_id, task_b_id, relation, tier, method, status)
               VALUES (1, 2, 'equivalent', 1, 'normalized_text', 'bogus_status')"""
        )


def test_task_equivalences_ordering_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO task_equivalences (task_a_id, task_b_id, relation, tier, method, status)
               VALUES (2, 1, 'equivalent', 1, 'normalized_text', 'confirmed')"""
        )


def test_task_equivalences_unique_pair(seeded_conn):
    seeded_conn.execute(
        """INSERT INTO task_equivalences (task_a_id, task_b_id, relation, tier, method, status)
           VALUES (1, 2, 'equivalent', 1, 'normalized_text', 'confirmed')"""
    )
    seeded_conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute(
            """INSERT INTO task_equivalences (task_a_id, task_b_id, relation, tier, method, status)
               VALUES (1, 2, 'related_not_equivalent', 2, 'embedding+adjudication', 'probable')"""
        )


def test_position_requirements_kind_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO position_requirements (position_id, kind, value, source)
               VALUES (1, 'bogus_kind', 'S-230', 'test')"""
        )


def test_position_requirements_unique(seeded_conn):
    seeded_conn.execute(
        """INSERT INTO position_requirements (position_id, kind, value, source)
           VALUES (1, 'course', 'S-230', 'test')"""
    )
    seeded_conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute(
            """INSERT INTO position_requirements (position_id, kind, value, source)
               VALUES (1, 'course', 'S-230', 'test-dup')"""
        )


def test_position_requirements_position_fk(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        seeded_conn.execute(
            """INSERT INTO position_requirements (position_id, kind, value, source)
               VALUES (999, 'course', 'S-230', 'test')"""
        )


def test_position_implications_no_self_reference_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            "INSERT INTO position_implications (holding_position_id, implied_position_id, source) VALUES (1, 1, 'test')"
        )


def test_position_implications_unique(seeded_conn):
    seeded_conn.execute(
        "INSERT INTO position_implications (holding_position_id, implied_position_id, source) VALUES (1, 2, 'test')"
    )
    seeded_conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute(
            "INSERT INTO position_implications (holding_position_id, implied_position_id, source) VALUES (1, 2, 'test-dup')"
        )


def test_position_implications_fk(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        seeded_conn.execute(
            "INSERT INTO position_implications (holding_position_id, implied_position_id, source) VALUES (1, 999, 'test')"
        )


def test_field_coverage_status_check(seeded_conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        seeded_conn.execute(
            """INSERT INTO field_coverage (format, field_name, status, evidence)
               VALUES ('nwcg_nextgen', 'foo', 'bogus_status', 'test')"""
        )


def test_field_coverage_unique(seeded_conn):
    seeded_conn.execute(
        """INSERT INTO field_coverage (format, field_name, status, evidence)
           VALUES ('nwcg_nextgen', 'foo', 'captured', 'test')"""
    )
    seeded_conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        seeded_conn.execute(
            """INSERT INTO field_coverage (format, field_name, status, evidence)
               VALUES ('nwcg_nextgen', 'foo', 'absent_from_format', 'test-dup')"""
        )
