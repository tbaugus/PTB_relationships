"""Schema DDL and loader for the PTB relationships database (Phase 3).

Implements the DDL and invariants in specs/schema.spec.md. DDL is restricted
to Postgres-portable SQL; SQLite is the engine for now (see spec header).

The loader reads the Phase 2 output (extracted/<doc>.json, validated against
src.ptb.models.ExtractedDocument) plus the Phase 1 per-position qualification
requirements (extracted/requirements/<code>.json) and corpus/manifest.json
(for url/downloaded_at/role provenance the extraction JSON does not carry),
and populates every table except task_equivalences (Phase 4) and
field_coverage (Phase 6), which are created empty.

Known, documented Phase-3 gaps (not bugs — see PLAN.md's acquisition/Phase-1
notes for why these positions have no task book):
- Seven codes have a qualification-requirements page but no PTB (AREP, EDRC,
  FFT2, IARR, OPS3, PIOT, REAF). `positions` requires a source_document_id,
  so these codes never get a `positions` row and their
  extracted/requirements/<code>.json is not loaded into position_requirements
  in this phase.
- `position_implications` pairs where either endpoint lacks a `positions` row
  (currently: DIVS->OPS3, ICT3->OPS3) are skipped for the same reason.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb.models import ExtractedDocument  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "ptb.sqlite"
EXTRACTED_DIR = REPO_ROOT / "extracted"
REQUIREMENTS_DIR = REPO_ROOT / "extracted" / "requirements"
MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"
CORPUS_RAW_DIR = REPO_ROOT / "corpus" / "raw"

# ---------------------------------------------------------------------------
# DDL — verbatim transcription of specs/schema.spec.md's "Tables" section.
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE source_documents(
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  format TEXT NOT NULL CHECK (format IN ('nwcg_nextgen','nwcg_legacy','enhanced_gdoc')),
  role TEXT NOT NULL DEFAULT 'ptb'
       CHECK (role IN ('ptb','companion_standards','qualification_standard')),
  official INTEGER NOT NULL DEFAULT 1 CHECK (official IN (0,1)),
  pms_number TEXT,
  edition_date TEXT,
  downloaded_at TEXT NOT NULL
);

CREATE TABLE positions(
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  provisional_code INTEGER NOT NULL DEFAULT 0 CHECK (provisional_code IN (0,1)),
  source_document_id INTEGER NOT NULL REFERENCES source_documents(id)
);

CREATE TABLE tasks(
  id INTEGER PRIMARY KEY,
  canonical_text TEXT NOT NULL,
  normalized_text TEXT NOT NULL UNIQUE
);

CREATE TABLE position_tasks(
  id INTEGER PRIMARY KEY,
  position_id INTEGER NOT NULL REFERENCES positions(id),
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  task_number INTEGER NOT NULL,
  category TEXT NOT NULL,
  behavior TEXT,
  level TEXT CHECK (level IN ('Aspirant','Beginner','Journey','Expert') OR level IS NULL),
  verbatim_text TEXT NOT NULL,
  code_raw TEXT NOT NULL,
  code_alternatives TEXT NOT NULL,
  clarifications TEXT NOT NULL DEFAULT '[]',
  page INTEGER NOT NULL,
  UNIQUE (position_id, task_number)
);

CREATE TABLE task_equivalences(
  id INTEGER PRIMARY KEY,
  task_a_id INTEGER NOT NULL REFERENCES tasks(id),
  task_b_id INTEGER NOT NULL REFERENCES tasks(id),
  relation TEXT NOT NULL CHECK (relation IN ('equivalent','a_subsumes_b','b_subsumes_a','related_not_equivalent')),
  tier INTEGER NOT NULL CHECK (tier IN (1,2,3)),
  method TEXT NOT NULL,
  similarity_score REAL,
  adjudication_note TEXT,
  human_reviewed_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('confirmed','probable','rejected')),
  CHECK (task_a_id < task_b_id),
  UNIQUE (task_a_id, task_b_id)
);

CREATE TABLE position_requirements(
  id INTEGER PRIMARY KEY,
  position_id INTEGER NOT NULL REFERENCES positions(id),
  kind TEXT NOT NULL CHECK (kind IN ('course','prerequisite_position',
       'training','experience','fitness','currency','other')),
  value TEXT NOT NULL,
  detail TEXT,
  source TEXT NOT NULL,
  UNIQUE (position_id, kind, value)
);

CREATE TABLE position_implications(
  id INTEGER PRIMARY KEY,
  holding_position_id INTEGER NOT NULL REFERENCES positions(id),
  implied_position_id INTEGER NOT NULL REFERENCES positions(id),
  source TEXT NOT NULL,
  CHECK (holding_position_id <> implied_position_id),
  UNIQUE (holding_position_id, implied_position_id)
);

CREATE TABLE field_coverage(
  id INTEGER PRIMARY KEY,
  format TEXT NOT NULL,
  field_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('captured','absent_from_format','present_but_blank_in_samples')),
  evidence TEXT NOT NULL,
  UNIQUE (format, field_name)
);
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Normalization — specs/matching.spec.md's "Normalization" section, steps 1-5.
# Only what's needed to compute tasks.normalized_text at load time (tier-1
# sharing, INV-3); tiers 2/3 candidate generation is Phase 4's match.py.
# ---------------------------------------------------------------------------

_SMART_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
}

# Step 2: known PDF line-flow mid-word split artifacts. Grows only with
# human sign-off, same discipline as the abbreviation table below.
_MID_WORD_SPLIT_FIXES = {
    "an d": "and",
}

# Step 4: known abbreviation-variant canonicalizations. Starts with exactly
# the (aars)/(aar) pair per matching.spec.md; grows only with human sign-off.
_ABBREVIATION_TABLE = {
    "(aars)": "(aar)",
}

# Step 5: strict bracketed IPS cross-reference pattern.
_IPS_BRACKET_RE = re.compile(
    r"\[see the nwcg incident position standards for [^\]]*?,\s*pms\s*350-\d+[^\]]*?\]",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Compute tasks.normalized_text per specs/matching.spec.md's five steps."""
    # 1. Unicode NFKC; ASCII-fold smart quotes/apostrophes.
    text = unicodedata.normalize("NFKC", text)
    for smart, ascii_ in _SMART_QUOTES.items():
        text = text.replace(smart, ascii_)

    # 2. Collapse whitespace runs; rejoin known mid-word splits.
    text = _WHITESPACE_RE.sub(" ", text).strip()
    for split, fixed in _MID_WORD_SPLIT_FIXES.items():
        text = re.sub(r"\b" + re.escape(split) + r"\b", fixed, text)

    # 3. Lowercase; strip a single trailing period.
    text = text.lower()
    if text.endswith("."):
        text = text[:-1]

    # 4. Canonicalize known abbreviation variants.
    for variant, canonical in _ABBREVIATION_TABLE.items():
        text = text.replace(variant, canonical)

    # 5. Strip strict-pattern bracketed IPS cross-references.
    text = _IPS_BRACKET_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()

    return text


