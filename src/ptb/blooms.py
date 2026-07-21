"""Bloom's Taxonomy assignment for every distinct corpus objective.

Assigns each of the corpus's distinct tasks (tasks.normalized_text) a Bloom's
cognitive level 1-6 (Remember, Understand, Apply, Analyze, Evaluate, Create)
with a confidence score. Requested 2026-07-12 for use in (a) SME review
support and (b) the pair-narrowing context rule.

Method — "best judgment, codified": rather than eyeballing 2,503 texts
inconsistently, the judgment is written down as an explicit action-verb ->
level mapping (VERB_TABLE), phrase-level overrides for known ambiguous
constructions (PHRASE_RULES), and hand-written per-text overrides for texts
that defy verb analysis (HAND_OVERRIDES). Compound objectives ("develop,
implement, and adjust ...") receive the HIGHEST level among their verbs —
the standard convention for multi-verb learning objectives — with confidence
reduced the wider the verbs span. Any assignment with confidence < 0.70
carries a written justification (the user's requested threshold).

Outputs:
  py src/ptb/blooms.py            -> data/blooms.json  (machine-readable)
                                     reports/blooms_assignment.xlsx (review)

Keyed by normalized_text, so assignments survive database rebuilds exactly
like the adjudication verdicts do.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb import db  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BLOOMS_JSON = REPO_ROOT / "data" / "blooms.json"
BLOOMS_XLSX = REPO_ROOT / "reports" / "blooms_assignment.xlsx"

LEVEL_NAMES = {1: "Remember", 2: "Understand", 3: "Apply", 4: "Analyze", 5: "Evaluate", 6: "Create"}

# ---------------------------------------------------------------------------
# The judgment, codified. (level, confidence). Confidence < 0.70 marks verbs
# whose Bloom placement is genuinely contestable in an operational corpus;
# they always produce a written justification.
# ---------------------------------------------------------------------------
VERB_TABLE: dict[str, tuple[int, float]] = {
    # Remember — acquire/retain information
    "obtain": (1, 0.75), "gather": (1, 0.80), "collect": (1, 0.80), "receive": (1, 0.80),
    # Understand — grasp/known meaning
    "understand": (2, 0.85), "describe": (2, 0.85), "explain": (2, 0.85),
    "interpret": (2, 0.65), "recognize": (4, 0.65),  # recognizing hazards/deviations is diagnostic
    # Apply — execute procedures / perform the work
    "apply": (3, 0.90), "use": (3, 0.90), "utilize": (3, 0.90), "implement": (3, 0.85),
    "perform": (3, 0.90), "conduct": (3, 0.85), "complete": (3, 0.85), "execute": (3, 0.90),
    "operate": (3, 0.90), "maintain": (3, 0.80), "provide": (3, 0.80), "communicate": (3, 0.85),
    "coordinate": (3, 0.68), "participate": (3, 0.90), "attend": (3, 0.90), "travel": (3, 0.95),
    "arrive": (3, 0.95), "submit": (3, 0.90), "return": (3, 0.90), "distribute": (3, 0.85),
    "post": (3, 0.90), "brief": (3, 0.75), "inform": (3, 0.85), "notify": (3, 0.85),
    "exchange": (3, 0.85), "demobilize": (3, 0.90), "mobilize": (3, 0.90), "order": (3, 0.75),
    "request": (3, 0.85), "install": (3, 0.90), "respond": (3, 0.70), "act": (3, 0.70),
    "serve": (3, 0.80), "assist": (3, 0.70), "support": (3, 0.70), "enter": (3, 0.85),
    "file": (3, 0.85), "record": (3, 0.85), "document": (3, 0.80), "initiate": (3, 0.75),
    "follow": (3, 0.85), "comply": (3, 0.80), "wear": (3, 0.95), "share": (3, 0.85),
    "update": (3, 0.80), "relay": (3, 0.85), "transfer": (3, 0.80), "assign": (3, 0.68),
    "assemble": (3, 0.80), "check": (3, 0.85), "work": (3, 0.60), "keep": (3, 0.70),
    "give": (3, 0.85), "present": (3, 0.75), "deliver": (3, 0.80), "report": (3, 0.80),
    "demonstrate": (3, 0.68),  # skill demonstration unless "knowledge/understanding" (phrase rule)
    # Analyze — break down, diagnose, interpret situations
    "analyze": (4, 0.90), "assess": (4, 0.85), "monitor": (4, 0.75), "determine": (4, 0.80),
    "identify": (4, 0.75), "examine": (4, 0.90), "investigate": (4, 0.85),
    "distinguish": (4, 0.90), "calculate": (4, 0.90), "estimate": (4, 0.75),
    "anticipate": (4, 0.70), "track": (4, 0.70), "scout": (4, 0.70), "observe": (4, 0.70),
    "research": (4, 0.85), "compare": (4, 0.90), "reconcile": (4, 0.75), "consider": (4, 0.65),
    # Evaluate — judge against standards, oversee quality
    "evaluate": (5, 0.90), "validate": (5, 0.90), "verify": (5, 0.90), "ensure": (5, 0.75),
    "approve": (5, 0.90), "audit": (5, 0.90), "prioritize": (5, 0.85), "recommend": (5, 0.80),
    "adjust": (5, 0.68), "modify": (5, 0.68), "confirm": (5, 0.85), "select": (5, 0.70),
    "decide": (5, 0.85), "resolve": (5, 0.70), "inspect": (5, 0.70), "test": (5, 0.65),
    "debrief": (5, 0.65), "critique": (5, 0.90), "reevaluate": (5, 0.90),
    "supervise": (5, 0.65), "direct": (5, 0.60), "lead": (5, 0.62), "manage": (5, 0.65),
    "oversee": (5, 0.65), "facilitate": (5, 0.65), "delegate": (5, 0.70), "review": (5, 0.60),
    # Create — produce new plans/products/structures
    "develop": (6, 0.90), "create": (6, 0.90), "design": (6, 0.90), "formulate": (6, 0.90),
    "produce": (6, 0.85), "compile": (6, 0.70), "construct": (6, 0.85), "write": (6, 0.85),
    "generate": (6, 0.85), "establish": (6, 0.65), "organize": (6, 0.65), "build": (6, 0.85),
    "integrate": (6, 0.75), "draft": (6, 0.90), "prepare": (6, 0.68), "plan": (6, 0.75),
    "set": (6, 0.60), "schedule": (6, 0.70),
    # second-pass additions (verbs surfaced by the first full-corpus run)
    "discuss": (2, 0.75), "know": (2, 0.80), "take": (3, 0.65), "contact": (3, 0.85),
    "consult": (3, 0.70), "exhibit": (3, 0.60), "engage": (3, 0.70), "adhere": (3, 0.85),
    "issue": (3, 0.85), "represent": (3, 0.70), "recon": (4, 0.80), "administer": (3, 0.75),
    "finalize": (3, 0.75), "arrange": (3, 0.80), "supply": (3, 0.85), "archive": (3, 0.85),
    "conclude": (3, 0.75), "incorporate": (3, 0.65), "emphasize": (3, 0.65),
    "collaborate": (3, 0.75), "ingest": (3, 0.75), "stop": (3, 0.75), "exercise": (3, 0.60),
    "train": (3, 0.65), "solicit": (1, 0.65), "survey": (4, 0.75), "deconflict": (4, 0.70),
    "discriminate": (4, 0.90), "corroborate": (4, 0.85), "advise": (5, 0.75),
    "assure": (5, 0.75), "authorize": (5, 0.80), "declare": (5, 0.65), "correct": (5, 0.70),
    "align": (5, 0.65), "mentor": (5, 0.60), "make": (3, 0.60),
    # third-pass additions
    "mitigate": (3, 0.75), "start": (3, 0.85), "handle": (3, 0.85), "mange": (5, 0.65),
    "revise": (5, 0.65), "process": (3, 0.85), "locate": (4, 0.70), "disseminate": (3, 0.85),
    "minimize": (3, 0.65), "vocalize": (3, 0.85), "orient": (2, 0.65), "upload": (3, 0.90),
    "place": (3, 0.80), "welcome": (3, 0.85), "control": (5, 0.60), "dispose": (3, 0.85),
    "adapt": (5, 0.68), "reinforce": (5, 0.65), "consolidate": (6, 0.65),
    "familiarize": (2, 0.85), "address": (4, 0.60), "state": (2, 0.70), "dispatch": (3, 0.85),
    "convert": (5, 0.62), "terminate": (5, 0.65), "protect": (3, 0.70), "allocate": (5, 0.75),
    "secure": (3, 0.70), "have": (3, 0.60), "pack": (3, 0.90), "populate": (3, 0.85),
    "copy": (3, 0.90), "configure": (3, 0.85), "add": (3, 0.85), "store": (3, 0.90),
    "sync": (3, 0.90), "back": (3, 0.90), "backup": (3, 0.90), "save": (3, 0.90),
    "name": (3, 0.85), "download": (3, 0.90), "gauge": (4, 0.75), "articulate": (3, 0.80),
    "clone": (3, 0.90), "program": (3, 0.85), "display": (3, 0.70),
}

# Leading adverbs/fillers to skip when finding a clause's action verb.
_SKIP_LEADS = {
    "continually", "continuously", "accurately", "actively", "promptly", "properly",
    "safely", "clearly", "immediately", "regularly", "proactively", "effectively",
    "then", "also", "when", "as", "if", "the", "a", "an", "and", "always",
    "given", "successfully", "periodically", "fully",
}

# Verb-free noun headings (legacy/print-format artifacts). Read as performing
# the named function; low confidence because the action verb is absent.
_NOUN_HEADING_JUST = ("Noun-phrase heading with no printed action verb (print-format artifact); "
                      "read as performing the named function, but without a verb the Bloom level "
                      "is a judgment call.")
NOUN_HEADINGS: dict[str, int] = {
    "daily duties": 3, "ramp operations": 3, "hand signals": 3, "wing-walking": 3,
    "radio use": 3, "timekeeping operations": 3, "decision making": 5,
    "incident compliance inspection of national/regional agreement / contract resources:": 5,
    "non-compliance, poor or unsatisfactory performance of contracted resource with agreement": 5,
    "demobilization of contracted resources with agreements": 3,
}

# Phrase-level overrides, checked before verb extraction. (regex, level, conf,
# justification-or-None). First match wins for the clause it anchors.
PHRASE_RULES: list[tuple[str, int, float, str | None]] = [
    (r"demonstrates? (a |the )?(comprehensive |proper |working |thorough )?(knowledge|understanding|familiarity)",
     2, 0.85, None),
    (r"flight follow", 4, 0.75, None),
    (r"demonstrates? familiarity", 2, 0.85, None),
    (r"\bsize.?up\b", 4, 0.80, None),
    (r"\bcheck.?in\b", 3, 0.90, None),
    (r"hold (staff|.{0,30}) ?accountable", 5, 0.85, None),
    (r"set priorit", 5, 0.80, None),
    (r"\bprepare for\b", 3, 0.75, None),
    (r"review .{0,60}(for completeness|to ensure|compliance|prior to implementation)", 5, 0.78, None),
    (r"review .{0,80}and obtain (briefing|incident status)", 2, 0.68,
     "\"Review the plan and obtain briefing\" is mobilization familiarization (Understand), not a "
     "quality-control review; Understand assigned over the review-as-Evaluate default."),
    (r"base actions on", 5, 0.65,
     "\"Base actions on\" requires continuous judgment of evolving conditions (Evaluate), but the "
     "acting itself is Apply-level; Evaluate assigned as the governing demand."),
    (r"\bact as\b", 3, 0.75, None),
    (r"\bbe aware\b|\baware of\b", 2, 0.75, None),
    (r"make .{0,30}decision", 5, 0.85, None),
    (r"take command", 3, 0.75, None),
    (r"account for", 4, 0.70, None),
    (r"close.?out|close out", 3, 0.80, None),
    (r"hand.?off", 3, 0.85, None),
    (r"ground.?truth", 5, 0.75, None),
    (r"quality.?assure", 5, 0.85, None),
    (r"self.?assess", 5, 0.80, None),
]

# Leadership-level narrative bodies (role descriptions, not action statements).
NARRATIVE_RE = re.compile(
    r"^(a new leader begins|followers have several|leaders of people have|"
    r"the distance between the leader|for leaders of organizations)")
NARRATIVE = (3, 0.50,
             "Role-embodiment narrative (Leadership Level text) rather than a measurable action "
             "statement; treated as Apply (living out described leadership behaviors), but the text "
             "is a description, so any single Bloom level is a judgment call.")

# Hand-written assignments for texts verb analysis cannot read (fragments,
# garbled extraction, noun-only lines). Keyed by normalized_text.
HAND_OVERRIDES: dict[str, tuple[int, float, str]] = {
    "aircraft and/or airtanker operations": (3, 0.50,
        "Fragmentary noun phrase (FWPT knowledge-area line, no verb printed); read as performing "
        "aircraft/airtanker operations duties, but the missing verb makes the level a guess."),
    "security demonstrate knowledge of and enforces security protocols and proper identification of personnel on the aircraft ramp": (3, 0.60,
        "Garbled print layout mixes 'demonstrate knowledge' (Understand) with 'enforces protocols' "
        "(Apply/Evaluate); Apply assigned for the dominant enforcement duty."),
}

_CLAUSE_SPLIT = re.compile(r"[,;:.]| and/or | and | or ")
_WORD = re.compile(r"[a-z]+")


def classify(normalized_text: str) -> dict:
    """Assign (level, confidence, justification, verbs) to one objective."""
    text = normalized_text
    if text in HAND_OVERRIDES:
        level, conf, just = HAND_OVERRIDES[text]
        return _result(level, conf, just, verbs=["<hand-assigned>"])
    if NARRATIVE_RE.search(text):
        level, conf, just = NARRATIVE
        return _result(level, conf, just, verbs=["<narrative>"])

    hits: list[tuple[str, int, float]] = []
    phrase_just = None
    for rx, level, conf, just in PHRASE_RULES:
        if re.search(rx, text):
            hits.append((f"[{rx[:24]}]", level, conf))
            if just and conf < 0.70:
                phrase_just = just

    for clause in _CLAUSE_SPLIT.split(text.replace("re-evaluate", "reevaluate")):
        words = [w for w in _WORD.findall(clause) if w not in _SKIP_LEADS]
        if not words:
            continue
        lead = words[0]
        if lead not in VERB_TABLE:  # third-person forms: establishes, assists, uses
            for stem in (lead[:-1], lead[:-2]):
                if stem in VERB_TABLE:
                    lead = stem
                    break
        if lead in VERB_TABLE:
            # guard: "direct attack"/"direct protection" is a noun phrase
            if lead == "direct" and len(words) > 1 and words[1] in ("attack", "protection"):
                continue
            level, conf = VERB_TABLE[lead]
            hits.append((lead, level, conf))

    if not hits:
        if text in NOUN_HEADINGS:
            return _result(NOUN_HEADINGS[text], 0.50, _NOUN_HEADING_JUST, verbs=["<noun-heading>"])
        return _result(None, 0.0, "NO VERB FOUND - needs hand assignment", verbs=[])

    top = max(h[1] for h in hits)
    top_hits = [h for h in hits if h[1] == top]
    conf = max(h[2] for h in top_hits)
    span = len({h[1] for h in hits})
    if span >= 2:
        conf -= 0.05 * (span - 1)
    if len(top_hits) > 1:
        conf = min(0.95, conf + 0.05)
    conf = round(max(conf, 0.50), 2)

    just = None
    if conf < 0.70:
        parts = [f"'{v}' ({LEVEL_NAMES[l]})" for v, l, _ in sorted(set(hits), key=lambda h: -h[1])
                 if not v.startswith("[")]
        reason = phrase_just or ""
        contest = [v for v, l, c in hits if l == top and c < 0.70 and not v.startswith("[")]
        if contest and not reason:
            reason = (f"Verb(s) {', '.join(repr(v) for v in sorted(set(contest)))} sit between Bloom "
                      f"levels in operational use (doing vs judging vs designing); "
                      f"{LEVEL_NAMES[top]} chosen as the governing cognitive demand.")
        if span >= 3 and not phrase_just:
            reason += (" Compound objective spans " + str(span) +
                       " Bloom levels; highest level assigned per multi-verb convention.")
        just = (f"Verbs found: {', '.join(parts) or '(phrase rule only)'}. {reason}").strip()

    return _result(top, conf, just, verbs=[v for v, _, _ in hits])


def _result(level, conf, just, verbs):
    return {
        "level": level,
        "level_name": LEVEL_NAMES.get(level),
        "confidence": conf,
        "justification": just,
        "verbs": verbs,
    }


def load_levels(path: Path = BLOOMS_JSON) -> dict[str, dict]:
    """normalized_text -> assignment record, from the saved data/blooms.json.

    Returns an empty dict if the file is missing (run `py src/ptb/blooms.py`
    to generate it), so callers can degrade gracefully rather than crash.
    """
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {o["normalized_text"]: o for o in json.load(f)["objectives"]}


def levels_by_position_task(conn, path: Path = BLOOMS_JSON) -> dict[int, str]:
    """position_tasks.id -> Bloom level name, joining through tasks.normalized_text."""
    by_text = load_levels(path)
    rows = conn.execute(
        "SELECT pt.id, t.normalized_text FROM position_tasks pt JOIN tasks t ON pt.task_id = t.id"
    ).fetchall()
    out = {}
    for r in rows:
        rec = by_text.get(r["normalized_text"])
        out[r["id"]] = rec["level_name"] if rec else None
    return out


def assign_all(db_path=db.DEFAULT_DB_PATH) -> list[dict]:
    conn = db.connect(db_path)
    try:
        tasks = conn.execute(
            """SELECT t.id, t.canonical_text, t.normalized_text,
                      COUNT(pt.id) AS n_uses
               FROM tasks t JOIN position_tasks pt ON pt.task_id = t.id
               GROUP BY t.id ORDER BY t.id"""
        ).fetchall()
    finally:
        conn.close()
    out = []
    for t in tasks:
        r = classify(t["normalized_text"])
        out.append({
            "normalized_text": t["normalized_text"],
            "canonical_text": t["canonical_text"],
            "positions_using": t["n_uses"],
            **r,
        })
    return out


def write_outputs(rows: list[dict]) -> dict:
    BLOOMS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(BLOOMS_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"levels": LEVEL_NAMES, "objectives": rows}, f, indent=1, ensure_ascii=False)
        f.write("\n")

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Blooms"
    headers = ["#", "Objective (canonical text)", "Used by # positions",
               "Bloom's level", "Level name", "Confidence",
               "Justification (required when confidence < 0.70)"]
    arial = Font(name="Arial", size=10)
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(name="Arial", size=10, bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    low = PatternFill("solid", fgColor="FFF2CC")
    for i, r in enumerate(rows, start=1):
        vals = [i, r["canonical_text"], r["positions_using"], r["level"],
                r["level_name"], r["confidence"], r["justification"] or ""]
        for col, v in enumerate(vals, start=1):
            c = ws.cell(row=i + 1, column=col, value=v)
            c.font = arial
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if r["confidence"] < 0.70:
                c.fill = low
    for col, w in enumerate([6, 70, 10, 8, 12, 10, 70], start=1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = "A2"
    BLOOMS_XLSX.parent.mkdir(parents=True, exist_ok=True)
    wb.save(BLOOMS_XLSX)

    from collections import Counter
    dist = Counter(r["level_name"] for r in rows)
    return {
        "objectives": len(rows),
        "distribution": dict(dist),
        "below_070_with_justification": sum(1 for r in rows if r["confidence"] < 0.70),
        "unassigned": sum(1 for r in rows if r["level"] is None),
        "json": str(BLOOMS_JSON),
        "xlsx": str(BLOOMS_XLSX),
    }


if __name__ == "__main__":
    print(json.dumps(write_outputs(assign_all()), indent=2))
