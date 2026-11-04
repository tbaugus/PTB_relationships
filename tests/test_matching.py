"""Phase 4 acceptance tests: specs/matching.spec.md AC-M1 through AC-M8.

Two kinds of tests:

1. Artifact tests — verify the SHIPPED Phase-4 outputs (data/ptb.sqlite,
   data/tier2_candidates.json, data/adjudications.json,
   reports/tier2_review_checklist.md) satisfy the acceptance criteria.
   These need no embedding model and run fast.

2. Pipeline tests — rebuild the tier-2 layer live against the 5-fixture
   corpus (session-scoped; loads the pinned sentence-transformers model on
   CPU) to prove reproducibility (AC-M6) and the text-keyed portability of
   verdicts across database rebuilds (task ids differ in the fixture DB,
   yet the same adjudications file applies cleanly).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from conftest import REPO_ROOT

import sys

sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import adjudicate, db, match  # noqa: E402

REAL_DB = REPO_ROOT / "data" / "ptb.sqlite"
CANDIDATES_PATH = match.DEFAULT_CANDIDATES_PATH
ADJUDICATIONS_PATH = adjudicate.ADJUDICATIONS_PATH
CHECKLIST_PATH = adjudicate.CHECKLIST_PATH


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def real_conn() -> sqlite3.Connection:
    conn = db.connect(REAL_DB)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def candidates_payload() -> dict:
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def adjudications() -> dict:
    return adjudicate.load_adjudications()


def task_id(conn: sqlite3.Connection, code: str, number: int) -> int:
    row = conn.execute(
        """SELECT pt.task_id FROM position_tasks pt
           JOIN positions p ON p.id = pt.position_id
           WHERE p.code = ? AND pt.task_number = ?""",
        (code, number),
    ).fetchone()
    assert row is not None, f"{code} #{number} not found"
    return row["task_id"]


def equivalence_row(conn: sqlite3.Connection, code_a: str, num_a: int, code_b: str, num_b: int):
    a, b = sorted((task_id(conn, code_a, num_a), task_id(conn, code_b, num_b)))
    return a, b, conn.execute(
        "SELECT * FROM task_equivalences WHERE task_a_id = ? AND task_b_id = ?", (a, b)
    ).fetchone()


# ---------------------------------------------------------------------------
# AC-M1: all six grounded tier-1 examples share task_ids.
# (Tier-1 sharing is the shared task_id itself — INV-3; no equivalence rows.)
# ---------------------------------------------------------------------------

TIER1_GROUPS = [
    [("FFT1", 2), ("ENGB", 4), ("FIRB", 2)],     # Gather critical information...
    [("FFT1", 4), ("ENGB", 5), ("FIRB", 3)],     # Assemble and validate readiness...
    [("FFT1", 22), ("ENGB", 19), ("FIRB", 14)],  # Apply the Risk Management Process.
    [("ENGB", 21), ("CRWB", 31), ("FIRB", 16)],  # Develop and communicate contingency plans...
    [("ENGB", 22), ("FIRB", 17)],                # Plan for and manage medical emergencies.
    [("FFT1", 21), ("ENGB", 18), ("CRWB", 29)],  # AARs (via abbreviation table)
]


@pytest.mark.parametrize("group", TIER1_GROUPS)
def test_ac_m1_grounded_tier1_examples_share_task_ids(fixture_db_conn, group):
    ids = {task_id(fixture_db_conn, code, num) for code, num in group}
    assert len(ids) == 1, f"{group} do not share one task_id: {ids}"


@pytest.mark.parametrize("group", TIER1_GROUPS)
def test_ac_m1_holds_on_full_corpus_too(real_conn, group):
    ids = {task_id(real_conn, code, num) for code, num in group}
    assert len(ids) == 1


# ---------------------------------------------------------------------------
# AC-M2: ENGB #16 / FIRB #13 is a tier-2 candidate, not tier-1.
# ---------------------------------------------------------------------------


def test_ac_m2_engb16_firb13_not_tier1(real_conn):
    assert task_id(real_conn, "ENGB", 16) != task_id(real_conn, "FIRB", 13)


def test_ac_m2_engb16_firb13_is_tier2_candidate(real_conn, candidates_payload):
    a, b, row = equivalence_row(real_conn, "ENGB", 16, "FIRB", 13)
    keys = {c["pair_key"] for c in candidates_payload["candidates"]}
    ids = {(c["a"]["task_id"], c["b"]["task_id"]) for c in candidates_payload["candidates"]}
    assert (a, b) in ids, "pair missing from candidate generation output"
    assert row is not None and row["tier"] == 2
    assert row["similarity_score"] >= match.CANDIDATE_THRESHOLD
    assert match.pair_key(*_norms(real_conn, a, b)) in keys


def _norms(conn, a_id, b_id):
    get = lambda i: conn.execute("SELECT normalized_text FROM tasks WHERE id=?", (i,)).fetchone()[0]
    return get(a_id), get(b_id)


# ---------------------------------------------------------------------------
# AC-M3: FFT1#10/ENGB#9 ends related_not_equivalent;
#        FIRB#11/ENGB#9 ends a_subsumes_b with ENGB as subsumer.
# ---------------------------------------------------------------------------


def test_ac_m3_lookout_vs_scout_related_not_equivalent(real_conn):
    _, _, row = equivalence_row(real_conn, "FFT1", 10, "ENGB", 9)
    assert row is not None, "seeded grounded pair missing from task_equivalences"
    assert row["relation"] == "related_not_equivalent"
    assert row["status"] == "rejected" and row["tier"] == 3


def test_ac_m3_engb9_subsumes_firb11(real_conn):
    engb, firb = task_id(real_conn, "ENGB", 9), task_id(real_conn, "FIRB", 11)
    a, b = sorted((engb, firb))
    row = real_conn.execute(
        "SELECT * FROM task_equivalences WHERE task_a_id=? AND task_b_id=?", (a, b)
    ).fetchone()
    assert row is not None
    subsumer = a if row["relation"] == "a_subsumes_b" else b
    assert row["relation"] in ("a_subsumes_b", "b_subsumes_a")
    assert subsumer == engb, "ENGB #9 must be the subsumer"
    assert row["tier"] == 2 and row["status"] in ("probable", "confirmed", "rejected")


def test_rubric_case3_engb8_subsumes_crwb19_and_note_addresses_adjust(real_conn):
    engb, crwb = task_id(real_conn, "ENGB", 8), task_id(real_conn, "CRWB", 19)
    a, b = sorted((engb, crwb))
    row = real_conn.execute(
        "SELECT * FROM task_equivalences WHERE task_a_id=? AND task_b_id=?", (a, b)
    ).fetchone()
    assert row is not None
    # Spec: expected verdict a_subsumes_b (ENGB subsumes CRWB); acceptable
    # verdict equivalent — the note must address "adjust" either way.
    if row["relation"] in ("a_subsumes_b", "b_subsumes_a"):
        subsumer = a if row["relation"] == "a_subsumes_b" else b
        assert subsumer == engb
    else:
        assert row["relation"] == "equivalent"
    assert "adjust" in row["adjudication_note"].lower()


def test_rubric_case4_firing_triple_never_blanket_equivalent(real_conn):
    pairs = [
        ("ENGB", 13, "FIRB", 9),
        ("ENGB", 13, "CRWB", 14),
        ("FIRB", 9, "CRWB", 14),
    ]
    for ca, na, cb, nb in pairs:
        _, _, row = equivalence_row(real_conn, ca, na, cb, nb)
        assert row is not None, f"firing triple pair {ca}#{na}/{cb}#{nb} missing"
        assert row["relation"] != "equivalent", (
            f"{ca}#{na}/{cb}#{nb} must never be blanket equivalence"
        )


# ---------------------------------------------------------------------------
# AC-M4: zero tier-2 rows reach 'confirmed' without human_reviewed_at,
# and the only path to 'confirmed' (promote) always sets it.
# ---------------------------------------------------------------------------


def test_ac_m4_no_unreviewed_confirmed_rows(real_conn):
    bad = real_conn.execute(
        """SELECT COUNT(*) FROM task_equivalences
           WHERE status = 'confirmed' AND human_reviewed_at IS NULL"""
    ).fetchone()[0]
    assert bad == 0


def test_ac_m4_every_confirmed_row_traces_to_a_human_decision(real_conn):
    # Claude never promotes; the human does. Until the first review sheet was
    # ingested (F2, 2026-11-04) this asserted zero confirmed rows; the durable
    # invariant is that every confirmed row has human_reviewed_at AND a
    # matching 'confirm' decision in data/confirmations.json.
    confirmations = adjudicate.load_confirmations()
    confirmed_keys = {k for k, v in confirmations.items() if v["decision"] == "confirm"}
    rows = real_conn.execute(
        """SELECT ta.normalized_text, tb.normalized_text, e.human_reviewed_at
           FROM task_equivalences e
           JOIN tasks ta ON ta.id = e.task_a_id JOIN tasks tb ON tb.id = e.task_b_id
           WHERE e.status = 'confirmed'"""
    ).fetchall()
    assert rows, "expected the ingested review sheet to have produced confirmed rows"
    for text_a, text_b, reviewed_at in rows:
        pair_key = match.pair_key(text_a, text_b)
        assert reviewed_at, f"{pair_key} confirmed without human_reviewed_at"
        assert pair_key in confirmed_keys, f"{pair_key} confirmed with no human decision on file"
        assert confirmations[pair_key]["human_reviewed_at"] == reviewed_at


def test_ac_m4_confirmations_loader_requires_timestamp(tmp_path):
    p = tmp_path / "confirmations.json"
    p.write_text(json.dumps({"confirmations": [{"pair_key": "x", "decision": "confirm"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="human_reviewed_at"):
        adjudicate.load_confirmations(p)


def test_ac_m4_promote_confirm_sets_human_reviewed_at(tmp_path, candidates_payload, adjudications):
    # Copy the real DB, promote one probable pair into it, verify the row.
    import shutil

    tmp_db = tmp_path / "ptb.sqlite"
    shutil.copy2(REAL_DB, tmp_db)
    probable_key = next(
        c["pair_key"] for c in candidates_payload["candidates"]
        if adjudications[c["pair_key"]]["relation"] != "related_not_equivalent"
    )
    stats = adjudicate.promote(
        probable_key,
        "confirm",
        reviewer="pytest",
        confirmations_path=tmp_path / "confirmations.json",
        db_path=tmp_db,
        checklist_path=tmp_path / "checklist.md",
        pending_path=tmp_path / "pending.json",
    )
    assert stats["db_written"] and stats["tier2_confirmed"] == 1
    conn = db.connect(tmp_db)
    try:
        row = conn.execute(
            "SELECT * FROM task_equivalences WHERE status='confirmed'"
        ).fetchone()
        assert row is not None and row["human_reviewed_at"]
        assert conn.execute(
            "SELECT COUNT(*) FROM task_equivalences WHERE status='confirmed' AND human_reviewed_at IS NULL"
        ).fetchone()[0] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AC-M5: every row has method; tier-2 (and tier-3) rows have score + note.
# ---------------------------------------------------------------------------


def test_ac_m5_method_score_note_present(real_conn):
    assert real_conn.execute(
        "SELECT COUNT(*) FROM task_equivalences WHERE method IS NULL OR method = ''"
    ).fetchone()[0] == 0
    assert real_conn.execute(
        """SELECT COUNT(*) FROM task_equivalences
           WHERE tier IN (2,3) AND (similarity_score IS NULL
                 OR adjudication_note IS NULL OR adjudication_note = '')"""
    ).fetchone()[0] == 0


def test_ac_m5_method_pins_model_and_version(real_conn):
    methods = {r[0] for r in real_conn.execute("SELECT DISTINCT method FROM task_equivalences")}
    for m in methods:
        assert match.MODEL_NAME in m
        assert match.MODEL_REVISION[:12] in m
        assert "sentence-transformers" in m


# ---------------------------------------------------------------------------
# AC-M6: reproducibility — rerunning on unchanged corpus produces an
# identical task_equivalences table.
# ---------------------------------------------------------------------------


def _dump_table(conn) -> list[tuple]:
    return conn.execute(
        "SELECT * FROM task_equivalences ORDER BY id"
    ).fetchall()


def test_ac_m6_apply_is_deterministic_and_reproduces_shipped_table(tmp_path):
    import shutil

    before = None
    conn = db.connect(REAL_DB)
    try:
        before = [tuple(r) for r in _dump_table(conn)]
    finally:
        conn.close()

    tmp_db = tmp_path / "ptb.sqlite"
    shutil.copy2(REAL_DB, tmp_db)
    for _ in range(2):  # rerun twice: identical output both times
        stats = adjudicate.apply(
            db_path=tmp_db,
            checklist_path=tmp_path / "checklist.md",
            pending_path=tmp_path / "pending.json",
        )
        assert stats["pending"] == 0 and stats["db_written"]
        conn = db.connect(tmp_db)
        try:
            after = [tuple(r) for r in _dump_table(conn)]
        finally:
            conn.close()
        assert after == before, "task_equivalences table not reproduced identically"


def test_ac_m6_model_identity_is_pinned():
    assert match.MODEL_NAME == "sentence-transformers/all-MiniLM-L6-v2"
    assert re.fullmatch(r"[0-9a-f]{40}", match.MODEL_REVISION)
    assert match.CANDIDATE_THRESHOLD == 0.80


# ---------------------------------------------------------------------------
# AC-M7: the generated checklist lists every 'probable' pair with both
# verbatim texts, positions, categories, score, and adjudication note.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def checklist_text() -> str:
    return CHECKLIST_PATH.read_text(encoding="utf-8")


def test_ac_m7_checklist_covers_every_probable_pair(real_conn, checklist_text):
    # Every probable row, tier-2 AND NTFT-bridge layer (both share the checklist).
    by_ids = {(c["a"]["task_id"], c["b"]["task_id"]): c for c in adjudicate.load_all_candidates()}
    probable = real_conn.execute(
        "SELECT * FROM task_equivalences WHERE status = 'probable'"
    ).fetchall()
    assert len(probable) > 0
    listed_keys = set(re.findall(r"## \d+\. `([0-9a-f]{16})`", checklist_text))
    expected_keys = {by_ids[(r["task_a_id"], r["task_b_id"])]["pair_key"] for r in probable}
    assert listed_keys == expected_keys


def test_ac_m7_checklist_entries_carry_required_fields(real_conn, checklist_text):
    by_ids = {(c["a"]["task_id"], c["b"]["task_id"]): c for c in adjudicate.load_all_candidates()}
    probable = real_conn.execute(
        "SELECT * FROM task_equivalences WHERE status = 'probable'"
    ).fetchall()
    for row in probable:
        cand = by_ids[(row["task_a_id"], row["task_b_id"])]
        # both verbatim (canonical) texts present
        assert cand["a"]["canonical_text"] in checklist_text
        assert cand["b"]["canonical_text"] in checklist_text
        # score and note present
        assert str(row["similarity_score"]) in checklist_text
        assert row["adjudication_note"] in checklist_text
        # positions + categories of every occurrence present
        for side in ("a", "b"):
            for occ in cand[side]["occurrences"]:
                assert f"{occ['position']} #{occ['task_number']}" in checklist_text
                assert occ["category"] in checklist_text


# ---------------------------------------------------------------------------
# AC-M8: ENGB #1, CRWB #1, FIRB #1 share one task_id (normalization step 5);
# FFT1 #1 does not share it.
# ---------------------------------------------------------------------------


def test_ac_m8_leadership_l2_shared_via_step5(fixture_db_conn):
    ids = {task_id(fixture_db_conn, c, 1) for c in ("ENGB", "CRWB", "FIRB")}
    assert len(ids) == 1
    assert task_id(fixture_db_conn, "FFT1", 1) not in ids


def test_ac_m8_holds_on_full_corpus_too(real_conn):
    ids = {task_id(real_conn, c, 1) for c in ("ENGB", "CRWB", "FIRB")}
    assert len(ids) == 1
    assert task_id(real_conn, "FFT1", 1) not in ids


# ---------------------------------------------------------------------------
# Pipeline tests: live candidate generation on the fixture corpus.
# Prove (a) determinism of generation, (b) the ENGB16/FIRB13 candidate
# surfaces from the embedding cut, (c) the text-keyed adjudications file
# applies cleanly to a REBUILT database whose task ids differ from the
# shipped one — the "new position added" rerun path.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fixture_candidates(fixture_db_conn):
    model = match.load_model()
    first = match.generate_candidates(fixture_db_conn, model=model)
    second = match.generate_candidates(fixture_db_conn, model=model)
    return first, second


def test_ac_m6_candidate_generation_is_deterministic(fixture_candidates):
    first, second = fixture_candidates
    as_tuples = lambda cands: [(c.pair_key, c.score, c.a.task_id, c.b.task_id, c.seed_reason) for c in cands]
    assert as_tuples(first) == as_tuples(second)


def test_ac_m2_pair_surfaces_from_embedding_cut(fixture_db_conn, fixture_candidates):
    first, _ = fixture_candidates
    engb, firb = task_id(fixture_db_conn, "ENGB", 16), task_id(fixture_db_conn, "FIRB", 13)
    a, b = sorted((engb, firb))
    hit = [c for c in first if (c.a.task_id, c.b.task_id) == (a, b)]
    assert hit and hit[0].score >= match.CANDIDATE_THRESHOLD and hit[0].seed_reason is None


def test_seeded_grounded_pairs_present_regardless_of_score(fixture_db_conn, fixture_candidates):
    first, _ = fixture_candidates
    seeded = [c for c in first if c.seed_reason]
    assert len(seeded) == len(match.GROUNDED_SEED_PAIRS)
    for c in seeded:
        assert c.score < match.CANDIDATE_THRESHOLD


def test_adjudications_apply_cleanly_to_rebuilt_db(tmp_path, fixture_db_conn, fixture_candidates):
    """The rerun path: fresh DB build (different task ids) + the same
    text-keyed verdict stores -> complete, contradiction-free tier-2 layer."""
    first, _ = fixture_candidates
    payload = match.candidates_to_json(first, task_count=0)
    cand_path = tmp_path / "candidates.json"
    cand_path.write_text(json.dumps(payload), encoding="utf-8")

    # Build a DB file for the fixture corpus (fixture_db_conn's path is not
    # exposed; rebuild quickly from the same 5 fixtures).
    import shutil

    tmp_extracted = tmp_path / "extracted"
    tmp_extracted.mkdir()
    from conftest import FIXTURE_FILENAMES

    for filename in FIXTURE_FILENAMES:
        shutil.copy2(db.EXTRACTED_DIR / filename, tmp_extracted / filename)
    tmp_db = tmp_path / "fixtures.sqlite"
    db.build_database(db_path=tmp_db, extracted_dir=tmp_extracted, requirements_dir=tmp_extracted / "requirements")

    stats = adjudicate.apply(
        db_path=tmp_db,
        candidates_path=cand_path,
        checklist_path=tmp_path / "checklist.md",
        pending_path=tmp_path / "pending.json",
    )
    assert stats["pending"] == 0, "every fixture-corpus candidate must already have a verdict"
    assert stats["db_written"] and stats["rows"] == len(first)

    conn = db.connect(tmp_db)
    try:
        # AC-M3 holds in the rebuilt id-space too.
        engb, firb = task_id(conn, "ENGB", 9), task_id(conn, "FIRB", 11)
        a, b = sorted((engb, firb))
        row = conn.execute(
            "SELECT * FROM task_equivalences WHERE task_a_id=? AND task_b_id=?", (a, b)
        ).fetchone()
        subsumer = a if row["relation"] == "a_subsumes_b" else b
        assert subsumer == engb
    finally:
        conn.close()