# ---------------------------------------------------------------------------
# position_implications — curated from extracted/requirements/*.json "note"
# fields that explicitly state a grant-of-qualification ("Once qualified as
# X, the Y qualification may be granted...", "...meets the prerequisite
# experience and qualifications of X, the certifying official may grant the
# X qualification"). This is a hand-audited list, not a regex/NLP pass:
# every pair below was read verbatim from the cited file's "note" field.
#
# Explicitly EXCLUDED (source data does NOT state a confers-qualification
# relationship — see PLAN.md's Phase-1 known-gaps note distinguishing
# currency from implication):
# - currency_maintained_by / maintains_currency_for fields on every
#   requirements JSON: these describe recency/currency relationships
#   ("serving in A keeps your B currency alive"), not qualification grants.
#   Loaded into position_requirements(kind='currency') instead, never here.
# - ICT5, SOFF notes explicitly say a position is NOT a prerequisite. (AREP's
#   note is unrelated ["This is not a Command or General Staff position."]
#   and is irrelevant here anyway: AREP has no PTB/positions row, so it is
#   excluded from position_implications regardless of note content — see the
#   module docstring's "no PTB" list.)
# - HMGB, FAL1, FAL2, LSCC, PIOC, PIOT, PSCC notes describe ordering
#   requirements or alternate evaluation pathways, not qualification grants.
# - STCR/STEN/STEQ's own notes ("...will also qualify the individual in
#   that corresponding Strike Team Leader position") name no fixed target
#   code — the mapping from a specific Single Resource Boss position to its
#   "corresponding" Strike Team Leader position is not spelled out in the
#   text, so it is left out rather than guessed. (TFLD's note, by contrast,
#   names concrete source codes (STCR, STEN, STEQ) and a concrete target
#   (Task Force Leader) but is likewise a many-to-one abstraction over which
#   TFLD is "held" the same way regardless of which STL was held — since
#   TFLD requires holding "a" Strike Team Leader qualification rather than a
#   specific one, and PMS 310-1's own text frames it as inherent to holding
#   any STL rather than a distinct per-code implication, it is left out too;
#   revisit in Phase 4 if the gap-analysis rules need it.)
POSITION_IMPLICATIONS: list[tuple[str, str, str]] = [
    ("COST", "FSC3", "COST.json"),
    ("DIVS", "OPS3", "DIVS.json"),
    ("FACL", "LSC3", "FACL.json"),
    ("LTAN", "FBAN", "FBAN.json"),
    ("TIME", "FSC3", "TIME.json"),
    ("ICT3", "OPS3", "ICT3.json"),
    ("ICT3", "PSC3", "ICT3.json"),
    ("ICT3", "LSC3", "ICT3.json"),
    ("ICT3", "FSC3", "ICT3.json"),
    ("GSUL", "LSC3", "GSUL.json"),
    ("SPUL", "LSC3", "SPUL.json"),
    ("SITL", "PSC3", "SITL.json"),
    ("RESL", "PSC3", "RESL.json"),
]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_manifest() -> dict[str, dict]:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)
    return {d["filename"]: d for d in manifest["documents"]}


