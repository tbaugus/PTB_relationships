"""Tier-2 candidate generation for task equivalence matching (Phase 4).

Implements the "Tier 2 — semantic candidates" section of
specs/matching.spec.md:

- Tier 1 (identical normalized text -> shared tasks.task_id) is ALREADY done
  at DB-load time by src/ptb/db.py per INV-3. This module never re-does it;
  by construction it only pairs DIFFERENT task_ids, whose normalized texts
  are unique (tasks.normalized_text UNIQUE).
- Tier 2 candidates: embed every distinct task's normalized_text with the
  pinned sentence-transformers model (local CPU) and emit every pair of
  different task_ids with cosine similarity >= CANDIDATE_THRESHOLD.

Reproducibility (AC-M6): the model name AND its exact Hugging Face revision
hash are pinned below, inference runs on CPU in eval mode (deterministic for
fixed weights + fixed input order), scores are rounded to SCORE_DECIMALS, and
candidates are emitted in a deterministic sort order. The output artifact
(data/tier2_candidates.json) contains no timestamps or volatile fields, so
rerunning on an unchanged corpus reproduces it byte-for-byte.

Stability across corpus changes: candidate pairs are keyed by `pair_key`, a
hash of the two NORMALIZED TEXTS (not task ids). Task ids are reassigned
whenever the DB is rebuilt, but normalized texts are stable, so adjudication
verdicts recorded against pair_keys survive corpus additions — only genuinely
NEW pairs ever need adjudication. See src/ptb/adjudicate.py and the
"Re-running the matching pipeline" section of specs/matching.spec.md.

NTFT bridge (F2 ntft-bridge, specs/matching.spec.md "NTFT bridge
candidates"): `--ntft-bridge` keeps the model, normalization and pair_key
scheme but (1) admits only pairs with one official=0 side and one official=1
side (is_bridge_pair), (2) cuts at CANDIDATE_THRESHOLD_NTFT instead of
CANDIDATE_THRESHOLD, (3) excludes any pair_key already in
data/tier2_candidates.json, (4) seeds nothing, and (5) writes
data/ntft_candidates.json with a top-level "bridge": "ntft". The default
path is untouched: without the flag this module behaves exactly as before
and data/tier2_candidates.json stays byte-identical.

CLI:
    py -m ptb.match                     # writes data/tier2_candidates.json
    py -m ptb.match --db path --out path
    py -m ptb.match --ntft-bridge       # writes data/ntft_candidates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb import db  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATES_PATH = REPO_ROOT / "data" / "tier2_candidates.json"
DEFAULT_NTFT_CANDIDATES_PATH = REPO_ROOT / "data" / "ntft_candidates.json"

# ---------------------------------------------------------------------------
# Pinned model identity (specs/matching.spec.md, Tier 2). Changing ANY of
# these invalidates AC-M6 reproducibility against previously generated
# artifacts and requires a matching.spec.md changelog entry.
# ---------------------------------------------------------------------------
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"  # HF commit hash
CANDIDATE_THRESHOLD = 0.80
SCORE_DECIMALS = 6

# NTFT bridge cut (specs/matching.spec.md "NTFT bridge candidates"). Lower
# than the tier-2 cut on purpose: NTFT and NWCG task books are written in
# different registers, so cosine underestimates cross-boundary overlap. The
# honesty gate is unchanged — nothing reaches 'confirmed' without a human.
# Changing this requires a matching.spec.md changelog entry.
CANDIDATE_THRESHOLD_NTFT = 0.60
BRIDGES = ("ntft",)

# ---------------------------------------------------------------------------
# Grounded seed pairs (specs/matching.spec.md, Tier 2 + changelog 2026-07-10):
# rubric-named pairs whose verdicts the spec requires recorded in
# task_equivalences even though their cosine falls below CANDIDATE_THRESHOLD.
# Keyed by NORMALIZED TEXT (stable across DB rebuilds), never task id.
# Grows only alongside a matching.spec.md changelog entry.
# ---------------------------------------------------------------------------
GROUNDED_SEED_PAIRS: list[tuple[str, str, str]] = [
    (
        "act as a lookout",
        "scout line in critical areas and patrol fireline",
        "AC-M3 / rubric rule 1 grounded pair (FFT1#10 vs ENGB#9); cosine 0.244",
    ),
    (
        "supervise and participate in firing operations",
        "effectively lead crew operations: plan, direct, and supervise firing operations",
        "rubric rule 4 firing-operations triple (ENGB#13 vs CRWB#14); cosine 0.651",
    ),
    (
        "monitor and supervise firing operations",
        "effectively lead crew operations: plan, direct, and supervise firing operations",
        "rubric rule 4 firing-operations triple (FIRB#9 vs CRWB#14); cosine 0.549",
    ),
]


def method_string(bridge: str | None = None) -> str:
    """The task_equivalences.method value for tier-2/3 rows (AC-M5, AC-M6).

    Records model + pinned revision + library version + threshold + the
    adjudication contract, so every equivalence row is auditable back to
    exactly how it was produced. For bridge rows the threshold clause reads
    "ntft-bridge; cosine>=<NTFT cut>" so the two layers are distinguishable
    in the table (AC-B7) without a schema change.
    """
    import sentence_transformers

    if bridge is None:
        cut = f"cosine>={CANDIDATE_THRESHOLD:.2f}"
    elif bridge == "ntft":
        cut = f"ntft-bridge; cosine>={CANDIDATE_THRESHOLD_NTFT:.2f}"
    else:
        raise ValueError(f"unknown bridge {bridge!r}; known: {BRIDGES}")
    return (
        f"embedding+adjudication: {MODEL_NAME}@{MODEL_REVISION[:12]} "
        f"(sentence-transformers {sentence_transformers.__version__}), "
        f"{cut}, "
        f"claude rubric per specs/matching.spec.md"
    )


def is_bridge_pair(sides: dict[int, set[int]], task_x: int, task_y: int) -> bool:
    """NTFT bridge side filter: one task has >= 1 official=0 occurrence and
    the other >= 1 official=1 occurrence. `sides` maps task_id -> set of the
    `source_documents.official` flags of the positions it occurs in."""
    fx, fy = sides.get(task_x, set()), sides.get(task_y, set())
    return (0 in fx and 1 in fy) or (0 in fy and 1 in fx)


def _load_official_sides(conn: sqlite3.Connection) -> dict[int, set[int]]:
    sides: dict[int, set[int]] = {}
    for r in conn.execute(
        """
        SELECT DISTINCT pt.task_id, sd.official
        FROM position_tasks pt
        JOIN positions p ON p.id = pt.position_id
        JOIN source_documents sd ON sd.id = p.source_document_id
        """
    ):
        sides.setdefault(r["task_id"], set()).add(r["official"])
    return sides


def pair_key(normalized_a: str, normalized_b: str) -> str:
    """Stable, id-independent key for an unordered pair of normalized texts."""
    lo, hi = sorted((normalized_a, normalized_b))
    return hashlib.sha256(f"{lo}\n{hi}".encode("utf-8")).hexdigest()[:16]


@dataclass
class TaskSide:
    """One task of a candidate pair, with its per-position occurrences."""

    task_id: int
    normalized_text: str
    canonical_text: str
    occurrences: list[dict] = field(default_factory=list)
    # each occurrence: {position, title, task_number, category, verbatim_text, code_raw}


@dataclass
class Candidate:
    pair_key: str
    score: float
    a: TaskSide  # a/b ordered by task_id (a.task_id < b.task_id)
    b: TaskSide
    seed_reason: str | None = None  # set for GROUNDED_SEED_PAIRS entries


def _load_occurrences(conn: sqlite3.Connection) -> dict[int, list[dict]]:
    occurrences: dict[int, list[dict]] = {}
    rows = conn.execute(
        """
        SELECT pt.task_id, p.code AS position, p.title, pt.task_number,
               pt.category, pt.verbatim_text, pt.code_raw
        FROM position_tasks pt
        JOIN positions p ON p.id = pt.position_id
        ORDER BY p.code, pt.task_number
        """
    )
    for r in rows:
        occurrences.setdefault(r["task_id"], []).append(
            {
                "position": r["position"],
                "title": r["title"],
                "task_number": r["task_number"],
                "category": r["category"],
                "verbatim_text": r["verbatim_text"],
                "code_raw": r["code_raw"],
            }
        )
    return occurrences


def load_model():
    """Load the pinned embedding model on CPU."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu")


