"""Phase 5 acceptance tests: specs/gap-analysis.spec.md AC-G1 through AC-G8.

Most tests run against the shipped data/ptb.sqlite (the real corpus), the
same pattern test_matching.py uses for its artifact tests. AC-G5
(subsumption directionality) builds a small controlled in-memory DB instead,
because it needs a *confirmed* tier-2 row and human review of the real
corpus's tier-2 layer is still pending (data/ptb.sqlite currently has zero
confirmed tier-2 rows) — see PLAN.md Phase 4.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import db, gap  # noqa: E402

REAL_DB = REPO_ROOT / "data" / "ptb.sqlite"


@pytest.fixture(scope="module")
def real_conn() -> sqlite3.Connection:
    conn = db.connect(REAL_DB)
    yield conn
    conn.close()


def _pair_status(conn: sqlite3.Connection, task_a: int, task_b: int) -> str | None:
    lo, hi = min(task_a, task_b), max(task_a, task_b)
    row = conn.execute(
        "SELECT status FROM task_equivalences WHERE task_a_id = ? AND task_b_id = ?", (lo, hi)
    ).fetchone()
    return row["status"] if row else None


def _position_task_id(conn: sqlite3.Connection, code: str, task_number: int) -> int:
    row = conn.execute(
        """
        SELECT pt.id FROM position_tasks pt JOIN positions p ON pt.position_id = p.id
        WHERE p.code = ? AND pt.task_number = ?
        """,
        (code, task_number),
    ).fetchone()
    assert row is not None, f"{code} #{task_number} not found"
    return row["id"]


def _gap_for(results: list[gap.PositionGap], code: str) -> gap.PositionGap:
    matches = [r for r in results if r.position == code]
    assert matches, f"{code} missing from results"
    return matches[0]


# ---------------------------------------------------------------------------
# AC-G1: ENGB -> FIRB worked example
# ---------------------------------------------------------------------------


def test_ac_g1_engb_to_firb_worked_example(real_conn: sqlite3.Connection) -> None:
    profile = gap.CandidateProfile(held_qualifications=["ENGB"])
    results = gap.closest_positions(profile, conn=real_conn)

    firb = _gap_for(results, "FIRB")

    # #11 depends on ENGB#9/FIRB#11 subsumption (task ids 340/407) being confirmed.
    subsumption_confirmed = _pair_status(real_conn, 340, 407) == "confirmed"
    # #13 depends on ENGB#16/FIRB#13 equivalence (task ids 347/409) being confirmed.
    equivalence_confirmed = _pair_status(real_conn, 347, 409) == "confirmed"

    satisfied_numbers = {s.task_number for s in firb.satisfied}
    gap_numbers = {s.task_number for s in firb.gaps_tasks}

    # Always satisfied via implied-by-qualification (tier-1 sharing with ENGB).
    always_satisfied = {1, 2, 3, 4, 5, 10, 14, 15, 16, 17}
    assert always_satisfied <= satisfied_numbers

    # Always gaps regardless of review status.
    always_gaps = {6, 7, 8, 9, 12}
    assert always_gaps <= gap_numbers

    assert (11 in satisfied_numbers) is subsumption_confirmed
    assert (11 in gap_numbers) is not subsumption_confirmed
    assert (13 in satisfied_numbers) is equivalence_confirmed
    assert (13 in gap_numbers) is not equivalence_confirmed

    # No context-only gaps expected in this example (ENGB's contexts are a
    # superset of what FIRB's slots need for the implied-by-qualification rule,
    # which doesn't gate on context at all).
    assert firb.gaps_context_only == []

    # FIRB's course/prerequisite requirements are all implied by ENGB's own chain.
    assert firb.gaps_requirements == []
    gated_kinds = {r.kind for r in firb.satisfied_requirements}
    assert "course" in gated_kinds
    assert "prerequisite_position" in gated_kinds
    assert all(r.derivation == "implied_by" and r.derivation_position == "ENGB" for r in firb.satisfied_requirements)

    # Ranking: FIRB outranks (or ties with) CRWB and any unrelated position.
    codes_in_order = [r.position for r in results]
    assert codes_in_order.index("FIRB") <= codes_in_order.index("CRWB")
    lofr = _gap_for(results, "LOFR")
    firb_remaining = len(firb.gaps_tasks) + len(firb.gaps_context_only) + len(firb.gaps_requirements)
    lofr_remaining = len(lofr.gaps_tasks) + len(lofr.gaps_context_only) + len(lofr.gaps_requirements)
    assert firb_remaining < lofr_remaining
    assert len(lofr.satisfied) <= 2  # "near-zero satisfaction"


# ---------------------------------------------------------------------------
# AC-G2: nothing in a gap list is satisfiable under rules 1-5
# ---------------------------------------------------------------------------


def test_ac_g2_no_gap_item_double_counted(real_conn: sqlite3.Connection) -> None:
    profiles = [
        gap.CandidateProfile(held_qualifications=["ENGB"]),
        gap.CandidateProfile(held_qualifications=["FIRB"]),
        gap.CandidateProfile(held_qualifications=["CRWB"]),
        gap.CandidateProfile(held_qualifications=["UASP", "FIRB"]),
        gap.CandidateProfile(held_qualifications=[], completed_courses=["S-230"]),
        gap.CandidateProfile(held_qualifications=["ICT3"]),
    ]
    for profile in profiles:
        results = gap.closest_positions(profile, conn=real_conn)
        for pg in results:
            satisfied_ids = {s.position_task_id for s in pg.satisfied}
            gap_task_ids = {s.position_task_id for s in pg.gaps_tasks}
            gap_ctx_ids = {s.position_task_id for s in pg.gaps_context_only}
            # A slot lands in exactly one bucket.
            assert satisfied_ids.isdisjoint(gap_task_ids)
            assert satisfied_ids.isdisjoint(gap_ctx_ids)
            assert gap_task_ids.isdisjoint(gap_ctx_ids)
            assert len(satisfied_ids) + len(gap_task_ids) + len(gap_ctx_ids) == pg.total_slots

            satisfied_req_keys = {(r.kind, r.value) for r in pg.satisfied_requirements}
            gap_req_keys = {(r.kind, r.value) for r in pg.gaps_requirements}
            assert satisfied_req_keys.isdisjoint(gap_req_keys)


# ---------------------------------------------------------------------------
# AC-G3: every satisfied item carries a derivation; tier-2 cites a confirmed row
# ---------------------------------------------------------------------------


def test_ac_g3_derivations_and_confirmed_equivalence_citations(real_conn: sqlite3.Connection) -> None:
    profile = gap.CandidateProfile(held_qualifications=["ENGB"])
    results = gap.closest_positions(profile, conn=real_conn)

    for pg in results:
        for s in pg.satisfied:
            assert s.derivation in ("direct", "implied_by")
            if s.derivation == "implied_by":
                assert s.derivation_position is not None
            if s.equivalence_id is not None:
                row = real_conn.execute(
                    "SELECT status FROM task_equivalences WHERE id = ?", (s.equivalence_id,)
                ).fetchone()
                assert row is not None
                assert row["status"] == "confirmed"
        for r in pg.satisfied_requirements:
            assert r.derivation in ("direct", "implied_by", "conferred_by")
            if r.derivation != "direct":
                assert r.derivation_position is not None


# ---------------------------------------------------------------------------
# AC-G4: context gating
# ---------------------------------------------------------------------------


def test_ac_g4_context_gating(real_conn: sqlite3.Connection) -> None:
    fft1_task2 = _position_task_id(real_conn, "FFT1", 2)  # code O
    profile = gap.CandidateProfile(
        completed_task_ids=[gap.CompletedTask(position_task_id=fft1_task2, context="other")]
    )
    results = gap.closest_positions(profile, conn=real_conn)

    fft1 = _gap_for(results, "FFT1")
    assert any(s.task_number == 2 and s.derivation == "direct" for s in fft1.satisfied)

    firb = _gap_for(results, "FIRB")
    assert not any(s.task_number == 2 for s in firb.satisfied)
    assert any(s.task_number == 2 for s in firb.gaps_context_only)
    assert not any(s.task_number == 2 for s in firb.gaps_tasks)


def test_code_satisfied_matrix() -> None:
    assert gap.code_satisfied("O", "other", is_enhanced_format=False)
    assert gap.code_satisfied("O", "developmental", is_enhanced_format=False)
    assert gap.code_satisfied("W/RX", "wildfire", is_enhanced_format=False)
    assert gap.code_satisfied("W/RX", "prescribed_fire", is_enhanced_format=False)
    assert not gap.code_satisfied("W/RX", "other", is_enhanced_format=False)

    # Enhanced format's O redefinition: only 'developmental' satisfies it.
    assert gap.code_satisfied("O", "developmental", is_enhanced_format=True)
    assert not gap.code_satisfied("O", "other", is_enhanced_format=True)
    assert not gap.code_satisfied("O", "wildfire", is_enhanced_format=True)


# ---------------------------------------------------------------------------
# AC-G5: subsumption directionality (controlled fixture — needs a confirmed row)
# ---------------------------------------------------------------------------


@pytest.fixture
def subsumption_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)

    conn.execute(
        """INSERT INTO source_documents
           (id, filename, url, sha256, format, role, official, pms_number, edition_date, downloaded_at)
           VALUES (1, 'seed.pdf', 'http://example.test/seed.pdf', 'abc', 'nwcg_nextgen', 'ptb', 1,
                   '311-00', '2026-01-01', '2026-07-11')"""
    )
    conn.execute("INSERT INTO positions (id, code, title, provisional_code, source_document_id) VALUES (1, 'BROD', 'Broad Position', 0, 1)")
    conn.execute("INSERT INTO positions (id, code, title, provisional_code, source_document_id) VALUES (2, 'NARW', 'Narrow Position', 0, 1)")
    conn.execute("INSERT INTO tasks (id, canonical_text, normalized_text) VALUES (10, 'Broad task.', 'broad task')")
    conn.execute("INSERT INTO tasks (id, canonical_text, normalized_text) VALUES (20, 'Narrow task.', 'narrow task')")
    conn.execute(
        """INSERT INTO position_tasks
           (id, position_id, task_id, task_number, category, behavior, level,
            verbatim_text, code_raw, code_alternatives, clarifications, page)
           VALUES (100, 1, 10, 1, 'Cat', NULL, NULL, 'Broad task.', 'O', '["O"]', '[]', 1)"""
    )
    conn.execute(
        """INSERT INTO position_tasks
           (id, position_id, task_id, task_number, category, behavior, level,
            verbatim_text, code_raw, code_alternatives, clarifications, page)
           VALUES (200, 2, 20, 1, 'Cat', NULL, NULL, 'Narrow task.', 'O', '["O"]', '[]', 1)"""
    )
    # task_a_id (10) subsumes task_b_id (20): completing the broad task (10)
    # satisfies the narrow slot (20); completing the narrow task never
    # satisfies the broad slot.
    conn.execute(
        """INSERT INTO task_equivalences
           (task_a_id, task_b_id, relation, tier, method, similarity_score,
            adjudication_note, human_reviewed_at, status)
           VALUES (10, 20, 'a_subsumes_b', 2, 'test-fixture', 0.9, 'test', '2026-07-11', 'confirmed')"""
    )
    conn.commit()
    yield conn
    conn.close()


def test_ac_g5_subsumption_directionality(subsumption_conn: sqlite3.Connection) -> None:
    # Completing the narrow task (position_task_id 200) must NOT satisfy BROD's slot.
    profile_narrow = gap.CandidateProfile(
        completed_task_ids=[gap.CompletedTask(position_task_id=200, context="other")]
    )
    results_narrow = gap.closest_positions(profile_narrow, conn=subsumption_conn)
    brod = _gap_for(results_narrow, "BROD")
    assert brod.satisfied == []
    assert len(brod.gaps_tasks) == 1

    # Completing the broad task (position_task_id 100) DOES satisfy NARW's slot.
    profile_broad = gap.CandidateProfile(
        completed_task_ids=[gap.CompletedTask(position_task_id=100, context="other")]
    )
    results_broad = gap.closest_positions(profile_broad, conn=subsumption_conn)
    narw = _gap_for(results_broad, "NARW")
    assert len(narw.satisfied) == 1
    assert narw.satisfied[0].derivation == "direct"
    assert narw.satisfied[0].equivalence_id is not None
    assert narw.gaps_tasks == []


# ---------------------------------------------------------------------------
# AC-G6: honesty contract wording
# ---------------------------------------------------------------------------


def test_ac_g6_disclaimer_and_no_qualified_claim(real_conn: sqlite3.Connection) -> None:
    profile = gap.CandidateProfile(held_qualifications=["ENGB"])
    results = gap.closest_positions(profile, conn=real_conn)
    text = gap.format_report(profile, results)

    assert gap.DISCLAIMER in text
    assert "you are qualified" not in text.lower()


# ---------------------------------------------------------------------------
# AC-G7: deterministic, stable ranking
# ---------------------------------------------------------------------------


def test_ac_g7_ranking_is_deterministic(real_conn: sqlite3.Connection) -> None:
    profile = gap.CandidateProfile(held_qualifications=["ENGB"], completed_courses=["S-230"])
    order_1 = [r.position for r in gap.closest_positions(profile, conn=real_conn)]
    order_2 = [r.position for r in gap.closest_positions(profile, conn=real_conn)]
    order_3 = [r.position for r in gap.closest_positions(profile, conn=real_conn)]
    assert order_1 == order_2 == order_3


# ---------------------------------------------------------------------------
# AC-G8: enhanced draft position (UAIS) with prerequisites satisfied
# ---------------------------------------------------------------------------


def test_ac_g8_uais_draft_position_prerequisites(real_conn: sqlite3.Connection) -> None:
    profile = gap.CandidateProfile(held_qualifications=["UASP", "FIRB"])
    results = gap.closest_positions(profile, conn=real_conn)

    uais = _gap_for(results, "UAIS")
    assert uais.draft is True

    prereq_reqs = {r.value: r for r in uais.satisfied_requirements if r.kind == "prerequisite_position"}
    assert set(prereq_reqs) == {"UASP", "FIRB"}
    for r in prereq_reqs.values():
        assert r.derivation == "direct"

    # None of UAIS's prerequisite requirements show up as gaps.
    assert not any(r.kind == "prerequisite_position" for r in uais.gaps_requirements)

    info_kinds = {r.kind for r in uais.info_requirements}
    assert info_kinds == {"training", "experience", "fitness", "currency"}
    # Info requirements are never counted as gaps or satisfied requirements.
    gated_values = {(r.kind, r.value) for r in uais.gaps_requirements} | {
        (r.kind, r.value) for r in uais.satisfied_requirements
    }
    for r in uais.info_requirements:
        assert (r.kind, r.value) not in gated_values

    # UAIS still held-excluded positions (UASP, FIRB) do not appear in results.
    assert not any(r.position in ("UASP", "FIRB") for r in results)


# ---------------------------------------------------------------------------
# Rule 4 for prerequisite codes with no task book (gap-analysis.spec.md
# changelog 2026-11-03): ENGB -> FFT1 -> FFT2, so an ENGB holder must never be
# re-demanded FFT2 even though FFT2 has no `positions` row.
# ---------------------------------------------------------------------------


def test_rule4_prerequisite_without_positions_row_is_not_redemanded(real_conn):
    assert real_conn.execute("SELECT COUNT(*) FROM positions WHERE code = 'FFT2'").fetchone()[0] == 0
    profile = gap.CandidateProfile(held_qualifications=["ENGB"], completed_courses=[], completed_task_ids=[])
    results = gap.closest_positions(profile, conn=real_conn)
    fft1 = _gap_for(results, "FFT1")
    assert not any(r.value == "FFT2" for r in fft1.gaps_requirements), fft1.gaps_requirements
    waived = [r for r in fft1.satisfied_requirements if r.value == "FFT2"]
    assert waived and waived[0].derivation == "implied_by" and waived[0].derivation_position == "ENGB"
    for pg in results:
        assert not any(r.kind == "prerequisite_position" and r.value == "FFT2" for r in pg.gaps_requirements), pg.position
