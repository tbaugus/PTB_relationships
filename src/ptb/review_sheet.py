"""Non-technical reviewer workflow for the tier-2 human review (Phase 4).

The canonical review artifact is reports/tier2_review_checklist.md plus the
per-pair `py src/ptb/adjudicate.py promote` command. This module provides an
alternative for a NON-TECHNICAL reviewer (e.g. a subject-matter expert who
works in Google Sheets):

  py src/ptb/review_sheet.py export [--prefill <previously_filled.xlsx>]
      Writes reports/tier2_review_sheet.xlsx: an Instructions tab plus a
      Review tab with one row per status='probable' pair (highest similarity
      first) and two yellow columns the reviewer fills in. Context columns
      added 2026-07-12: Tier ("Check context first" marks pairs whose role
      context differs on independent axes), and each side's Bloom's level
      (from data/blooms.json). --prefill carries decisions/notes forward
      from an earlier filled sheet by Pair ID.

  py src/ptb/review_sheet.py ingest <downloaded.xlsx> [--reviewer NAME]
      Reads the filled sheet back (File -> Download -> Microsoft Excel in
      Google Sheets; any tab name works - columns are found by header),
      converts every Confirm/Reject decision into data/confirmations.json
      entries (the same store `promote` writes, keyed by pair text so it
      survives corpus changes), then re-applies everything to the database
      and regenerates both review artifacts. Rows left blank or marked
      "Not sure"/"Unsure"/"Unlikely" stay status='probable' and appear again
      on the next export ("Unlikely" candidates are handled in bulk by the
      context rule - see src/ptb/context.py). Re-ingesting a corrected sheet
      is safe: the newest decision for a pair wins.

Never hand-edit data/confirmations.json; this script and `promote` are the
two sanctioned writers (PLAN.md: don't hand-edit generated artifacts).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb import adjudicate, db, match  # noqa: E402
from ptb.blooms import LEVEL_NAMES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHEET_PATH = REPO_ROOT / "reports" / "tier2_review_sheet.xlsx"

RELATION_PLAIN = {
    "equivalent": "Same task",
    "a_subsumes_b": "Task A includes Task B",
    "b_subsumes_a": "Task B includes Task A",
}

DECISIONS = ["Confirm", "Reject", "Unlikely", "Not sure"]

HEADERS = [
    "#", "Pair ID (do not edit)", "Claude's call", "Task A",
    "Task A appears in", "Task B", "Task B appears in",
    "Similarity (0-1)", "Claude's reasoning", "Tier",
    "Bloom A", "Bloom B",
    "YOUR DECISION", "YOUR NOTES (optional)",
]
DECISION_COL = 13  # 1-based index of "YOUR DECISION"


def _occurrences_label(side: dict) -> str:
    return "; ".join(
        f"{o['position']} #{o['task_number']} ({o['title']}) - {o['category']}"
        for o in side["occurrences"]
    )


def _load_prior_decisions(prefill_path) -> dict:
    """pair_key -> (decision, note) from any previously filled sheet."""
    from openpyxl import load_workbook

    wb = load_workbook(prefill_path, data_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb[wb.sheetnames[0]]
    head = [str(c.value or "").lower() for c in ws[1]]

    def col(fragment, default):
        for i, h in enumerate(head):
            if fragment in h:
                return i
        return default

    ci_key, ci_dec, ci_note = col("pair id", 1), col("your decision", 9), col("your notes", 10)
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[ci_key]:
            continue
        pk = str(row[ci_key]).strip()
        dec = str(row[ci_dec]).strip() if len(row) > ci_dec and row[ci_dec] else ""
        note = str(row[ci_note]).strip() if len(row) > ci_note and row[ci_note] else ""
        if pk not in ("EXAMPLE", "") and "pair id" not in pk.lower() and dec:
            out[pk] = (dec, note)
    return out


def export(
    db_path: Path | str = db.DEFAULT_DB_PATH,
    candidates_path: Path = match.DEFAULT_CANDIDATES_PATH,
    out_path: Path = DEFAULT_SHEET_PATH,
    prefill_path: Path | str | None = None,
) -> dict:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    from ptb import context

    payload = adjudicate.load_candidates(candidates_path)
    by_ids = {(c["a"]["task_id"], c["b"]["task_id"]): c for c in payload["candidates"]}
    blooms = {o["normalized_text"]: o for o in json.load(
        open(REPO_ROOT / "data" / "blooms.json", encoding="utf-8"))["objectives"]}
    prior = _load_prior_decisions(prefill_path) if prefill_path else {}

    conn = db.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM task_equivalences WHERE status = 'probable'
               ORDER BY similarity_score DESC, task_a_id, task_b_id"""
        ).fetchall()
    finally:
        conn.close()

    wb = Workbook()
    arial = Font(name="Arial", size=10)
    bold = Font(name="Arial", size=10, bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    yellow = PatternFill("solid", fgColor="FFFF00")
    grey = PatternFill("solid", fgColor="EEEEEE")
    orange = PatternFill("solid", fgColor="FCE5CD")

    # ---- Instructions tab -------------------------------------------------
    ws = wb.active
    ws.title = "Instructions"
    lines = [
        ("What this is", bold),
        ("Wildland-fire position task books from different positions often ask for the same "
         "demonstrated work in slightly different words. A computer flagged pairs of task "
         "statements that look alike, and an AI assistant made a first call on each pair. "
         "Nothing counts until a person confirms it. That person is you.", arial),
        ("", arial),
        ("How to review (Review tab)", bold),
        ("Read Task A and Task B in each row, then fill in the two YELLOW columns only:", arial),
        ('  - "Confirm" = you agree with Claude\'s call in column C. For "Same task" rows, that '
         "means a firefighter who was signed off on one has genuinely demonstrated the other. "
         'For "Task A includes Task B" rows, it means someone who did the bigger task (A) '
         "deserves credit for the smaller one (B) - but NOT the other way around.", arial),
        ('  - "Reject" = the two are different requirements; never give credit across them.', arial),
        ('  - "Unlikely" = probably not a real match (your earlier category - treated like '
         '"Not sure" until finalized, and used to improve the automatic rules).', arial),
        ('  - "Not sure" (or leave blank) = skip it; the pair stays unconfirmed and can be '
         "reviewed later.", arial),
        ("", arial),
        ("The golden rule", bold),
        ("When in doubt, Reject or Not sure. A wrong Confirm could credit someone with work "
         "they have not done; a wrong Reject only makes someone demonstrate a task again.", arial),
        ("", arial),
        ("What changed since your first pass (2026-07-12)", bold),
        ("  - Your first 51 decisions are already filled in - no need to redo them.", arial),
        ("  - ~300 pairs matching your 'different context' pattern (same words filed under "
         "different behavior categories) were removed by an automatic rule built from your "
         "feedback, so this sheet is much shorter.", arial),
        ('  - New "Tier" column: rows marked "Check context first" (orange) have positions from '
         "different worlds (e.g. aviation vs ground crew) or very different thinking levels - "
         "read those with extra skepticism.", arial),
        ('  - New "Bloom A/B" columns show each task\'s thinking level (Remember, Understand, '
         "Apply, Analyze, Evaluate, Create). A big difference is a warning sign.", arial),
        ("", arial),
        ("Practical notes", bold),
        ("  - Rows are sorted easiest-first (most similar wording at the top).", arial),
        ("  - Row 2 of the Review tab is a worked EXAMPLE - leave it alone.", arial),
        ("  - Do not edit column B (Pair ID) - it is how your answers get matched back.", arial),
        ("  - Your notes column is optional but welcome, especially on Rejects.", arial),
    ]
    for i, (text, font) in enumerate(lines, start=1):
        cell = ws.cell(row=i, column=1, value=text)
        cell.font = font
        cell.alignment = wrap
    ws.column_dimensions["A"].width = 110

    # ---- Review tab -------------------------------------------------------
    ws = wb.create_sheet("Review")
    for col, header in enumerate(HEADERS, start=1):
        c = ws.cell(row=1, column=col, value=header)
        c.font = bold
        c.alignment = wrap
        if header.startswith("YOUR"):
            c.fill = yellow

    example = [
        "EX", "EXAMPLE", "Same task",
        "Gather critical information pertinent to the assignment.",
        "ENGB #4 (Engine Boss, Single Resource) - Prepare and Mobilize",
        "Gather information pertinent to the assignment.",
        "RXB2 #14 (Prescribed Fire Burn Boss Type 2) - Prepare and Mobilize",
        0.85, "Differs only by the word 'critical'; same duty.",
        "Standard", "Remember", "Remember",
        "Confirm", "clearly the same",
    ]
    for col, value in enumerate(example, start=1):
        c = ws.cell(row=2, column=col, value=value)
        c.font = arial
        c.alignment = wrap
        c.fill = grey

    prefilled = 0
    for i, r in enumerate(rows, start=1):
        cand = by_ids[(r["task_a_id"], r["task_b_id"])]
        feats = context.pair_features(cand, blooms)
        tier = "Check context first" if context.scrutiny_flag(feats) else "Standard"
        dec, note = prior.get(cand["pair_key"], (None, None))
        if dec:
            prefilled += 1
        values = [
            i, cand["pair_key"], RELATION_PLAIN[r["relation"]],
            cand["a"]["canonical_text"], _occurrences_label(cand["a"]),
            cand["b"]["canonical_text"], _occurrences_label(cand["b"]),
            round(r["similarity_score"], 3), r["adjudication_note"],
            tier,
            LEVEL_NAMES.get(feats["bloom_a"]), LEVEL_NAMES.get(feats["bloom_b"]),
            dec, note or None,
        ]
        for col, value in enumerate(values, start=1):
            c = ws.cell(row=i + 2, column=col, value=value)
            c.font = arial
            c.alignment = wrap
            if col >= DECISION_COL:
                c.fill = yellow
            elif col == 10 and tier != "Standard":
                c.fill = orange

    dv = DataValidation(type="list", formula1='"' + ",".join(DECISIONS) + '"', allow_blank=True)
    dv.error = "Please choose Confirm, Reject, Unlikely, or Not sure."
    dv.errorTitle = "Invalid decision"
    ws.add_data_validation(dv)
    dv.add(f"M3:M{len(rows) + 2}")

    widths = [5, 18, 20, 45, 40, 45, 40, 10, 50, 16, 11, 11, 14, 30]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = "A3"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return {"probable_pairs": len(rows), "prefilled_decisions": prefilled, "sheet": str(out_path)}


def ingest(
    sheet_path: Path | str,
    reviewer: str = "SME",
    db_path: Path | str = db.DEFAULT_DB_PATH,
    candidates_path: Path = match.DEFAULT_CANDIDATES_PATH,
    confirmations_path: Path = adjudicate.CONFIRMATIONS_PATH,
    **apply_kwargs,
) -> dict:
    from openpyxl import load_workbook

    payload = adjudicate.load_candidates(candidates_path)
    known_keys = {c["pair_key"] for c in payload["candidates"]}
    adjudications = adjudicate.load_adjudications()

    wb = load_workbook(sheet_path, data_only=True)
    ws = wb["Review"] if "Review" in wb.sheetnames else wb[wb.sheetnames[0]]
    head = [str(c.value or "").lower() for c in ws[1]]

    def _col(fragment, default):
        for i, h in enumerate(head):
            if fragment in h:
                return i
        return default

    ci_key = _col("pair id", 1)
    ci_dec = _col("your decision", DECISION_COL - 1)
    ci_note = _col("your notes", DECISION_COL)

    decisions, skipped, problems = [], 0, []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None or all(v is None for v in row):
            continue
        pair_key = str(row[ci_key]).strip() if row[ci_key] else ""
        decision = (str(row[ci_dec]).strip() if len(row) > ci_dec and row[ci_dec] else "").lower()
        note = str(row[ci_note]).strip() if len(row) > ci_note and row[ci_note] else None
        if pair_key in ("EXAMPLE", "") or "pair id" in pair_key.lower():
            continue
        if decision in ("", "not sure", "unsure", "unlikely"):
            skipped += 1
            continue
        if decision not in ("confirm", "reject"):
            problems.append(f"row with Pair ID {pair_key}: unrecognized decision {decision!r}")
            continue
        if pair_key not in known_keys:
            problems.append(f"unknown Pair ID {pair_key} (column B must not be edited)")
            continue
        if adjudications.get(pair_key, {}).get("relation") == "related_not_equivalent":
            # Already rejected in bulk (e.g. by the context rule); her Confirm
            # on such a row would be a real conflict worth surfacing.
            if decision == "confirm":
                problems.append(f"Pair ID {pair_key}: sheet says Confirm but the pair was "
                                f"rule-rejected - resolve manually in data/adjudications.json")
            else:
                skipped += 1
            continue
        decisions.append(
            {
                "pair_key": pair_key,
                "decision": decision,
                "human_reviewed_at": date.today().isoformat(),
                "reviewer": reviewer,
                **({"note": note} if note else {}),
            }
        )

    if problems:
        raise ValueError("Sheet problems - nothing ingested:\n  " + "\n  ".join(problems))

    if confirmations_path.exists():
        data = json.load(open(confirmations_path, encoding="utf-8"))
    else:
        data = {"confirmations": []}
    data["confirmations"].extend(decisions)  # newest entry for a pair wins on load
    confirmations_path.parent.mkdir(parents=True, exist_ok=True)
    with open(confirmations_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")

    stats = adjudicate.apply(
        db_path=db_path,
        candidates_path=candidates_path,
        confirmations_path=confirmations_path,
        **apply_kwargs,
    )
    return {
        "ingested_confirm": sum(1 for d in decisions if d["decision"] == "confirm"),
        "ingested_reject": sum(1 for d in decisions if d["decision"] == "reject"),
        "left_for_later": skipped,
        **stats,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export/ingest the SME review spreadsheet.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_ex = sub.add_parser("export", help="write reports/tier2_review_sheet.xlsx")
    p_ex.add_argument("--prefill", default=None,
                      help="previously filled sheet whose decisions/notes carry over")
    p_in = sub.add_parser("ingest", help="read a filled sheet and apply decisions")
    p_in.add_argument("sheet", help="path to the filled .xlsx downloaded from Google Sheets")
    p_in.add_argument("--reviewer", default="SME")
    args = parser.parse_args()
    if args.command == "export":
        print(json.dumps(export(prefill_path=args.prefill), indent=2))
    else:
        print(json.dumps(ingest(args.sheet, reviewer=args.reviewer), indent=2))