def generate_candidates(
    conn: sqlite3.Connection,
    model=None,
    bridge: str | None = None,
    exclude_pair_keys: frozenset[str] | set[str] = frozenset(),
) -> list[Candidate]:
    """Embed every distinct task and return all cross-task_id pairs with
    cosine >= CANDIDATE_THRESHOLD, sorted by score desc then (a_id, b_id).

    With bridge="ntft": cut at CANDIDATE_THRESHOLD_NTFT, keep only pairs
    passing is_bridge_pair, drop any pair_key in exclude_pair_keys (the
    tier-2 set, AC-B2), and add no grounded seed pairs.
    """
    import numpy as np

    if bridge is not None and bridge not in BRIDGES:
        raise ValueError(f"unknown bridge {bridge!r}; known: {BRIDGES}")
    threshold = CANDIDATE_THRESHOLD_NTFT if bridge == "ntft" else CANDIDATE_THRESHOLD

    if model is None:
        model = load_model()

    tasks = conn.execute(
        "SELECT id, normalized_text, canonical_text FROM tasks ORDER BY id"
    ).fetchall()
    texts = [t["normalized_text"] for t in tasks]

    embeddings = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)

    sims = embeddings @ embeddings.T
    ai, bi = np.where(np.triu(sims >= threshold, k=1))

    occurrences = _load_occurrences(conn)

    if bridge == "ntft":
        sides = _load_official_sides(conn)
        keep = [
            (i, j) for i, j in zip(ai.tolist(), bi.tolist())
            if is_bridge_pair(sides, tasks[i]["id"], tasks[j]["id"])
            and pair_key(tasks[i]["normalized_text"], tasks[j]["normalized_text"]) not in exclude_pair_keys
        ]
        ai = np.array([i for i, _ in keep], dtype=int)
        bi = np.array([j for _, j in keep], dtype=int)

    def build(i: int, j: int, seed_reason: str | None = None) -> Candidate:
        ta, tb = tasks[i], tasks[j]
        return Candidate(
            pair_key=pair_key(ta["normalized_text"], tb["normalized_text"]),
            score=round(float(sims[i, j]), SCORE_DECIMALS),
            a=TaskSide(ta["id"], ta["normalized_text"], ta["canonical_text"], occurrences.get(ta["id"], [])),
            b=TaskSide(tb["id"], tb["normalized_text"], tb["canonical_text"], occurrences.get(tb["id"], [])),
            seed_reason=seed_reason,
        )

    candidates = [build(i, j) for i, j in zip(ai.tolist(), bi.tolist())]

    if bridge is not None:
        # No grounded seed pairs in a bridge layer (spec: "seeds nothing").
        candidates.sort(key=lambda c: (-c.score, c.a.task_id, c.b.task_id))
        return candidates

    # Grounded seed pairs: always adjudicated regardless of score
    # (specs/matching.spec.md changelog 2026-07-10). A seed whose texts are
    # missing from the corpus is an error — the spec grounds it in real tasks.
    index_by_norm = {t["normalized_text"]: idx for idx, t in enumerate(tasks)}
    surfaced = {c.pair_key for c in candidates}
    for norm_x, norm_y, reason in GROUNDED_SEED_PAIRS:
        if norm_x not in index_by_norm or norm_y not in index_by_norm:
            raise KeyError(
                f"GROUNDED_SEED_PAIRS text not found in tasks table: "
                f"{norm_x if norm_x not in index_by_norm else norm_y!r}"
            )
        if pair_key(norm_x, norm_y) in surfaced:
            continue  # already above threshold; no seeding needed
        i, j = sorted((index_by_norm[norm_x], index_by_norm[norm_y]))
        candidates.append(build(i, j, seed_reason=reason))

    candidates.sort(key=lambda c: (-c.score, c.a.task_id, c.b.task_id))
    return candidates


