"""Context features for tier-2 pair narrowing (the SME-derived context rule).

Motivated by SME review feedback (2026-07-12, first 51 checklist rows): pairs
whose wording matches but whose CONTEXT differs — different functional domain
(aviation vs ground crew), different behavior-category framing (doing vs
overseeing), different role altitude (chief vs technician), or different
cognitive demand (Bloom's level) — merit skepticism regardless of wording
similarity.

Features computed per candidate pair (both sides' occurrences considered):
  cross_domain      - the two sides share no functional family
  altitude_disjoint - one side is entirely chief/leader level, the other
                      entirely a different level
  category_disjoint - the two sides' task-book category families share nothing
                      (the SME's dominant "Unlikely" signal: e.g. filed under
                      "Gather, analyze, validate" vs "Ensure information is
                      exchanged")
  bloom_gap         - |Bloom level A - Bloom level B| from data/blooms.json

The narrowing rule (see matching.spec.md changelog 2026-07-12), calibrated
against the SME's first 51 labeled rows: a probable pair is demoted to
related_not_equivalent when its CATEGORY FRAMING is disjoint (variant tested
at 1 false alarm on her 41 confirms while catching 5 of her 6 "Unlikely"
rows; broader variants mis-flagged 6/41 confirms and were rejected).
SME-confirmed pairs are never demoted. Pairs that survive but carry a
cross-domain AND altitude-disjoint role signal (her 6th "Unlikely" pattern)
are tiered "Check context first" on the regenerated review sheet rather than
auto-demoted.

CLI:
  py src/ptb/context.py            # report counts, change nothing
  py src/ptb/context.py --apply    # demote rule-flagged pairs in
                                   # data/adjudications.json (then rerun
                                   # py src/ptb/adjudicate.py)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[2]

DOMAIN_RULES = [
    ("aviation",  r"helicopter|helibase|aircraft|airtanker|aerial|air (tactical|support|operations)|aviation|unmanned|uas|fixed[- ]wing|ramp|deck coordinator|mixmaster|retardant|flight|loadmaster"),
    ("dispatch",  r"dispatch"),
    ("finance",   r"finance|time unit|cost unit|compensation|procurement|equipment time|personnel time|incident business|buying"),
    ("logistics", r"logistics|facilit(y|ies)|food unit|ground support|supply|base camp|camp manager|equipment manager|ordering|receiving|distribution|security manager|communications unit|incident communications|radio operator|medical unit|medical leader"),
    ("planning",  r"planning|situation unit|resources unit|documentation unit|demobilization|field observer|fire effects|geographic information|gis|training specialist|long term analyst|fire behavior"),
    ("safety",    r"safety officer"),
    ("information", r"public information|information officer|incident information"),
    ("liaison",   r"liaison|agency representative"),
    ("investigation", r"investigat"),
    ("fallers",   r"faller|felling boss"),
    ("rx_firing", r"prescribed fire|burn boss|firing boss|ignition"),
    ("ground_ops", r"firefighter|engine boss|crew boss|division|strike team|task force|operations (section|branch)|crew representative|structure protection|structure defense"),
    ("command",   r"incident commander|area command|complex incident"),
    ("prevention", r"prevention|education"),
]

# Task-book category headers -> behavior families. The SME's "Unlikely" notes
# repeatedly contrasted these framings ("you're gathering and analyzing" vs
# "you're ensuring an exchange happens").
CATEGORY_FAMILIES = [
    ("readiness",     r"ensure readiness|prepare and mobilize|ensure availability|preparedness|ensure individual readiness|travel to and check in"),
    ("build_team",    r"build the team|establish organization|establish effective relationship|assemble and validate readiness of ass"),
    ("lead",          r"lead, supervise|supervise and direct|establish work assignments|supervise effectively|emphasize teamwork|leadership level|manager-specific|leader-specific"),
    ("comm",          r"communicate and coordinate|communicate following|communicate and (ensure|assure)|use effective written|coordinate interdependent"),
    ("info_exchange", r"ensure (all )?relevant information is exchang"),
    ("info_produce",  r"gather, produce,? and distribute|prepare clear and concise|develop appropriate information"),
    ("sa_gather",     r"gather, update, and apply|gather critical information"),
    ("analyze",       r"gather, analyze,? and validate"),
    ("plans",         r"develop and implement plans|planning duties|prescribed fire planning"),
    ("decisions",     r"make appropriate decisions|take appropriate action|modify approach|modify approached"),
    ("risk",          r"manage risk|understand and comply with incident sa|anticipate, recognize|ensure the safety, welfare|follow established procedures and safe"),
    ("compliance",    r"follow established procedures|administer (and/or|/or) apply|ensure compliance with all legal|understand and comply with ics"),
    ("docs",          r"ensure documentation|^document$"),
    ("demob_transfer", r"demobilize|plan for demobilization|transfer position duties"),
    ("specific",      r"specific duties|-specific|perform .{0,40}(duties|responsibilities)|^duties$|implement a prescribed fire|complete individual performance"),
    ("logi_support",  r"provide logistic|ensure functionality of equipment|provide for"),
]


def domains_of_title(title: str) -> set:
    t = title.lower()
    return {d for d, rx in DOMAIN_RULES if re.search(rx, t)} or {"other"}


def altitude_of_title(title: str) -> int:
    t = title.lower()
    if re.search(r"chief|director|area commander|incident commander", t):
        return 3
    if re.search(r"boss|leader|manager|supervisor|commander|coordinator", t):
        return 2
    return 1


def families_of_category(category: str) -> set:
    c = category.lower()
    fams = {f for f, rx in CATEGORY_FAMILIES if re.search(rx, c)}
    return fams or {"other"}


def side_features(side: dict) -> dict:
    domains, alts, fams = set(), set(), set()
    for o in side["occurrences"]:
        domains |= domains_of_title(o["title"])
        alts.add(altitude_of_title(o["title"]))
        fams |= families_of_category(o["category"])
    return {"domains": domains, "altitudes": alts, "families": fams}


def pair_features(cand: dict, blooms_by_text: dict) -> dict:
    a, b = side_features(cand["a"]), side_features(cand["b"])
    la = blooms_by_text.get(cand["a"]["normalized_text"], {}).get("level")
    lb = blooms_by_text.get(cand["b"]["normalized_text"], {}).get("level")
    return {
        "cross_domain": not (a["domains"] & b["domains"]),
        "altitude_disjoint": not (a["altitudes"] & b["altitudes"]),
        "category_disjoint": not (a["families"] & b["families"]),
        "bloom_a": la, "bloom_b": lb,
        "bloom_gap": abs(la - lb) if la and lb else 0,
        "domains_a": sorted(a["domains"]), "domains_b": sorted(b["domains"]),
        "families_a": sorted(a["families"]), "families_b": sorted(b["families"]),
    }


def flagged_by_context_rule(f: dict) -> bool:
    """The 2026-07-12 context rule (matching.spec.md changelog): disjoint
    category framing alone, the SME's dominant and best-calibrated signal."""
    return f["category_disjoint"]


