"""Adjudication application + human-review workflow (Phase 4).

Implements the adjudication half of specs/matching.spec.md:

- Reads data/tier2_candidates.json (produced by src/ptb/match.py) plus two
  durable, append-only verdict stores keyed by `pair_key` (a hash of the two
  NORMALIZED TEXTS — stable across DB rebuilds, unlike task ids):

  * data/adjudications.json — Claude's rubric verdict for every candidate
    pair: relation ∈ {equivalent, subsumes, related_not_equivalent}, a note,
    and (for subsumes) the SUBSUMER'S normalized text. The a_subsumes_b vs
    b_subsumes_a DB relation value is derived here at write time from the
    subsumer text and the (task_a_id < task_b_id) row ordering.
  * data/confirmations.json — the one-time human review record: per
    pair_key, decision 'confirm' or 'reject' + timestamp + reviewer. ONLY
    entries here can ever produce status='confirmed' (AC-M4 / INV-2).

- Rewrites the task_equivalences table deterministically (AC-M6): same
  three inputs -> byte-identical table, including row ids. Tier-1 matches
  live as shared task_ids (INV-3) and never appear in this table.

- Generates reports/tier2_review_checklist.md (AC-M7): every
  status='probable' pair with both verbatim texts, positions, categories,
  score, and the adjudication note, plus the exact promote command.

Status/tier mapping (specs/matching.spec.md, Tiers section):
  adjudicated equivalent/subsumes      -> tier 2, status 'probable'
  ... + human 'confirm'                -> tier 2, status 'confirmed' (+ human_reviewed_at)
  ... + human 'reject'                 -> tier 2, status 'rejected'  (+ human_reviewed_at)
  adjudicated related_not_equivalent   -> tier 3, status 'rejected'

CLI (run from repo root or anywhere):
    py src/ptb/adjudicate.py                 # apply: verdicts -> DB + checklist
    py src/ptb/adjudicate.py status          # counts only, no writes
    py src/ptb/adjudicate.py promote <pair_key> confirm|reject
        [--note "..."] [--reviewer name]     # record human review + re-apply

If any candidate pair has no adjudication verdict, apply() writes
data/pending_adjudication.json (the full pair context Claude needs to
adjudicate), makes NO database changes, and exits with code 2. See
"Re-running the pipeline" in specs/matching.spec.md.

NTFT bridge layer (F2 ntft-bridge, specs/matching.spec.md "NTFT bridge
candidates"): when data/ntft_candidates.json exists, apply() also loads it,
requires each of its verdicts in data/adjudications.json to carry
"bridge": "ntft" (and each tier-2 verdict NOT to), and writes its rows with
match.method_string(bridge="ntft") so the two layers stay distinguishable in
task_equivalences.method. Same status rules: the adjudicator never writes
'confirmed'; only data/confirmations.json does.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb import db  # noqa: E402
from ptb import match  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ADJUDICATIONS_PATH = REPO_ROOT / "data" / "adjudications.json"
NTFT_CANDIDATES_PATH = match.DEFAULT_NTFT_CANDIDATES_PATH
CONFIRMATIONS_PATH = REPO_ROOT / "data" / "confirmations.json"
PENDING_PATH = REPO_ROOT / "data" / "pending_adjudication.json"
CHECKLIST_PATH = REPO_ROOT / "reports" / "tier2_review_checklist.md"

VALID_VERDICT_RELATIONS = {"equivalent", "subsumes", "related_not_equivalent"}


@dataclass
class EquivalenceRow:
    task_a_id: int
    task_b_id: int
    relation: str
    tier: int
    method: str
    similarity_score: float
    adjudication_note: str
    human_reviewed_at: str | None
    status: str


# ---------------------------------------------------------------------------
# Verdict / confirmation stores
# ---------------------------------------------------------------------------


def load_adjudications(path: Path = ADJUDICATIONS_PATH) -> dict[str, dict]:
    """{pair_key: verdict}. Validates structure; duplicate keys are an error."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result: dict[str, dict] = {}
    for entry in data["adjudications"]:
        key = entry["pair_key"]
        if key in result:
            raise ValueError(f"duplicate adjudication for pair_key {key}")
        relation = entry["relation"]
        if relation not in VALID_VERDICT_RELATIONS:
            raise ValueError(f"invalid relation {relation!r} for pair_key {key}")
        if relation == "subsumes" and not entry.get("subsumer_normalized_text"):
            raise ValueError(f"subsumes verdict without subsumer_normalized_text: {key}")
        if not entry.get("note"):
            raise ValueError(f"adjudication without note (AC-M5): {key}")
        result[key] = entry
    return result