def _insert_source_document(conn: sqlite3.Connection, doc: ExtractedDocument, manifest_entry: dict) -> int:
    filename = doc.document.filename
    raw_path = CORPUS_RAW_DIR / filename
    if not raw_path.exists():
        raise FileNotFoundError(
            f"source_documents provenance check failed: {raw_path} does not exist "
            f"(INV-1 requires every position_tasks row trace to a file in corpus/raw/)"
        )
    cur = conn.execute(
        """
        INSERT INTO source_documents
            (filename, url, sha256, format, role, official, pms_number, edition_date, downloaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            manifest_entry["url"],
            doc.document.sha256,
            doc.document.format,
            manifest_entry.get("role", "ptb"),
            1 if doc.document.official else 0,
            doc.document.pms_number,
            doc.document.edition_date,
            manifest_entry["downloaded_at"],
        ),
    )
    return cur.lastrowid


def _insert_positions(
    conn: sqlite3.Connection, doc: ExtractedDocument, source_document_id: int, position_id_by_code: dict[str, int]
) -> None:
    for position in doc.positions:
        cur = conn.execute(
            """
            INSERT INTO positions (code, title, provisional_code, source_document_id)
            VALUES (?, ?, ?, ?)
            """,
            (position.code, position.title, 1 if position.provisional_code else 0, source_document_id),
        )
        position_id_by_code[position.code] = cur.lastrowid


def _get_or_create_task_id(conn: sqlite3.Connection, verbatim_text: str, normalized_text_cache: dict[str, int]) -> int:
    normalized = normalize_text(verbatim_text)
    if normalized in normalized_text_cache:
        return normalized_text_cache[normalized]
    row = conn.execute("SELECT id FROM tasks WHERE normalized_text = ?", (normalized,)).fetchone()
    if row is not None:
        normalized_text_cache[normalized] = row["id"]
        return row["id"]
    cur = conn.execute(
        "INSERT INTO tasks (canonical_text, normalized_text) VALUES (?, ?)",
        (verbatim_text, normalized),
    )
    normalized_text_cache[normalized] = cur.lastrowid
    return cur.lastrowid


def _insert_tasks_and_position_tasks(
    conn: sqlite3.Connection,
    doc: ExtractedDocument,
    position_id_by_code: dict[str, int],
    normalized_text_cache: dict[str, int],
) -> None:
    for task in doc.tasks:
        position_id = position_id_by_code[task.position_code]
        task_id = _get_or_create_task_id(conn, task.verbatim_text, normalized_text_cache)
        conn.execute(
            """
            INSERT INTO position_tasks
                (position_id, task_id, task_number, category, behavior, level,
                 verbatim_text, code_raw, code_alternatives, clarifications, page)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id,
                task_id,
                task.task_number,
                task.category,
                task.behavior,
                task.level,
                task.verbatim_text,
                task.code_raw,
                json.dumps(task.code_alternatives),
                json.dumps(task.clarifications),
                task.page,
            ),
        )


