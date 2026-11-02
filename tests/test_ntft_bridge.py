"""F2 ntft-bridge acceptance tests: specs/matching.spec.md "NTFT bridge
candidates" (AC-B1, AC-B2, AC-B3, AC-B4, AC-B7). Feature spec:
docs/F2_ntft_bridge.md.

Artifact tests verify the SHIPPED bridge outputs (data/ntft_candidates.json,
data/adjudications.json bridge entries, bridge rows in data/ptb.sqlite) and
that the default tier-2 pipeline is untouched. One pipeline test runs the
bridge side filter live over the 5-fixture corpus (all NWCG, so the bridge
must be empty there).

AC-B5 / AC-B6 depend on the human review (scope item 8) and are checked at
that step, not here.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from conftest import REPO_ROOT

import sys

sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import adjudicate, db, match  # noqa: E402

REAL_DB = REPO_ROOT / "data" / "ptb.sqlite"
TIER2_PATH = match.DEFAULT_CANDIDATES_PATH
BRIDGE_PATH = match.DEFAULT_NTFT_CANDIDATES_PATH


@pytest.fixture(scope="session")
def real_conn() -> sqlite3.Connection:
    conn = db.connect(REAL_DB)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def tier2_payload() -> dict:
    with open(TIER2_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def bridge_payload() -> dict:
    with open(BRIDGE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def official_by_code(real_conn) -> dict[str, int]:
    return {
        r["code"]: r["official"]
        for r in real_conn.execute(
            """SELECT p.code, sd.official FROM positions p
               JOIN source_documents sd ON sd.id = p.source_document_id"""
        )
    }


def _flags(side: dict, official_by_code: dict[str, int]) -> set[int]:
    return {official_by_code[o["position"]] for o in side["occurrences"]}


# ---------------------------------------------------------------------------
# AC-B1: every candidate has one official=0 side and one official=1 side.
# ---------------------------------------------------------------------------


def test_ac_b1_every_candidate_straddles_the_official_boundary(bridge_payload, official_by_code):
    assert bridge_payload["bridge"] == "ntft"
    assert bridge_payload["candidate_count"] == len(bridge_payload["candidates"]) > 0
    for c in bridge_payload["candidates"]:
        fa, fb = _flags(c["a"], official_by_code), _flags(c["b"], official_by_code)
        assert (0 in fa and 1 in fb) or (0 in fb and 1 in fa), c["pair_key"]
        assert c["a"]["task_id"] < c["b"]["task_id"]
        assert c["score"] >= bridge_payload["threshold"]
        assert c["seed_reason"] is None  # no grounded seeds in the bridge


def test_ac_b1_side_filter_unit():
    sides = {1: {0}, 2: {1}, 3: {0, 1}, 4: {0}}
    assert match.is_bridge_pair(sides, 1, 2)
    assert match.is_bridge_pair(sides, 2, 1)
    assert match.is_bridge_pair(sides, 3, 1)  # shared task counts on either side
    assert match.is_bridge_pair(sides, 3, 2)
    assert not match.is_bridge_pair(sides, 1, 4)  # both NTFT
    assert not match.is_bridge_pair(sides, 2, 2)
    assert not match.is_bridge_pair(sides, 1, 99)  # unknown task has no side


def test_ac_b1_bridge_is_empty_on_all_nwcg_fixture_corpus(fixture_db_conn):
    # The 5 Phase-0 fixtures are all official=1, so the side filter must
    # admit nothing regardless of similarity.
    cands = match.generate_candidates(fixture_db_conn, bridge="ntft")
    assert cands == []


# ---------------------------------------------------------------------------
# AC-B2: no candidate duplicates a tier-2 pair_key; tier-2 artifact unchanged.
# ---------------------------------------------------------------------------


def test_ac_b2_no_pair_key_shared_with_tier2(bridge_payload, tier2_payload):
    tier2_keys = {c["pair_key"] for c in tier2_payload["candidates"]}
    bridge_keys = [c["pair_key"] for c in bridge_payload["candidates"]]
    assert len(bridge_keys) == len(set(bridge_keys))
    assert not tier2_keys & set(bridge_keys)


def test_ac_b2_pair_keys_match_normalized_texts(bridge_payload):
    for c in bridge_payload["candidates"]:
        assert c["pair_key"] == match.pair_key(c["a"]["normalized_text"], c["b"]["normalized_text"])


# ---------------------------------------------------------------------------
# AC-B3: every candidate adjudicated (with bridge tag); 0 confirmed without
# human review; every bridge probable row traces to a non-rejecting verdict.
# ---------------------------------------------------------------------------


def test_ac_b3_every_bridge_candidate_has_a_bridge_tagged_verdict(bridge_payload):
    adjudications = adjudicate.load_adjudications()
    for c in bridge_payload["candidates"]:
        v = adjudications.get(c["pair_key"])
        assert v is not None, f"bridge pair {c['pair_key']} not adjudicated"
        assert v.get("bridge") == "ntft", c["pair_key"]
        assert v["relation"] in adjudicate.VALID_VERDICT_RELATIONS
        assert v["note"]


def test_ac_b3_tier2_verdicts_carry_no_bridge_tag(tier2_payload):
    adjudications = adjudicate.load_adjudications()
    for c in tier2_payload["candidates"]:
        assert "bridge" not in adjudications[c["pair_key"]], c["pair_key"]


def test_ac_b3_bridge_rows_in_db_match_candidates_and_verdicts(real_conn, bridge_payload):
    adjudications = adjudicate.load_adjudications()
    rows = real_conn.execute(
        "SELECT * FROM task_equivalences WHERE method LIKE '%ntft-bridge%'"
    ).fetchall()
    assert len(rows) == len(bridge_payload["candidates"])
    by_ids = {(c["a"]["task_id"], c["b"]["task_id"]): c for c in bridge_payload["candidates"]}
    for r in rows:
        cand = by_ids[(r["task_a_id"], r["task_b_id"])]
        verdict = adjudications[cand["pair_key"]]
        assert r["similarity_score"] == cand["score"]
        assert r["adjudication_note"] == verdict["note"]
        if verdict["relation"] == "related_not_equivalent":
            assert (r["tier"], r["status"]) == (3, "rejected")
        else:
            assert r["tier"] == 2
            assert r["status"] in ("probable", "confirmed", "rejected")
        if r["status"] == "confirmed":
            assert r["human_reviewed_at"], "confirmed bridge row without human review"


def test_ac_b3_no_confirmed_bridge_row_without_human_review(real_conn):
    assert real_conn.execute(
        """SELECT COUNT(*) FROM task_equivalences
           WHERE method LIKE '%ntft-bridge%' AND status = 'confirmed'
             AND human_reviewed_at IS NULL"""
    ).fetchone()[0] == 0


# ---------------------------------------------------------------------------
# AC-B4: CFMD prerequisites resolve to FBAN and LTAN.
# ---------------------------------------------------------------------------


def test_ac_b4_cfmd_prerequisites_resolve(real_conn):
    values = {
        r["value"]
        for r in real_conn.execute(
            """SELECT pr.value FROM position_requirements pr
               JOIN positions p ON p.id = pr.position_id
               WHERE p.code = 'CFMD' AND pr.kind = 'prerequisite_position'"""
        )
    }
    assert values == {"FBAN", "LTAN"}
    codes = {r["code"] for r in real_conn.execute("SELECT code FROM positions")}
    assert values <= codes


def test_ac_b4_every_ntft_prerequisite_resolves_to_a_position(real_conn):
    unresolved = real_conn.execute(
        """SELECT p.code, pr.value FROM position_requirements pr
           JOIN positions p ON p.id = pr.position_id
           JOIN source_documents sd ON sd.id = p.source_document_id
           WHERE sd.official = 0 AND pr.kind = 'prerequisite_position'
             AND pr.value NOT IN (SELECT code FROM positions)"""
    ).fetchall()
    assert [tuple(r) for r in unresolved] == []


# ---------------------------------------------------------------------------
# AC-B7: default pipeline unchanged; bridge rows distinguishable by method.
# ---------------------------------------------------------------------------


def test_ac_b7_tier2_defaults_unchanged(tier2_payload):
    assert match.CANDIDATE_THRESHOLD == 0.80
    assert tier2_payload["threshold"] == 0.80
    assert "bridge" not in tier2_payload
    assert "ntft-bridge" not in match.method_string()


def test_ac_b7_bridge_threshold_and_method_string(bridge_payload):
    assert match.CANDIDATE_THRESHOLD_NTFT in (0.60, 0.65)
    assert bridge_payload["threshold"] == match.CANDIDATE_THRESHOLD_NTFT
    assert bridge_payload["model"] == match.MODEL_NAME
    assert bridge_payload["model_revision"] == match.MODEL_REVISION
    expected = f"ntft-bridge; cosine>={match.CANDIDATE_THRESHOLD_NTFT:.2f}"
    assert expected in match.method_string(bridge="ntft")


def test_ac_b7_db_rows_split_cleanly_between_layers(real_conn, tier2_payload, bridge_payload):
    total = real_conn.execute("SELECT COUNT(*) FROM task_equivalences").fetchone()[0]
    bridge = real_conn.execute(
        "SELECT COUNT(*) FROM task_equivalences WHERE method LIKE '%ntft-bridge%'"
    ).fetchone()[0]
    assert bridge == len(bridge_payload["candidates"])
    assert total - bridge == len(tier2_payload["candidates"])
    for r in real_conn.execute("SELECT method FROM task_equivalences WHERE method LIKE '%ntft-bridge%'"):
        assert re.search(r"ntft-bridge; cosine>=0\.6[05]", r["method"])