def scrutiny_flag(f: dict) -> bool:
    """Not demoted, but reviewed skeptically: role context differs on two
    independent axes, or the cognitive demand differs by 2+ Bloom levels."""
    return (f["cross_domain"] and f["altitude_disjoint"]) or f["bloom_gap"] >= 2


def load_inputs():
    from ptb import adjudicate, db, match  # noqa: PLC0415

    cands = {c["pair_key"]: c for c in adjudicate.load_candidates()["candidates"]}
    blooms = {o["normalized_text"]: o
              for o in json.load(open(REPO_ROOT / "data" / "blooms.json", encoding="utf-8"))["objectives"]}
    conn = db.connect()
    try:
        probable = conn.execute(
            "SELECT * FROM task_equivalences WHERE status='probable'").fetchall()
        by_ids = {(c["a"]["task_id"], c["b"]["task_id"]): k for k, c in cands.items()}
        keys = [by_ids[(r["task_a_id"], r["task_b_id"])] for r in probable]
    finally:
        conn.close()
    return cands, blooms, keys


DEMOTE_NOTE = (
    "Demoted by the context rule (matching.spec.md changelog 2026-07-12, SME-calibrated): the two "
    "sides' task-book category framings share no behavior family ({fam_a} vs {fam_b}) - the same "
    "wording performed in a materially different behavioral context (doing vs overseeing vs "
    "deciding) is not treated as the same demonstrated work; doubt resolves against equivalence "
    "(rubric rules 2, 5). Kept for audit; resurrect by editing this verdict and rerunning "
    "adjudicate if the SME's full review ever contradicts it."
)

# Explicit SME "Unlikely" rows (2026-07-12 sheet) not caught by the codified
# rule: demoted on her direct judgment.
SME_UNLIKELY_DEMOTIONS = {
    "b619e0ac8477504d": (
        "Demoted on explicit SME judgment (review sheet 2026-07-12): same wording, but a Helibase "
        "Manager's functional-area briefing/AAR context differs materially from a Training "
        "Specialist's; role context governs over wording (rubric rules 2, 5)."),
}


def apply_rule(protected_keys: set, dry_run: bool = True) -> dict:
    cands, blooms, probable_keys = load_inputs()
    demote = []
    for k in probable_keys:
        if k in protected_keys:
            continue
        f = pair_features(cands[k], blooms)
        if flagged_by_context_rule(f):
            demote.append((k, DEMOTE_NOTE.format(
                fam_a="/".join(f["families_a"]), fam_b="/".join(f["families_b"]))))
        elif k in SME_UNLIKELY_DEMOTIONS:
            demote.append((k, SME_UNLIKELY_DEMOTIONS[k]))

    if not dry_run:
        adj_path = REPO_ROOT / "data" / "adjudications.json"
        data = json.load(open(adj_path, encoding="utf-8"))
        by_key = {e["pair_key"]: e for e in data["adjudications"]}
        for k, note in demote:
            e = by_key[k]
            e["relation"] = "related_not_equivalent"
            e.pop("subsumer_normalized_text", None)
            e["note"] = note
        with open(adj_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    return {"probable": len(probable_keys), "flagged_for_demotion": len(demote),
            "protected_sme_confirms": len(protected_keys), "applied": not dry_run}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--protect", default="",
                        help="comma-separated pair_keys never to demote (SME confirms)")
    parser.add_argument("--protect-file", default=None,
                        help="file with one pair_key per line never to demote (e.g. every pair "
                             "already probable before a corpus refresh, so the rule only runs "
                             "over newly adjudicated pairs)")
    args = parser.parse_args()
    protected = {k for k in args.protect.split(",") if k}
    if args.protect_file:
        protected |= {line.strip() for line in open(args.protect_file, encoding="utf-8") if line.strip()}
    print(json.dumps(apply_rule(protected, dry_run=not args.apply), indent=2))