def load_ptb_documents(conn: sqlite3.Connection, extracted_dir: Path = EXTRACTED_DIR) -> dict[str, int]:
    """Load source_documents, positions, tasks, position_tasks from extracted/*.json.

    Returns position_id_by_code for use by the requirements/implications loaders.
    """
    manifest = _load_manifest()
    position_id_by_code: dict[str, int] = {}
    normalized_text_cache: dict[str, int] = {}

    doc_files = sorted(p for p in extracted_dir.glob("*.json") if p.is_file())
    for doc_file in doc_files:
        with open(doc_file, encoding="utf-8") as f:
            raw = json.load(f)
        doc = ExtractedDocument.model_validate(raw)

        manifest_entry = manifest.get(doc.document.filename)
        if manifest_entry is None:
            raise KeyError(f"{doc.document.filename} has no corpus/manifest.json entry")

        source_document_id = _insert_source_document(conn, doc, manifest_entry)
        _insert_positions(conn, doc, source_document_id, position_id_by_code)
        _insert_tasks_and_position_tasks(conn, doc, position_id_by_code, normalized_text_cache)

    conn.commit()
    return position_id_by_code


def _parse_course_entry(entry: str) -> tuple[str, str | None]:
    """Split '<CODE>, <title>' or '<CODE>: <title>' into (value, title).

    Falls back to the whole entry as value with no title when neither
    separator is present (e.g. 'Contracting Officer Representative Training').
    """
    for sep in (",", ":"):
        if sep in entry:
            code, _, title = entry.partition(sep)
            return code.strip(), title.strip()
    return entry.strip(), None


_TRAILING_CODES_RE = re.compile(r"^(.*?)\(\s*([^)]+?)\s*\)\s*$")


def _parse_title_and_codes(entry: str) -> tuple[str, list[str]]:
    """Split 'Title ( CODE1 , CODE2 )' into (title, [codes])."""
    match = _TRAILING_CODES_RE.match(entry)
    if not match:
        return entry.strip(), []
    title = match.group(1).strip()
    codes = [c.strip() for c in match.group(2).split(",") if c.strip()]
    return title, codes