def load_confirmations(path: Path = CONFIRMATIONS_PATH) -> dict[str, dict]:
    """{pair_key: confirmation}. Later entries for the same key override
    earlier ones (a human may re-review); each must carry a timestamp."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result: dict[str, dict] = {}
    for entry in data["confirmations"]:
        if entry["decision"] not in ("confirm", "reject"):
            raise ValueError(f"invalid decision {entry['decision']!r} for {entry['pair_key']}")
        if not entry.get("human_reviewed_at"):
            raise ValueError(f"confirmation without human_reviewed_at: {entry['pair_key']}")
        result[entry["pair_key"]] = entry
    return result


def load_candidates(path: Path = match.DEFAULT_CANDIDATES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_bridge_candidates(path: Path = NTFT_CANDIDATES_PATH) -> dict | None:
    """The NTFT bridge artifact, or None when the bridge has not been run."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("bridge") != "ntft":
        raise ValueError(f"{path} is not an NTFT bridge artifact (missing \"bridge\": \"ntft\")")
    return payload


def load_all_candidates(
    candidates_path: Path = match.DEFAULT_CANDIDATES_PATH,
    ntft_candidates_path: Path = NTFT_CANDIDATES_PATH,
) -> list[dict]:
    """Tier-2 candidates followed by bridge candidates (if any), each dict
    carrying a "bridge" key (None for tier 2) so consumers can tell the
    layers apart without re-reading the files."""
    out = [{**c, "bridge": None} for c in load_candidates(candidates_path)["candidates"]]
    bridge = load_bridge_candidates(ntft_candidates_path)
    if bridge is not None:
        out.extend({**c, "bridge": "ntft"} for c in bridge["candidates"])
    return out


# ---------------------------------------------------------------------------
# Applying verdicts -> task_equivalences rows
# ---------------------------------------------------------------------------


def build_rows(
    candidates: list[dict],
    adjudications: dict[str, dict],
    confirmations: dict[str, dict],
    method: str,
    bridge: str | None = None,
) -> tuple[list[EquivalenceRow], list[dict]]:
    """Map candidates + verdicts (+ confirmations) to DB rows.

    Returns (rows, pending) where pending is the list of candidates that
    have no adjudication verdict yet. `bridge` names the layer these
    candidates belong to; a verdict's "bridge" tag must agree (AC-B3), so a
    tier-2 verdict can never be silently reused for a bridge pair or vice
    versa.
    """
    rows: list[EquivalenceRow] = []
    pending: list[dict] = []

    for cand in candidates:
        verdict = adjudications.get(cand["pair_key"])
        if verdict is None:
            pending.append({**cand, "bridge": bridge})
            continue
        if verdict.get("bridge") != bridge:
            raise ValueError(
                f"verdict for pair_key {cand['pair_key']} is tagged bridge={verdict.get('bridge')!r} "
                f"but the candidate belongs to layer bridge={bridge!r}"
            )

        a, b = cand["a"], cand["b"]
        if not a["task_id"] < b["task_id"]:
            raise ValueError(f"candidate pair not id-ordered: {cand['pair_key']}")

        relation = verdict["relation"]
        if relation == "subsumes":
            subsumer = verdict["subsumer_normalized_text"]
            if subsumer == a["normalized_text"]:
                relation = "a_subsumes_b"
            elif subsumer == b["normalized_text"]:
                relation = "b_subsumes_a"
            else:
                raise ValueError(
                    f"subsumer text matches neither side of pair {cand['pair_key']}: {subsumer!r}"
                )

        method_value = method
        if cand.get("seed_reason"):
            method_value = f"{method}; seeded grounded pair (below threshold): {cand['seed_reason']}"

        if relation == "related_not_equivalent":
            tier, status, reviewed_at = 3, "rejected", None
        else:
            tier, status, reviewed_at = 2, "probable", None
            conf = confirmations.get(cand["pair_key"])
            if conf is not None:
                status = "confirmed" if conf["decision"] == "confirm" else "rejected"
                reviewed_at = conf["human_reviewed_at"]

        rows.append(
            EquivalenceRow(
                task_a_id=a["task_id"],
                task_b_id=b["task_id"],
                relation=relation,
                tier=tier,
                method=method_value,
                similarity_score=cand["score"],
                adjudication_note=verdict["note"],
                human_reviewed_at=reviewed_at,
                status=status,
            )
        )

    rows.sort(key=lambda r: (r.task_a_id, r.task_b_id))
    return rows, pending


