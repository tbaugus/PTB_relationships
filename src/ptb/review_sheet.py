"""Non-technical reviewer workflow for the tier-2 human review (Phase 4).

The canonical review artifact is reports/tier2_review_checklist.md plus the
per-pair `py src/ptb/adjudicate.py promote` command. This module provides an
alternative for a NON-TECHNICAL reviewer (e.g. a subject-matter expert who
works in Google Sheets):

  py src/ptb/review_sheet.py export
      Writes reports/tier2_review_sheet.xlsx: an Instructions tab plus a
      Review tab with one row per status='probable' pair (same population as
      the Markdown checklist, highest similarity first) and two yellow
      columns the reviewer fills in ("YOUR DECISION" dropdown + notes).
      Upload the file to Google Sheets, share it, and let them work.

  py src/ptb/review_sheet.py ingest <downloaded.xlsx> [--reviewer NAME]
      Reads the filled sheet back (File -> Download -> Microsoft Excel in
      Google Sheets), converts every Confirm/Reject decision into
      data/confirmations.json entries (the same store `promote` writes,
      keyed by pair text so it survives corpus changes), then re-applies
      everything to the database and regenerates both review artifacts.
      Rows left blank or marked "Not sure" stay status='probable' and simply
      appear again on the next export. Re-ingesting a corrected sheet is
      safe: the newest decision for a pair wins.

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

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHEET_PATH = REPO_ROOT / "reports" / "tier2_review_sheet.xlsx"

RELATION_PLAIN = {
    "equivalent": "Same task",
    "a_subsumes_b": "Task A includes Task B",
    "b_subsumes_a": "Task B includes Task A",
}

DECISIONS = ["Confirm", "Reject", "Not sure"]

HEADERS = [
    "#", "Pair ID (do not edit)", "Claude's call", "Task A",
    "Task A appears in", "Task B", "Task B appears in",
    "Similarity (0-1)", "Claude's reasoning",
    "YOUR DECISION", "YOUR NOTES (optional)",
]
DECISION_COL = 10  # 1-based index of "YOUR DECISION"


def _occurrences_label(side: dict) -> str:
    return "; ".join(
        f"{o['position']} #{o['task_number']} ({o['title']}) - {o['category']}"
        for o in side["occurrences"]
    )


def export(
    db_path: Path | str = db.DEFAULT_DB_PATH,
    candidates_path: Path = match.DEFAULT_CANDIDATES_PATH,
    out_path: Path = DEFAULT_SHEET_PATH,
) -> dict:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    payload = adjudicate.load_candidates(candidates_path)
    by_ids = {(c["a"]["task_id"], c["b"]["task_id"]): c for c in payload["candidates"]}

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
        ('  - "Not sure" (or leave blank) = skip it; the pair stays unconfirmed and can be '
         "reviewed later.", arial),
        ("", arial),
        ("The golden rule", bold),
        ("When in doubt, Reject or Not sure. A wrong Confirm could credit someone with work "
         "they have not done; a wrong Reject only makes someone demonstrate a task again.", arial),
        ("", arial),
        ("Practical notes", bold),
        ("  - Rows are sorted easiest-first (most similar wording at the top).", arial),
        ("  - Row 2 of the Review tab is a worked EXAMPLE - leave it alone.", arial),
        ('  - "Appears in" shows every position and task number that uses each wording, with '
         "the section of the task book it sits in.", arial),
        ("  - Similarity is the computer's wording-closeness score (1.00 = nearly identical).", arial),
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
        c.font = Font(name="Arial", size=10, bold=True)
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
        "Confirm", "clearly the same",
    ]
    for col, value in enumerate(example, start=1):
        c = ws.cell(row=2, column=col, value=value)
        c.font = arial
        c.alignment = wrap
        c.fill = grey

    for i, r in enumerate(rows, start=1):
        cand = by_ids[(r["task_a_id"], r["task_b_id"])]
        values = [
            i, cand["pair_key"], RELATION_PLAIN[r["relation"]],
            cand["a"]["canonical_text"], _occurrences_label(cand["a"]),
            cand["b"]["canonical_text"], _occurrences_label(cand["b"]),
            round(r["similarity_score"], 3), r["adjudication_note"],
            None, None,
        ]
        for col, value in enumerate(values, start=1):
            c = ws.cell(row=i + 2, column=col, value=value)
            c.font = arial
            c.alignment = wrap
            if col >= DECISION_COL:
                c.fill = yellow

    dv = DataValidation(type="list", formula1='"' + ",".join(DECISIONS) + '"', allow_blank=True)
    dv.error = "Please choose Confirm, Reject, or Not sure."
    dv.errorTitle = "Invalid decision"
    ws.add_data_validation(dv)
    dv.add(f"J3:J{len(rows) + 2}")

    widths = [5, 18, 20, 45, 40, 45, 40, 10, 50, 14, 30]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = "A3"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return {"probable_pairs": len(rows), "sheet": str(out_path)}


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
    if "Review" not in wb.sheetnames:
        raise ValueError(f"{sheet_path} has no 'Review' tab - is this the right file?")
    ws = wb["Review"]

    decisions, skipped, problems = [], 0, []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None or all(v is None for v in row):
            continue
        pair_key = str(row[1]).strip() if row[1] else ""
        decision = str(row[DECISION_COL - 1]).strip() if row[DECISION_COL - 1] else ""
        note = str(row[DECISION_COL]).strip() if row[DECISION_COL] else None
        if pair_key in ("EXAMPLE", ""):
            continue
        if decision in ("", "Not sure"):
            skipped += 1
            continue
        if decision not in ("Confirm", "Reject"):
            problems.append(f"row with Pair ID {pair_key}: unrecognized decision {decision!r}")
            continue
        if pair_key not in known_keys:
            problems.append(f"unknown Pair ID {pair_key} (column B must not be edited)")
            continue
        if adjudications.get(pair_key, {}).get("relation") == "related_not_equivalent":
            problems.append(f"Pair ID {pair_key} is not a reviewable (probable) pair")
            continue
        decisions.append(
            {
                "pair_key": pair_key,
                "decision": "confirm" if decision == "Confirm" else "reject",
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
    sub.add_parser("export", help="write reports/tier2_review_sheet.xlsx")
    p_in = sub.add_parser("ingest", help="read a filled sheet and apply decisions")
    p_in.add_argument("sheet", help="path to the filled .xlsx downloaded from Google Sheets")
    p_in.add_argument("--reviewer", default="SME")
    args = parser.parse_args()
    if args.command == "export":
        print(json.dumps(export(), indent=2))
    else:
        print(json.dumps(ingest(args.sheet, reviewer=args.reviewer), indent=2))
