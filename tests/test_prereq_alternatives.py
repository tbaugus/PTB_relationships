"""Prerequisite alternative groups (schema.spec.md / gap-analysis.spec.md,
2026-11-04): CFMD's source anchor "FBAN / LTAN" means either, not both."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import db, gap  # noqa: E402
from ptb.structure.enhanced import parse_attaches_to  # noqa: E402


@pytest.fixture(scope="module")
def real_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db.DEFAULT_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _cfmd(results):
    return next(pg for pg in results if pg.position == "CFMD")


# --- parser --------------------------------------------------------------------

def test_parse_attaches_to_distinguishes_plus_from_slash():
    assert parse_attaches_to("Attaches to: UASP + FIRB") == (["UASP", "FIRB"], [])
    assert parse_attaches_to("Attaches to: FBAN / LTAN") == (["FBAN", "LTAN"], [["FBAN", "LTAN"]])
    assert parse_attaches_to("Attaches to: GISS") == (["GISS"], [])


def test_source_json_records_the_cfmd_group():
    doc = json.load(open(REPO_ROOT / "extracted" / "enhanced_ptbs_gdoc.docx.json", encoding="utf-8"))
    by_code = {p["code"]: p for p in doc["positions"]}
    assert by_code["CFMD"]["attaches_to"] == ["FBAN", "LTAN"]
    assert by_code["CFMD"]["attaches_to_alternatives"] == [["FBAN", "LTAN"]]
    assert all(not p.get("attaches_to_alternatives") for c, p in by_code.items() if c != "CFMD")


# --- schema / loader -----------------------------------------------------------

def test_alt_group_column_and_cfmd_group(real_conn):
    cols = {r["name"] for r in real_conn.execute("PRAGMA table_info(position_requirements)")}
    assert "alt_group" in cols
    rows = real_conn.execute(
        """SELECT pr.value, pr.alt_group FROM position_requirements pr
           JOIN positions p ON p.id = pr.position_id
           WHERE p.code = 'CFMD' AND pr.kind = 'prerequisite_position' ORDER BY pr.value"""
    ).fetchall()
    assert [(r["value"], r["alt_group"]) for r in rows] == [("FBAN", 1), ("LTAN", 1)]
    others = real_conn.execute(
        """SELECT COUNT(*) FROM position_requirements pr JOIN positions p ON p.id = pr.position_id
           WHERE pr.alt_group IS NOT NULL AND p.code <> 'CFMD'"""
    ).fetchone()[0]
    assert others == 0


# --- gap semantics -------------------------------------------------------------

def test_cfmd_with_neither_anchor_shows_one_either_or_gap(real_conn):
    results = gap.closest_positions(gap.CandidateProfile(), conn=real_conn)
    prereqs = [r for r in _cfmd(results).gaps_requirements if r.kind == "prerequisite_position"]
    assert len(prereqs) == 1
    assert prereqs[0].value == "FBAN / LTAN"
    assert prereqs[0].alternatives == ["FBAN", "LTAN"]
    # F1 pathway compatibility: the value splits on "/" into the member codes.
    assert [a.strip() for a in prereqs[0].value.split("/")] == prereqs[0].alternatives


@pytest.mark.parametrize("held", ["FBAN", "LTAN"])
def test_cfmd_with_either_anchor_has_no_prerequisite_gap(real_conn, held):
    results = gap.closest_positions(gap.CandidateProfile(held_qualifications=[held]), conn=real_conn)
    cfmd = _cfmd(results)
    assert not any(r.kind == "prerequisite_position" for r in cfmd.gaps_requirements)
    sat = [r for r in cfmd.satisfied_requirements if r.kind == "prerequisite_position"]
    assert [(r.value, r.derivation) for r in sat] == [(held, "direct")]


def test_ordinary_requirements_have_empty_alternatives(real_conn):
    results = gap.closest_positions(gap.CandidateProfile(), conn=real_conn)
    for pg in results:
        for r in pg.gaps_requirements:
            if pg.position != "CFMD" or r.kind != "prerequisite_position":
                assert r.alternatives == []


def test_alternative_group_adds_no_prerequisite_chain_edges(real_conn):
    ctx = gap._build_context(real_conn)
    cfmd_id = ctx.code_to_id["CFMD"]
    assert ctx.code_to_id["FBAN"] not in ctx.prereq_edges.get(cfmd_id, set())
    assert ctx.code_to_id["LTAN"] not in ctx.prereq_edges.get(cfmd_id, set())


def test_text_report_counts_the_group_once(real_conn):
    results = gap.closest_positions(gap.CandidateProfile(), conn=real_conn)
    text = gap.format_report(gap.CandidateProfile(), results, limit=len(results))
    cfmd_line = next(line for line in text.splitlines() if "requirement(s) remaining (FBAN / LTAN)" in line)
    assert "1 requirement(s) remaining" in cfmd_line