def candidates_to_json(candidates: list[Candidate], task_count: int, bridge: str | None = None) -> dict:
    """Serializable artifact. Deliberately timestamp-free: byte-stable on
    rerun over an unchanged corpus (AC-M6). A bridge artifact carries the
    same schema plus a top-level "bridge" tag and its own threshold."""
    import sentence_transformers

    return {
        **({"bridge": bridge} if bridge else {}),
        "model": MODEL_NAME,
        "model_revision": MODEL_REVISION,
        "sentence_transformers_version": sentence_transformers.__version__,
        "threshold": CANDIDATE_THRESHOLD_NTFT if bridge == "ntft" else CANDIDATE_THRESHOLD,
        "distinct_tasks": task_count,
        "candidate_count": len(candidates),
        "candidates": [
            {
                "pair_key": c.pair_key,
                "score": c.score,
                "seed_reason": c.seed_reason,
                "a": vars(c.a),
                "b": vars(c.b),
            }
            for c in candidates
        ],
    }


def write_candidates(
    db_path: Path | str = db.DEFAULT_DB_PATH,
    out_path: Path | str | None = None,
    bridge: str | None = None,
    tier2_path: Path | str = DEFAULT_CANDIDATES_PATH,
) -> dict:
    """Default: write the tier-2 artifact. bridge="ntft": write the bridge
    artifact, excluding every pair_key already present in tier2_path
    (AC-B2) and never touching the tier-2 file."""
    if out_path is None:
        out_path = DEFAULT_NTFT_CANDIDATES_PATH if bridge == "ntft" else DEFAULT_CANDIDATES_PATH
    exclude: frozenset[str] = frozenset()
    if bridge == "ntft" and Path(tier2_path).exists():
        with open(tier2_path, encoding="utf-8") as f:
            exclude = frozenset(c["pair_key"] for c in json.load(f)["candidates"])

    conn = db.connect(db_path)
    try:
        candidates = generate_candidates(conn, bridge=bridge, exclude_pair_keys=exclude)
        task_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        conn.close()
    payload = candidates_to_json(candidates, task_count, bridge=bridge)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
        f.write("\n")
    result = {"distinct_tasks": task_count, "candidates": len(candidates), "out": str(out_path)}
    if bridge:
        result["bridge"] = bridge
        result["threshold"] = payload["threshold"]
        result["excluded_tier2_pair_keys"] = len(exclude)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate tier-2 equivalence candidates (Phase 4).")
    parser.add_argument("--db", default=str(db.DEFAULT_DB_PATH))
    parser.add_argument("--out", default=None,
                        help="defaults to data/tier2_candidates.json, or data/ntft_candidates.json with --ntft-bridge")
    parser.add_argument("--ntft-bridge", action="store_true",
                        help="generate the NTFT bridge layer instead (specs/matching.spec.md 'NTFT bridge candidates')")
    args = parser.parse_args()
    print(json.dumps(write_candidates(args.db, args.out, bridge="ntft" if args.ntft_bridge else None), indent=2))