def load_position_requirements(
    conn: sqlite3.Connection,
    position_id_by_code: dict[str, int],
    requirements_dir: Path = REQUIREMENTS_DIR,
) -> dict[str, int]:
    """Load extracted/requirements/*.json into position_requirements.

    Codes with no `positions` row (no PTB — see module docstring) are
    skipped; returns a {code: skipped_row_count} map for reporting, not
    raised as an error, since this is a documented, expected gap.
    """
    source = "PMS 310-1 qualification-requirements page"
    skipped: dict[str, int] = {}

    req_files = sorted(requirements_dir.glob("*.json"))
    for req_file in req_files:
        with open(req_file, encoding="utf-8") as f:
            data = json.load(f)
        code = data["position_code"]
        position_id = position_id_by_code.get(code)
        if position_id is None:
            skipped[code] = skipped.get(code, 0) + 1
            continue

        seen: set[tuple[str, str]] = set()

        def _insert(kind: str, value: str, detail: dict[str, Any] | None) -> None:
            key = (kind, value)
            if key in seen:
                return
            seen.add(key)
            conn.execute(
                """
                INSERT INTO position_requirements (position_id, kind, value, detail, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (position_id, kind, value, json.dumps(detail) if detail is not None else None, source),
            )

        for prereq_code in data.get("required_experience_prereq_codes") or []:
            _insert("prerequisite_position", prereq_code, None)

        for entry in data.get("required_experience") or []:
            _insert("experience", entry, None)

        for entry in data.get("required_training") or []:
            value, title = _parse_course_entry(entry)
            _insert("course", value, {"full_text": entry, "title": title} if title else {"full_text": entry})

        for entry in data.get("other_training") or []:
            value, title = _parse_course_entry(entry)
            _insert("training", value, {"full_text": entry, "title": title} if title else {"full_text": entry})

        if data.get("physical_fitness"):
            _insert("fitness", data["physical_fitness"], None)

        for entry in data.get("currency_maintained_by") or []:
            title, codes = _parse_title_and_codes(entry)
            for related_code in codes:
                _insert(
                    "currency",
                    f"currency_maintained_by:{related_code}",
                    {"related_position": related_code, "related_title": title, "direction": "currency_maintained_by"},
                )

        for entry in data.get("maintains_currency_for") or []:
            title, codes = _parse_title_and_codes(entry)
            for related_code in codes:
                _insert(
                    "currency",
                    f"maintains_currency_for:{related_code}",
                    {"related_position": related_code, "related_title": title, "direction": "maintains_currency_for"},
                )

    conn.commit()
    return skipped


def load_position_implications(conn: sqlite3.Connection, position_id_by_code: dict[str, int]) -> list[tuple[str, str]]:
    """Load POSITION_IMPLICATIONS, skipping pairs with a missing endpoint.

    Returns the list of (holding_code, implied_code) pairs skipped, for
    reporting (documented gap — see module docstring and the constant's
    comment for why).
    """
    skipped: list[tuple[str, str]] = []
    for holding_code, implied_code, evidence_file in POSITION_IMPLICATIONS:
        holding_id = position_id_by_code.get(holding_code)
        implied_id = position_id_by_code.get(implied_code)
        if holding_id is None or implied_id is None:
            skipped.append((holding_code, implied_code))
            continue
        conn.execute(
            """
            INSERT INTO position_implications (holding_position_id, implied_position_id, source)
            VALUES (?, ?, ?)
            """,
            (holding_id, implied_id, f"PMS 310-1 qualification-requirements page note ({evidence_file})"),
        )
    conn.commit()
    return skipped


def build_database(
    db_path: Path | str = DEFAULT_DB_PATH,
    extracted_dir: Path = EXTRACTED_DIR,
    requirements_dir: Path = REQUIREMENTS_DIR,
) -> dict[str, Any]:
    """Build a fresh database at db_path, loading the full corpus. Returns load stats."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    try:
        init_schema(conn)
        position_id_by_code = load_ptb_documents(conn, extracted_dir)
        skipped_requirements = load_position_requirements(conn, position_id_by_code, requirements_dir)
        skipped_implications = load_position_implications(conn, position_id_by_code)
        stats = {
            "positions": len(position_id_by_code),
            "source_documents": conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0],
            "tasks": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
            "position_tasks": conn.execute("SELECT COUNT(*) FROM position_tasks").fetchone()[0],
            "position_requirements": conn.execute("SELECT COUNT(*) FROM position_requirements").fetchone()[0],
            "position_implications": conn.execute("SELECT COUNT(*) FROM position_implications").fetchone()[0],
            "skipped_requirements_no_position": skipped_requirements,
            "skipped_implications_missing_endpoint": skipped_implications,
        }
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    result = build_database()
    print(json.dumps(result, indent=2))
