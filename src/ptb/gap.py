"""Gap analysis: the "closest positions" query (Phase 5).

Implements specs/gap-analysis.spec.md. Pure functions over an already-built
SQLite database (data/ptb.sqlite) — no framework, no writes, no I/O side
effects beyond the read-only queries needed to answer a query. A future app
backend calls closest_positions() directly; this module also ships a CLI
demo (`py src/ptb/gap.py --qual ENGB`).

Honesty contract (spec's own wording, governs all rendered text): report
demonstrated-task overlap and requirement gaps, never a certification
decision. See DISCLAIMER below.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb import db  # noqa: E402

DISCLAIMER = (
    "This report shows demonstrated-task overlap and requirement gaps only. "
    "It is not a certification decision — agencies certify, and a position "
    "task book is still issued and completed per agency policy. "
    "Training/experience/fitness/currency requirements are listed for "
    "information only and are not assessed here."
)

# Rendered label for enhanced (official = 0) positions — the "FireTech" set,
# i.e. the NTFT (Novel Thinking Fire Tech) positions authored outside NWCG.
# `official = 0` remains the load-bearing flag (schema INV-8; tests) and
# PositionGap.draft stays True; only this human-readable label changed per
# owner direction 2026-07-12 (was "draft position — not an official NWCG
# standard", now the owning org's own designation, "NTFT standard"). Enhanced
# positions are still never intermixed silently with NWCG-official ones.
DRAFT_LABEL = "NTFT standard"  # NTFT = Novel Thinking Fire Tech

# specs/matching.spec.md's context -> satisfied-codes matrix, plus 'ALL'
# (a valid code per models.VALID_CODES, not named in the matrix; treated as
# satisfied by any context, consistent with its name) and 'developmental'
# (the enhanced format's own context, added for its redefined O — see
# gap-analysis.spec.md's "Cross-format context caution").
_CONTEXT_SATISFIES: dict[str, set[str]] = {
    "wildfire": {"W", "I", "O", "ALL"},
    "prescribed_fire": {"RX", "I", "O", "ALL"},
    "incident": {"I", "O", "ALL"},
    "simulation": {"S", "O", "ALL"},
    "rare_event": {"R", "O", "ALL"},
    "other": {"O", "ALL"},
    "developmental": {"O", "ALL"},
}

# Requirement kinds that gate satisfaction (rules 3-5) vs. display-only.
_GATED_KINDS = {"course", "prerequisite_position", "other"}
_INFO_KINDS = {"training", "experience", "fitness", "currency"}


def code_satisfied(code_raw: str, context: str, is_enhanced_format: bool) -> bool:
    """Does a completion in `context` satisfy a target slot's `code_raw`?

    code_raw may hold alternatives ("W/RX"), satisfied if any alternative
    matches. The enhanced format redefines O as developmental/non-incident:
    for an enhanced-format slot, O is satisfied only by a 'developmental'
    context, never by NWCG's broader "any situation" contexts (which do NOT
    apply in reverse per the spec).
    """
    # Alternatives print as "W/RX" or, in a few books, "I, S" (see
    # extraction.spec.md changelog 2026-11-03).
    for code in (c for c in re.split(r"[/,]\s*", code_raw) if c):
        if code == "O" and is_enhanced_format:
            if context == "developmental":
                return True
            continue
        if code in _CONTEXT_SATISFIES.get(context, set()):
            return True
    return False


# ---------------------------------------------------------------------------
# Input / output shapes (gap-analysis.spec.md's "Input"/"Output" sections)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletedTask:
    position_task_id: int
    context: str  # wildfire | prescribed_fire | incident | simulation | rare_event | other | developmental


@dataclass(frozen=True)
class CandidateProfile:
    held_qualifications: list[str] = field(default_factory=list)
    completed_courses: list[str] = field(default_factory=list)
    completed_task_ids: list[CompletedTask] = field(default_factory=list)


@dataclass(frozen=True)
class SatisfiedSlot:
    position_task_id: int
    task_number: int
    verbatim_text: str
    derivation: str  # 'direct' | 'implied_by'
    derivation_position: str | None = None
    equivalence_id: int | None = None


@dataclass(frozen=True)
class GapSlot:
    position_task_id: int
    task_number: int
    verbatim_text: str
    category: str
    code_raw: str


@dataclass(frozen=True)
class Slot:
    position_task_id: int
    task_number: int
    verbatim_text: str
    category: str
    code_raw: str


@dataclass(frozen=True)
class GapReq:
    kind: str
    value: str
    detail: str | None = None
    alternatives: list[str] = field(default_factory=list)  # members of an unsatisfied alt_group


@dataclass(frozen=True)
class SatisfiedReq:
    kind: str
    value: str
    derivation: str  # 'direct' | 'implied_by' | 'conferred_by'
    derivation_position: str | None = None


@dataclass(frozen=True)
class InfoRequirement:
    kind: str
    value: str
    detail: str | None = None


@dataclass(frozen=True)
class PositionGap:
    position: str
    title: str
    draft: bool
    total_slots: int
    satisfied: list[SatisfiedSlot]
    gaps_tasks: list[GapSlot]
    gaps_context_only: list[Slot]
    gaps_requirements: list[GapReq]
    satisfied_requirements: list[SatisfiedReq]
    info_requirements: list[InfoRequirement]


# ---------------------------------------------------------------------------
# DB loading — one read pass, all lookups built in memory.
# ---------------------------------------------------------------------------


@dataclass
class _GapContext:
    positions: dict[int, dict]  # position_id -> {code, title, official, format}
    code_to_id: dict[str, int]
    position_tasks_by_position: dict[int, list[sqlite3.Row]]
    task_id_of_position_task: dict[int, int]
    position_tasks_by_task_id: dict[int, list[int]]  # task_id -> [position_id]
    satisfiers: dict[int, list[tuple[int, int | None]]]  # target_task_id -> [(satisfier_task_id, equivalence_id)]
    requirements_by_position: dict[int, list[sqlite3.Row]]
    implication_edges: dict[int, set[int]]
    prereq_edges: dict[int, set[int]]


def _build_context(conn: sqlite3.Connection) -> _GapContext:
    positions: dict[int, dict] = {}
    code_to_id: dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT p.id, p.code, p.title, sd.official, sd.format
        FROM positions p JOIN source_documents sd ON p.source_document_id = sd.id
        """
    ):
        positions[row["id"]] = {
            "code": row["code"],
            "title": row["title"],
            "official": row["official"],
            "format": row["format"],
        }
        code_to_id[row["code"]] = row["id"]

    position_tasks_by_position: dict[int, list[sqlite3.Row]] = {}
    task_id_of_position_task: dict[int, int] = {}
    position_tasks_by_task_id: dict[int, list[int]] = {}
    for row in conn.execute("SELECT * FROM position_tasks ORDER BY position_id, task_number"):
        position_tasks_by_position.setdefault(row["position_id"], []).append(row)
        task_id_of_position_task[row["id"]] = row["task_id"]
        position_tasks_by_task_id.setdefault(row["task_id"], []).append(row["position_id"])

    satisfiers: dict[int, list[tuple[int, int | None]]] = {}

    def _add_satisfier(target: int, satisfier: int, equivalence_id: int | None) -> None:
        satisfiers.setdefault(target, [])
        if (satisfier, equivalence_id) not in satisfiers[target]:
            satisfiers[target].append((satisfier, equivalence_id))

    for task_id in task_id_of_position_task.values():
        _add_satisfier(task_id, task_id, None)  # tier-1 self-identity always satisfies

    for row in conn.execute(
        "SELECT * FROM task_equivalences WHERE status = 'confirmed' ORDER BY id"
    ):
        a, b, relation, eq_id = row["task_a_id"], row["task_b_id"], row["relation"], row["id"]
        if relation == "equivalent":
            _add_satisfier(a, b, eq_id)
            _add_satisfier(b, a, eq_id)
        elif relation == "a_subsumes_b":
            _add_satisfier(b, a, eq_id)  # completing a (subsumer) satisfies b
        elif relation == "b_subsumes_a":
            _add_satisfier(a, b, eq_id)  # completing b (subsumer) satisfies a
        # 'related_not_equivalent' never satisfies anything.

    requirements_by_position: dict[int, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM position_requirements ORDER BY position_id, kind, value"):
        requirements_by_position.setdefault(row["position_id"], []).append(row)

    implication_edges: dict[int, set[int]] = {}
    for row in conn.execute("SELECT holding_position_id, implied_position_id FROM position_implications"):
        implication_edges.setdefault(row["holding_position_id"], set()).add(row["implied_position_id"])

    prereq_edges: dict[int, set[int]] = {}
    for pos_id, reqs in requirements_by_position.items():
        for req in reqs:
            if req["kind"] != "prerequisite_position" or req["alt_group"] is not None:
                continue  # alternatives: holding the position proves one of them, not which
            target_id = code_to_id.get(req["value"])
            if target_id is not None:
                prereq_edges.setdefault(pos_id, set()).add(target_id)

    return _GapContext(
        positions=positions,
        code_to_id=code_to_id,
        position_tasks_by_position=position_tasks_by_position,
        task_id_of_position_task=task_id_of_position_task,
        position_tasks_by_task_id=position_tasks_by_task_id,
        satisfiers=satisfiers,
        requirements_by_position=requirements_by_position,
        implication_edges=implication_edges,
        prereq_edges=prereq_edges,
    )


def _bfs_with_root(
    held_ids_in_order: list[int], edges: dict[int, set[int]]
) -> tuple[set[int], dict[int, int]]:
    """Closure over `edges` starting from held_ids_in_order.

    root_of[node] = the held id (first, in held_ids_in_order, to reach it)
    that the chain to `node` originates from — used to cite the ORIGINAL
    held qualification in derivation text (per PLAN.md's CLI example
    "S-230, FFT1 satisfied — implied by ENGB", not an intermediate hop).
    """
    visited: set[int] = set()
    root_of: dict[int, int] = {}
    queue: deque[int] = deque()
    for hid in held_ids_in_order:
        if hid not in visited:
            visited.add(hid)
            root_of[hid] = hid
            queue.append(hid)
    while queue:
        n = queue.popleft()
        for nxt in edges.get(n, ()):
            if nxt not in visited:
                visited.add(nxt)
                root_of[nxt] = root_of[n]
                queue.append(nxt)
    return visited, root_of


# ---------------------------------------------------------------------------
# The query
# ---------------------------------------------------------------------------


def closest_positions(
    profile: CandidateProfile,
    limit: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[PositionGap]:
    owns_conn = conn is None
    conn = conn or db.connect()
    try:
        ctx = _build_context(conn)

        held_ids_in_order = [ctx.code_to_id[c] for c in profile.held_qualifications if c in ctx.code_to_id]

        conferred_set, conferred_root = _bfs_with_root(held_ids_in_order, ctx.implication_edges)
        prereq_chain_set, prereq_root = _bfs_with_root(held_ids_in_order, ctx.prereq_edges)
        merged_edges: dict[int, set[int]] = {}
        for n in set(ctx.implication_edges) | set(ctx.prereq_edges):
            merged_edges[n] = ctx.implication_edges.get(n, set()) | ctx.prereq_edges.get(n, set())
        reachable_for_tasks, tasks_root = _bfs_with_root(held_ids_in_order, merged_edges)

        held_ids = set(held_ids_in_order)
        excluded = held_ids | conferred_set

        completed_by_task_id: dict[int, list[str]] = {}
        for ct in profile.completed_task_ids:
            task_id = ctx.task_id_of_position_task.get(ct.position_task_id)
            if task_id is None:
                raise ValueError(f"unknown position_task_id in profile: {ct.position_task_id}")
            completed_by_task_id.setdefault(task_id, []).append(ct.context)

        results: list[PositionGap] = []
        for pos_id, pos in ctx.positions.items():
            if pos_id in excluded:
                continue
            slots = ctx.position_tasks_by_position.get(pos_id, [])
            is_enhanced = pos["format"] == "enhanced_gdoc"

            satisfied: list[SatisfiedSlot] = []
            gaps_tasks: list[GapSlot] = []
            gaps_context_only: list[Slot] = []

            for slot in slots:
                target_task_id = slot["task_id"]
                satisfier_list = ctx.satisfiers.get(target_task_id, [(target_task_id, None)])

                matched_direct = False
                context_mismatch = False
                for sat_task_id, equiv_id in satisfier_list:
                    for completed_context in completed_by_task_id.get(sat_task_id, []):
                        if code_satisfied(slot["code_raw"], completed_context, is_enhanced):
                            satisfied.append(
                                SatisfiedSlot(
                                    position_task_id=slot["id"],
                                    task_number=slot["task_number"],
                                    verbatim_text=slot["verbatim_text"],
                                    derivation="direct",
                                    equivalence_id=equiv_id,
                                )
                            )
                            matched_direct = True
                            break
                        else:
                            context_mismatch = True
                    if matched_direct:
                        break
                if matched_direct:
                    continue

                matched_implied = False
                for sat_task_id, equiv_id in satisfier_list:
                    owner_positions = ctx.position_tasks_by_task_id.get(sat_task_id, [])
                    for owner_pos_id in owner_positions:
                        if owner_pos_id in reachable_for_tasks:
                            root_code = ctx.positions[tasks_root[owner_pos_id]]["code"]
                            satisfied.append(
                                SatisfiedSlot(
                                    position_task_id=slot["id"],
                                    task_number=slot["task_number"],
                                    verbatim_text=slot["verbatim_text"],
                                    derivation="implied_by",
                                    derivation_position=root_code,
                                    equivalence_id=equiv_id,
                                )
                            )
                            matched_implied = True
                            break
                    if matched_implied:
                        break
                if matched_implied:
                    continue

                if context_mismatch:
                    gaps_context_only.append(
                        Slot(
                            position_task_id=slot["id"],
                            task_number=slot["task_number"],
                            verbatim_text=slot["verbatim_text"],
                            category=slot["category"],
                            code_raw=slot["code_raw"],
                        )
                    )
                else:
                    gaps_tasks.append(
                        GapSlot(
                            position_task_id=slot["id"],
                            task_number=slot["task_number"],
                            verbatim_text=slot["verbatim_text"],
                            category=slot["category"],
                            code_raw=slot["code_raw"],
                        )
                    )

            gaps_requirements: list[GapReq] = []
            satisfied_requirements: list[SatisfiedReq] = []
            info_requirements: list[InfoRequirement] = []

            # Alternative groups (gap-analysis.spec.md "Alternative groups"): members
            # sharing an alt_group are evaluated together - any one satisfies the
            # group; an unsatisfied group is one gap, "A / B".
            group_members: dict[tuple[str, int], list] = {}
            for req in ctx.requirements_by_position.get(pos_id, []):
                if req["alt_group"] is not None:
                    group_members.setdefault((req["kind"], req["alt_group"]), []).append(req)
            group_outcome: dict[tuple[str, int], SatisfiedReq | GapReq] = {}

            for req in ctx.requirements_by_position.get(pos_id, []):
                kind, value, detail = req["kind"], req["value"], req["detail"]
                if kind in _INFO_KINDS:
                    info_requirements.append(InfoRequirement(kind=kind, value=value, detail=detail))
                    continue
                if kind not in _GATED_KINDS:
                    continue

                derivation: str | None = None
                derivation_position: str | None = None

                if kind == "course" and value in profile.completed_courses:
                    derivation = "direct"
                elif kind == "prerequisite_position" and value in profile.held_qualifications:
                    derivation = "direct"
                elif kind == "other" and (
                    value in profile.completed_courses or value in profile.held_qualifications
                ):
                    derivation = "direct"

                if derivation is None and kind == "prerequisite_position":
                    val_pos_id = ctx.code_to_id.get(value)
                    if val_pos_id is not None and val_pos_id in prereq_chain_set and val_pos_id not in held_ids:
                        derivation = "implied_by"
                        derivation_position = ctx.positions[prereq_root[val_pos_id]]["code"]

                if derivation is None:
                    # Rule 4 by requirement text: the same (kind, value) sits in
                    # the requirement set of a held qualification or of any
                    # position in its chain. For prerequisite_position this is
                    # the only route for codes with no `positions` row (FFT2,
                    # EDRC, EMT — requirements pages but no task book), which
                    # prereq_edges cannot reach; without it an ENGB holder was
                    # re-demanded FFT2 although ENGB -> FFT1 -> FFT2 (found by
                    # the 2026-11-03 spec-checker audit, AC-G2).
                    for owner_pos_id in held_ids | prereq_chain_set:
                        owner_reqs = ctx.requirements_by_position.get(owner_pos_id, [])
                        if any(r["kind"] == kind and r["value"] == value for r in owner_reqs):
                            root_id = prereq_root.get(owner_pos_id, owner_pos_id)
                            derivation = "implied_by"
                            derivation_position = ctx.positions[root_id]["code"]
                            break

                if derivation is None and kind == "prerequisite_position":
                    val_pos_id = ctx.code_to_id.get(value)
                    if val_pos_id is not None and val_pos_id in conferred_set and val_pos_id not in held_ids:
                        derivation = "conferred_by"
                        derivation_position = ctx.positions[conferred_root[val_pos_id]]["code"]

                outcome: SatisfiedReq | GapReq
                if derivation is not None:
                    outcome = SatisfiedReq(kind=kind, value=value, derivation=derivation, derivation_position=derivation_position)
                else:
                    outcome = GapReq(kind=kind, value=value, detail=detail)

                group_key = (kind, req["alt_group"]) if req["alt_group"] is not None else None
                if group_key is None:
                    (satisfied_requirements if derivation is not None else gaps_requirements).append(outcome)
                    continue
                prior = group_outcome.get(group_key)
                # keep the first satisfying member, but let a direct credential
                # displace an implied/conferred one so the report names what is held
                if not isinstance(prior, SatisfiedReq) or (
                    isinstance(outcome, SatisfiedReq) and outcome.derivation == "direct" and prior.derivation != "direct"
                ):
                    group_outcome[group_key] = outcome
                members = group_members[group_key]
                if req is not members[-1]:
                    continue  # decide once every member has been evaluated
                final = group_outcome[group_key]
                if isinstance(final, SatisfiedReq):
                    satisfied_requirements.append(final)
                else:
                    codes = [m["value"] for m in members]
                    gaps_requirements.append(
                        GapReq(kind=kind, value=" / ".join(codes), detail=detail, alternatives=codes)
                    )

            results.append(
                PositionGap(
                    position=pos["code"],
                    title=pos["title"],
                    draft=(pos["official"] == 0),
                    total_slots=len(slots),
                    satisfied=satisfied,
                    gaps_tasks=gaps_tasks,
                    gaps_context_only=gaps_context_only,
                    gaps_requirements=gaps_requirements,
                    satisfied_requirements=satisfied_requirements,
                    info_requirements=info_requirements,
                )
            )

        results.sort(
            key=lambda pg: (
                len(pg.gaps_tasks) + len(pg.gaps_context_only) + len(pg.gaps_requirements),
                len(pg.gaps_tasks),
                pg.position,
            )
        )
        if limit is not None:
            results = results[:limit]
        return results
    finally:
        if owns_conn:
            conn.close()


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataCurrency:
    """What edition of the source data a report describes (gap-analysis.spec.md
    "Data currency", AC-G9). Read from source_documents, never hardcoded."""

    downloaded_at: str | None  # newest corpus download date
    nwcg_edition_min: str | None  # oldest NWCG (official=1) task-book edition, ISO YYYY-MM
    nwcg_edition_max: str | None  # newest NWCG task-book edition
    nwcg_document_count: int
    ntft_edition: str | None  # NTFT draft's own date (DOCX modified), if any

    def line(self) -> str:
        parts = [f"corpus downloaded {self.downloaded_at or 'unknown'}"]
        if self.nwcg_edition_max:
            span = (
                f"{self.nwcg_edition_min} to {self.nwcg_edition_max}"
                if self.nwcg_edition_min != self.nwcg_edition_max
                else self.nwcg_edition_max
            )
            parts.append(f"NWCG task-book editions {span} ({self.nwcg_document_count} documents)")
        if self.ntft_edition:
            parts.append(f"{DRAFT_LABEL} draft dated {self.ntft_edition}")
        return "Data as of: " + "; ".join(parts) + "."


def data_currency(conn: sqlite3.Connection | None = None) -> DataCurrency:
    owns_conn = conn is None
    if owns_conn:
        conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT MAX(downloaded_at) AS downloaded_at,
                   MIN(CASE WHEN official = 1 THEN edition_date END) AS ed_min,
                   MAX(CASE WHEN official = 1 THEN edition_date END) AS ed_max,
                   SUM(CASE WHEN official = 1 THEN 1 ELSE 0 END) AS n_official,
                   MAX(CASE WHEN official = 0 THEN edition_date END) AS ntft
            FROM source_documents WHERE role = 'ptb'
            """
        ).fetchone()
    finally:
        if owns_conn:
            conn.close()
    return DataCurrency(
        downloaded_at=row["downloaded_at"],
        nwcg_edition_min=row["ed_min"],
        nwcg_edition_max=row["ed_max"],
        nwcg_document_count=row["n_official"] or 0,
        ntft_edition=row["ntft"],
    )


def format_report(
    profile: CandidateProfile,
    results: list[PositionGap],
    limit: int = 10,
    currency: DataCurrency | None = None,
) -> str:
    lines = [DISCLAIMER]
    # Honesty contract: say which edition of the data this report describes.
    lines.append((currency or data_currency()).line())
    lines.append("")
    for pg in results[:limit]:
        remaining = len(pg.gaps_tasks) + len(pg.gaps_context_only) + len(pg.gaps_requirements)
        draft_tag = f" ({DRAFT_LABEL})" if pg.draft else ""
        lines.append(f"{pg.position} — {pg.title}{draft_tag}")
        if remaining == 0:
            lines.append("  No demonstrated gaps against this position's task book or requirements.")
        else:
            parts = []
            if pg.gaps_tasks:
                parts.append(f"{len(pg.gaps_tasks)} task(s) not yet demonstrated an equivalent of")
            if pg.gaps_context_only:
                parts.append(f"{len(pg.gaps_context_only)} task(s) demonstrated in the wrong context")
            if pg.gaps_requirements:
                req_list = ", ".join(r.value for r in pg.gaps_requirements)
                parts.append(f"{len(pg.gaps_requirements)} requirement(s) remaining ({req_list})")
            lines.append("  Remaining: " + "; ".join(parts))
        satisfied_reqs = [r for r in pg.satisfied_requirements if r.derivation != "direct"]
        if satisfied_reqs:
            waived = ", ".join(f"{r.value} ({r.derivation} {r.derivation_position})" for r in satisfied_reqs)
            lines.append(f"  Already satisfied via qualification chain: {waived}")
        lines.append("")
    return "\n".join(lines)


def _parse_completed_task(spec: str) -> CompletedTask:
    position_task_id_str, _, context = spec.partition(":")
    return CompletedTask(position_task_id=int(position_task_id_str), context=context or "other")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PTB gap analysis CLI demo")
    parser.add_argument("--qual", action="append", default=[], help="held position code, e.g. ENGB (repeatable)")
    parser.add_argument("--course", action="append", default=[], help="completed course code, e.g. S-230 (repeatable)")
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="completed position_task_id:context, e.g. 12:wildfire (repeatable)",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of the text report")
    args = parser.parse_args(argv)

    profile = CandidateProfile(
        held_qualifications=args.qual,
        completed_courses=args.course,
        completed_task_ids=[_parse_completed_task(t) for t in args.task],
    )

    results = closest_positions(profile, limit=args.limit)

    if args.json:
        print(json.dumps([_position_gap_to_dict(pg) for pg in results], indent=2))
    else:
        print(format_report(profile, results, limit=args.limit))


def _position_gap_to_dict(pg: PositionGap) -> dict:
    import dataclasses

    return dataclasses.asdict(pg)


if __name__ == "__main__":
    main()