def write_rows(conn: sqlite3.Connection, rows: list[EquivalenceRow]) -> None:
    """Deterministic rewrite of the whole table (Phase 4 owns it; tier-1
    matches are shared task_ids and never have rows here)."""
    conn.execute("DELETE FROM task_equivalences")
    # Explicit ids below make the rewrite fully deterministic (AC-M6);
    # the table has no AUTOINCREMENT, so no sequence to reset.
    for i, r in enumerate(rows, start=1):
        conn.execute(
            """
            INSERT INTO task_equivalences
                (id, task_a_id, task_b_id, relation, tier, method,
                 similarity_score, adjudication_note, human_reviewed_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (i, r.task_a_id, r.task_b_id, r.relation, r.tier, r.method,
             r.similarity_score, r.adjudication_note, r.human_reviewed_at, r.status),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# AC-M7 checklist
# ---------------------------------------------------------------------------


def _side_block(side: dict) -> list[str]:
    lines = [f"  - text: “{side['canonical_text']}”"]
    for occ in side["occurrences"]:
        lines.append(
            f"    - {occ['position']} #{occ['task_number']} ({occ['title']}) — "
            f"category: {occ['category']} — code: {occ['code_raw']}"
        )
        if occ["verbatim_text"] != side["canonical_text"]:
            lines.append(f"      verbatim: “{occ['verbatim_text']}”")
    return lines


def generate_checklist(
    candidates: list[dict],
    rows: list[EquivalenceRow],
    out_path: Path = CHECKLIST_PATH,
) -> int:
    """Write the human-review checklist for every status='probable' pair.

    Returns the number of probable pairs listed.
    """
    by_ids = {(c["a"]["task_id"], c["b"]["task_id"]): c for c in candidates}
    probable = [r for r in rows if r.status == "probable"]
    # Highest score first: near-duplicates are the fastest reviews.
    probable.sort(key=lambda r: (-r.similarity_score, r.task_a_id, r.task_b_id))

    lines = [
        "# Tier-2 equivalence review checklist",
        "",
        "**Generated by `py src/ptb/adjudicate.py` — do not hand-edit; it is",
        "regenerated on every run.** (AC-M7, specs/matching.spec.md)",
        "",
        f"{len(probable)} pairs adjudicated `equivalent` or `subsumes` await your",
        "one-time review. For each pair, record your decision with:",
        "",
        "```",
        "py src/ptb/adjudicate.py promote <pair_key> confirm   # agree: real equivalence/subsumption",
        "py src/ptb/adjudicate.py promote <pair_key> reject    # disagree: do not surface to candidates",
        "```",
        "",
        "Only `confirm` ever makes a pair count toward qualification gaps",
        "(Phase 5 uses status='confirmed' rows only). Decisions are stored in",
        "`data/confirmations.json` keyed by text (not task id), so they survive",
        "database rebuilds and corpus additions.",
        "",
        "Rubric reminders (specs/matching.spec.md): action level must match;",
        "narrower scope = subsumption, not equivalence; doubt → reject.",
        "",
        "---",
        "",
    ]

    for n, r in enumerate(probable, start=1):
        cand = by_ids[(r.task_a_id, r.task_b_id)]
        relation_human = {
            "equivalent": "equivalent",
            "a_subsumes_b": "A subsumes B",
            "b_subsumes_a": "B subsumes A",
        }[r.relation]
        lines.append(f"## {n}. `{cand['pair_key']}` — {relation_human} — score {r.similarity_score}")
        lines.append("")
        lines.append("- [ ] reviewed")
        lines.append(f"- **Task A** (task_id {r.task_a_id}):")
        lines.extend(_side_block(cand["a"]))
        lines.append(f"- **Task B** (task_id {r.task_b_id}):")
        lines.extend(_side_block(cand["b"]))
        lines.append(f"- **Adjudication note:** {r.adjudication_note}")
        if cand.get("seed_reason"):
            lines.append(f"- **Seeded:** {cand['seed_reason']}")
        if cand.get("bridge"):
            lines.append(f"- **Bridge:** {cand['bridge']} (one NTFT-standard side, one NWCG side; "
                         f"reviewed on reports/{cand['bridge']}_review_sheet.xlsx)")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return len(probable)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def apply(
    db_path: Path | str = db.DEFAULT_DB_PATH,
    candidates_path: Path = match.DEFAULT_CANDIDATES_PATH,
    adjudications_path: Path = ADJUDICATIONS_PATH,
    confirmations_path: Path = CONFIRMATIONS_PATH,
    checklist_path: Path = CHECKLIST_PATH,
    pending_path: Path = PENDING_PATH,
    ntft_candidates_path: Path | None = None,
) -> dict:
    """Apply all verdicts to the DB and regenerate the checklist.

    Returns stats. If any candidate lacks a verdict, writes pending_path,
    changes nothing in the DB, and returns with stats['pending'] > 0.
    The NTFT bridge layer is included when its file exists; its rows carry
    the bridge method string. ntft_candidates_path=None means "the bridge
    artifact that belongs with candidates_path": data/ntft_candidates.json
    when candidates_path is the shipped tier-2 artifact, nothing otherwise
    (a caller applying a custom candidate set, e.g. the fixture-corpus
    tests, never gets the real corpus's bridge pairs mixed in).
    """
    if ntft_candidates_path is None:
        if Path(candidates_path).resolve() == Path(match.DEFAULT_CANDIDATES_PATH).resolve():
            ntft_candidates_path = NTFT_CANDIDATES_PATH
        else:
            ntft_candidates_path = Path(candidates_path).with_name("__no_bridge__.json")
    payload = load_candidates(candidates_path)
    candidates = [{**c, "bridge": None} for c in payload["candidates"]]
    adjudications = load_adjudications(adjudications_path)
    confirmations = load_confirmations(confirmations_path)

    rows, pending = build_rows(candidates, adjudications, confirmations, match.method_string())

    bridge_payload = load_bridge_candidates(ntft_candidates_path)
    bridge_candidates: list[dict] = []
    bridge_rows: list[EquivalenceRow] = []
    if bridge_payload is not None:
        bridge_candidates = [{**c, "bridge": "ntft"} for c in bridge_payload["candidates"]]
        bridge_rows, bridge_pending = build_rows(
            bridge_candidates, adjudications, confirmations,
            match.method_string(bridge="ntft"), bridge="ntft",
        )
        pending.extend(bridge_pending)
        candidates = candidates + bridge_candidates
        rows = sorted(rows + bridge_rows, key=lambda r: (r.task_a_id, r.task_b_id))

    if pending:
        with open(pending_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"pending_count": len(pending), "pending": pending}, f, indent=1, ensure_ascii=False)
        return {
            "pending": len(pending),
            "pending_file": str(pending_path),
            "db_written": False,
            "message": "Adjudicate the pending pairs (rubric: specs/matching.spec.md), "
                       "append verdicts to data/adjudications.json, rerun.",
        }
    # Stale pending file from an earlier run would misdirect the next
    # adjudicator; remove it once everything has a verdict.
    if Path(pending_path).exists():
        Path(pending_path).unlink()

    conn = db.connect(db_path)
    try:
        write_rows(conn, rows)
        probable_count = generate_checklist(candidates, rows, checklist_path)
        stats = {
            "pending": 0,
            "db_written": True,
            "rows": len(rows),
            "tier2_probable": probable_count,
            "tier2_confirmed": sum(1 for r in rows if r.status == "confirmed"),
            "tier2_rejected_by_human": sum(1 for r in rows if r.tier == 2 and r.status == "rejected"),
            "tier3_rejected": sum(1 for r in rows if r.tier == 3),
            "checklist": str(checklist_path),
        }
        if bridge_payload is not None:
            stats["ntft_bridge"] = {
                "rows": len(bridge_rows),
                "probable": sum(1 for r in bridge_rows if r.status == "probable"),
                "confirmed": sum(1 for r in bridge_rows if r.status == "confirmed"),
                "rejected_by_human": sum(1 for r in bridge_rows if r.tier == 2 and r.status == "rejected"),
                "tier3_rejected": sum(1 for r in bridge_rows if r.tier == 3),
            }
    finally:
        conn.close()
    return stats


def promote(
    pair_key: str,
    decision: str,
    note: str | None = None,
    reviewer: str = "human",
    confirmations_path: Path = CONFIRMATIONS_PATH,
    **apply_kwargs,
) -> dict:
    """Record a human review decision and re-apply to the DB."""
    if decision not in ("confirm", "reject"):
        raise ValueError("decision must be 'confirm' or 'reject'")

    adjudications = load_adjudications(apply_kwargs.get("adjudications_path", ADJUDICATIONS_PATH))
    verdict = adjudications.get(pair_key)
    if verdict is None:
        raise KeyError(f"pair_key {pair_key} has no adjudication verdict")
    if verdict["relation"] == "related_not_equivalent":
        raise ValueError(f"pair_key {pair_key} was adjudicated related_not_equivalent; nothing to promote")

    if confirmations_path.exists():
        with open(confirmations_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"confirmations": []}
    data["confirmations"].append(
        {
            "pair_key": pair_key,
            "decision": decision,
            "human_reviewed_at": date.today().isoformat(),
            "reviewer": reviewer,
            **({"note": note} if note else {}),
        }
    )
    with open(confirmations_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")

    return apply(confirmations_path=confirmations_path, **apply_kwargs)


def status(
    candidates_path: Path = match.DEFAULT_CANDIDATES_PATH,
    adjudications_path: Path = ADJUDICATIONS_PATH,
    confirmations_path: Path = CONFIRMATIONS_PATH,
) -> dict:
    payload = load_candidates(candidates_path)
    adjudications = load_adjudications(adjudications_path)
    confirmations = load_confirmations(confirmations_path)
    keys = [c["pair_key"] for c in payload["candidates"]]
    result = {
        "candidates": len(keys),
        "adjudicated": sum(1 for k in keys if k in adjudications),
        "pending": sum(1 for k in keys if k not in adjudications),
        "human_reviewed": sum(1 for k in keys if k in confirmations),
    }
    bridge = load_bridge_candidates()
    if bridge is not None:
        bkeys = [c["pair_key"] for c in bridge["candidates"]]
        result["ntft_bridge"] = {
            "candidates": len(bkeys),
            "adjudicated": sum(1 for k in bkeys if k in adjudications),
            "pending": sum(1 for k in bkeys if k not in adjudications),
            "human_reviewed": sum(1 for k in bkeys if k in confirmations),
            "by_relation": dict(sorted(Counter(
                adjudications[k]["relation"] for k in bkeys if k in adjudications
            ).items())),
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply tier-2 adjudication verdicts (Phase 4).")
    sub = parser.add_subparsers(dest="command")
    p_apply = sub.add_parser("apply", help="apply verdicts -> DB + checklist (default)")
    p_apply.add_argument("--db", default=str(db.DEFAULT_DB_PATH))
    sub.add_parser("status", help="show verdict coverage counts")
    p_promote = sub.add_parser("promote", help="record a human review decision")
    p_promote.add_argument("pair_key")
    p_promote.add_argument("decision", choices=["confirm", "reject"])
    p_promote.add_argument("--note", default=None)
    p_promote.add_argument("--reviewer", default="human")

    args = parser.parse_args()
    if args.command == "status":
        result = status()
    elif args.command == "promote":
        result = promote(args.pair_key, args.decision, note=args.note, reviewer=args.reviewer)
    else:
        result = apply(**({"db_path": args.db} if getattr(args, "db", None) else {}))
    print(json.dumps(result, indent=2))
    if result.get("pending"):
        sys.exit(2)
