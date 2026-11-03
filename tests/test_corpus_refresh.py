"""Corpus-refresh acceptance tests (2026-11-02):

- specs/acquisition.spec.md AC-A11 / AC-A12 — manifest currency fields and
  explicit retirement (offline: reads the committed corpus/manifest.json;
  AC-A10's live URL check is `py src/ptb/acquire.py --verify-urls`, run by
  the spec-checker, not here — tests never touch the network).
- specs/schema.spec.md changelog 2026-11-02 — every source_documents row
  carries an ISO-8601 edition_date.
- specs/gap-analysis.spec.md AC-G9 — the "Data as of:" line.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ptb import db, gap  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"
EXTRACTED_DIR = REPO_ROOT / "extracted"
ISO_MONTH_OR_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# --- AC-A12: edition_date / edition_date_source on every NWCG document ------


def test_ac_a12_every_nwcg_document_has_iso_edition_date(manifest: dict) -> None:
    for d in manifest["documents"]:
        if d.get("role") not in ("ptb", "companion_standards"):
            continue
        assert ISO_MONTH_OR_DATE.match(d.get("edition_date") or ""), f"{d['filename']}: edition_date={d.get('edition_date')!r}"
        assert d.get("edition_date_source") and d["edition_date_source"] != "none", d["filename"]


def test_ac_a12_catalog_date_matches_printed_month_or_conflict_recorded(manifest: dict) -> None:
    """The catalog's Date Published must agree with the month printed on the
    PDF's page 1, or the entry must record the disagreement explicitly with
    the printed value chosen — never a silent preference."""
    checked, conflicts = 0, set()
    for d in manifest["documents"]:
        printed = d.get("edition_date_printed")
        if d.get("role") != "ptb" or not printed or d["filename"].startswith("enhanced_"):
            continue
        printed_iso = db.printed_edition_to_iso(printed)
        if d.get("edition_date_conflict"):
            assert d["edition_date"] == printed_iso, f"{d['filename']}: conflict recorded but printed value not chosen"
            assert set(d["edition_date_conflict"]) == {"catalog", "printed"}
            conflicts.add(d["filename"])
        else:
            assert d["edition_date_source"] == "catalog Date Published", d["filename"]
            assert printed_iso == d["edition_date"], f"{d['filename']}: catalog {d['edition_date']} vs printed {printed!r}"
        checked += 1
    assert checked > 0
    # The two disagreements NWCG published as of 2026-11-02; a new one must be
    # noticed (and added to acquisition.spec.md's changelog), not absorbed.
    assert conflicts == {"pms311-51_EQTR.pdf", "pms311-107_FELB.pdf"}, conflicts


def test_requirement_pages_record_no_edition_date_explicitly(manifest: dict) -> None:
    pages = [d for d in manifest["documents"] if d.get("role") == "qualification_standard" and d["filename"].startswith("requirements/")]
    assert pages, "no qualification-requirement pages in the manifest"
    for d in pages:
        assert d.get("edition_date") is None and d.get("edition_date_source") == "none", d["filename"]


# --- AC-A11: retirement is explicit --------------------------------------------


def test_ac_a11_retired_entries_are_explicit_and_gone(manifest: dict) -> None:
    retired = manifest.get("retired", [])
    assert retired, "the 2026-11-02 refresh retired the combined FEMO-FOBS legacy book; retired[] must not be empty"
    live = {d["filename"] for d in manifest["documents"]}
    for r in retired:
        assert r["reason"] and isinstance(r["superseded_by"], list), r["filename"]
        assert r["filename"] not in live
        assert not (EXTRACTED_DIR / f"{r['filename']}.json").exists(), f"stale extracted JSON for retired {r['filename']}"
        raw = db.CORPUS_RAW_DIR / r["filename"]
        assert not raw.exists(), f"retired raw file still present: {raw}"
        for successor in r["superseded_by"]:
            assert successor in live, f"{r['filename']} names successor {successor} that is not a live document"


def test_ac_a11_femo_fobs_split_recorded(manifest: dict) -> None:
    by_name = {r["filename"]: r for r in manifest.get("retired", [])}
    old = by_name["pms311-30_FEMO-FOBS.pdf"]
    assert set(old["superseded_by"]) == {"pms311-30_FOBS.pdf", "pms311-71_FEMO.pdf"}
    live = {d["filename"]: d for d in manifest["documents"]}
    assert live["pms311-30_FOBS.pdf"]["position_codes"] == ["FOBS"]
    assert live["pms311-71_FEMO.pdf"]["position_codes"] == ["FEMO"]
    assert live["pms311-112_REAF.pdf"]["position_codes"] == ["REAF"]


def test_revised_documents_keep_prior_edition_in_superseded(manifest: dict) -> None:
    """A republished book keeps its previous hash/date under `superseded` so
    the revision is detectable from the manifest alone (acquisition rules)."""
    live = {d["filename"]: d for d in manifest["documents"]}
    for name in ("pms311-16_STAM.pdf", "pms311-12_CREP.pdf", "pms311-91_FAL2.pdf"):
        prior = live[name].get("superseded")
        assert prior, f"{name}: expected a superseded entry from the 2026-11-02 refresh"
        assert prior[-1]["sha256"] != live[name]["sha256"]
        assert "downloaded_at" in prior[-1]


# --- schema.spec.md 2026-11-02: ISO edition_date on every source_documents row


def test_every_source_document_has_iso_edition_date(full_db_conn) -> None:
    rows = full_db_conn.execute("SELECT filename, edition_date FROM source_documents").fetchall()
    assert len(rows) > 0
    for row in rows:
        assert row["edition_date"] and ISO_MONTH_OR_DATE.match(row["edition_date"]), (
            f"{row['filename']}: edition_date={row['edition_date']!r}"
        )


def test_refreshed_editions_loaded(full_db_conn) -> None:
    got = {
        r["filename"]: r["edition_date"]
        for r in full_db_conn.execute(
            "SELECT filename, edition_date FROM source_documents WHERE filename IN "
            "('pms311-16_STAM.pdf','pms311-30_FOBS.pdf','pms311-71_FEMO.pdf','pms311-112_REAF.pdf','pms311-20_HEBM.pdf')"
        )
    }
    assert got == {
        "pms311-16_STAM.pdf": "2026-09",
        "pms311-30_FOBS.pdf": "2026-09",
        "pms311-71_FEMO.pdf": "2026-09",
        "pms311-112_REAF.pdf": "2025-07",
        "pms311-20_HEBM.pdf": "2018-10",  # mixed-case printed month, previously null
    }
    assert full_db_conn.execute("SELECT COUNT(*) FROM positions WHERE code = 'REAF'").fetchone()[0] == 1
    assert full_db_conn.execute("SELECT COUNT(*) FROM source_documents WHERE filename LIKE '%FEMO-FOBS%'").fetchone()[0] == 0


def test_printed_edition_to_iso() -> None:
    assert db.printed_edition_to_iso("SEPTEMBER 2026") == "2026-09"
    assert db.printed_edition_to_iso("October 2018") == "2018-10"
    assert db.printed_edition_to_iso(None) is None
    assert db.printed_edition_to_iso("Sometime 2020") is None


# --- AC-G9: "Data as of:" line --------------------------------------------------


def test_ac_g9_data_as_of_line_in_text_report(full_db_conn) -> None:
    currency = gap.data_currency(full_db_conn)
    assert currency.nwcg_edition_max == "2026-09"
    assert currency.downloaded_at and ISO_MONTH_OR_DATE.match(currency.downloaded_at)
    assert currency.ntft_edition, "the NTFT draft's DOCX modified date must be surfaced"
    profile = gap.CandidateProfile(held_qualifications=["ENGB"], completed_courses=[], completed_task_ids=[])
    results = gap.closest_positions(profile, limit=3, conn=full_db_conn)
    text = gap.format_report(profile, results, limit=3, currency=currency)
    lines = text.splitlines()
    assert lines[0] == gap.DISCLAIMER
    assert lines[1].startswith("Data as of: ")
    assert "2026-09" in lines[1] and currency.downloaded_at in lines[1]
    assert "you are qualified" not in text
