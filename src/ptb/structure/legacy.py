"""Structuring for nwcg_legacy Position Task Books.

Legacy PTBs print tasks as "N. <text> <code>" with sub-bullets underneath
that are explicitly non-evaluated clarifications (spec: "Evaluate the
numbered tasks ONLY. DO NOT evaluate bullets"). The single-letter code sits
in its own column, on the same visual row as the task's opening line, so
(unlike Next Gen) a left-to-right, top-to-bottom line walk with column-aware
classification is enough — no nearest-anchor reconstruction needed.
"""

from __future__ import annotations

import re
from collections import Counter

IPS_REFERENCE_RE = re.compile(r"PMS\s*350-(\d+[A-Za-z]?)")
FOOTER_MARKER = "Evaluate the numbered tasks ONLY"
BULLET_GLYPHS = {"•", "-", "*"}
# A bare uppercase-letters check ("^[A-Z/]+$") also accepts stray all-caps
# furniture that happens to land in the code x-band on some pages (e.g. a
# position abbreviation like "TFLD" in a page title, or "NWCG"); require an
# actual member of the code vocabulary instead.
CODE_VALUE_RE = re.compile(r"^(I|W|RX|R|S|O|ALL)(/(I|W|RX|R|S|O|ALL))*$")
# A task-number token is normally its own word ("25."), but pdfplumber
# occasionally merges it with the next word when the source PDF has no space
# after the period ("25.Ensure...") — match a leading "N." prefix either way.
TASK_NUM_RE = re.compile(r"^(\d+)\.(.*)$")
# A wrapped "Behavior:" heading's continuation line sits one text row
# (~13-14pt) below the previous heading line; the first task's number is a
# blank row further down (30pt+ in every legacy book), so this bound tells
# the two apart.
HEADING_WRAP_GAP = 20.0


def _cluster_lines(words: list[dict], tolerance: float = 3.0) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def _cluster_x0(words: list[dict], tolerance: float = 2.5) -> list[list[dict]]:
    """Group words with near-identical x0 into columns. Sub-pixel rendering
    differences (e.g. 'C' at x0=347.1 vs 'O' at x0=346.4, same visual column)
    can straddle an integer rounding boundary, so exact-round grouping is not
    reliable enough."""
    groups: list[list[dict]] = []
    for w in sorted(words, key=lambda w: w["x0"]):
        if groups and abs(groups[-1][0]["x0"] - w["x0"]) <= tolerance:
            groups[-1].append(w)
        else:
            groups.append([w])
    return groups


def _find_code_column(page_words: list[dict]) -> float | None:
    """Locate the vertically-spelled 'C/O/D/E' header on a single page: one
    letter per row, sharing its x-column with every task's own single-letter
    code value (e.g. 'O' is both the 2nd header letter and a common real
    code), so this must match the exact C,O,D,E *sequence* in row order, not
    just co-occurrence. 'top' is page-relative, so this cannot be done on
    words pooled across pages — the sequence would be scrambled."""
    for group in _cluster_x0(page_words):
        by_top = sorted(group, key=lambda w: w["top"])
        texts = [w["text"] for w in by_top]
        for i in range(len(texts) - 3):
            if texts[i : i + 4] == ["C", "O", "D", "E"]:
                tops = [w["top"] for w in by_top[i : i + 4]]
                if tops[3] - tops[0] < 60:
                    return sum(w["x0"] for w in by_top[i : i + 4]) / 4
    return None


def _find_columns(pages_words: list[list[dict]]) -> dict | None:
    """Derive column x-positions for the whole document: the code column
    from the first page where its distinctive C/O/D/E sequence is found, and
    the margin/text columns as the most common left edges across every page
    (population counts are safe to pool across pages; sequence order is not)."""
    code_x0 = next((x for pw in pages_words for x in [_find_code_column(pw)] if x is not None), None)
    if code_x0 is None:
        return None

    words = [w for pw in pages_words for w in pw]
    margin_candidates = [
        w for w in words if TASK_NUM_RE.match(w["text"]) or w["text"] in ("Behavior:", "Competency:")
    ]
    if not margin_candidates:
        return None
    margin_x0 = Counter(round(w["x0"]) for w in margin_candidates).most_common(1)[0][0]

    # The task's own text column vs. a nested bullet's indent are both
    # "body text left of the code column" and can't be told apart by a
    # simple population mode over every such word — a document with many
    # long bullet lists can have more bullet-indent words than task-text
    # words, which would make the mode pick the wrong column entirely. The
    # task's own text column is unambiguous, though: it's whatever column
    # holds the word immediately following a task-number token on that
    # token's own row.
    text_x0_candidates = []
    for pw in pages_words:
        number_lines: dict[float, float] = {}  # top -> x0 of the task-number token
        for w in pw:
            if abs(w["x0"] - margin_x0) < 9 and TASK_NUM_RE.match(w["text"]):
                number_lines[round(w["top"], 1)] = w["x0"]
        for w in pw:
            top = round(w["top"], 1)
            if top in number_lines and margin_x0 + 5 < w["x0"] < code_x0 - 30:
                text_x0_candidates.append(w)
    if not text_x0_candidates:
        return None
    text_x0 = Counter(round(w["x0"]) for w in text_x0_candidates).most_common(1)[0][0]

    return {"margin": margin_x0, "text": text_x0, "bullet_content": text_x0 + 15, "code": code_x0}


def _find_header_exclusion_bands(words: list[dict]) -> list[tuple[float, float]]:
    """The 'TASK ... CODE ... EVAL. RECORD # ... EVALUATOR:' column header
    repeats not just once per page but again mid-page whenever a new
    Competency/Behavior section starts — every occurrence needs its own
    exclusion band, not just the first."""
    return [(w["top"], w["top"] + 45) for w in words if w["text"] == "TASK"]


def _filtered_page_words(page) -> list[dict]:
    """Words with the repeating page header (title + vertically-spelled
    'CODE' column labels) and footer excluded — used both for the line walk
    and for code-token nearest-anchor assignment, so neither sees the
    header's own literal 'C'/'O'/'D'/'E'/'RECORD' text as a task's code."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    words = [w for w in words if w["top"] < 730]  # drop page-number footer
    bands = _find_header_exclusion_bands(words)
    if bands:
        eps = 0.01  # guard against float noise between near-identical 'top' values
        words = [w for w in words if not any(lo - eps <= w["top"] < hi for lo, hi in bands)]
    return words


def _page_lines(words: list[dict]) -> list[list[dict]]:
    lines = _cluster_lines(words)
    return [line for line in lines if FOOTER_MARKER not in " ".join(w["text"] for w in line)]


def _is_code_token(w: dict, cols: dict) -> bool:
    # Position alone isn't a reliable enough signal (occasional justified/
    # wrapped body text can drift into the code band's x-range on some
    # documents) — a real code token is always short and uppercase-only,
    # never containing a lowercase letter.
    return cols["code"] - 15 <= w["x0"] < cols["code"] + 40 and CODE_VALUE_RE.match(w["text"])


def _assign_codes_by_page(
    page_words: list[dict],
    cols: dict,
    number_anchors: list[tuple[int, float]],
    carry_over_task: int | None = None,
) -> dict[int, str]:
    """A task's code letter is meant to sit on the same row as its number,
    but font-baseline differences of several points are common enough (seen
    across the corpus) that exact line-clustering silently drops the code on
    many tasks. Nearest-anchor-by-top (same technique as the Next Gen parser)
    tolerates that drift without needing them on one exact line.

    A table row can also split exactly at a page break, leaving a task's own
    code cell orphaned at the top of the *next* page with no anchor on that
    page yet to claim it — nearest-anchor would otherwise misattach it to
    that page's first real task. A code word well above this page's first
    number (more than one row's worth of drift) is assigned to
    carry_over_task (the task still open from the previous page) instead;
    a *small* gap is ordinary same-row baseline drift and must still bind
    to this page's own first task, not the carry-over.
    """
    ORPHAN_GAP = 20  # pt; bigger than any observed same-row code/number drift
    code_words = [w for w in page_words if _is_code_token(w, cols)]
    if not code_words:
        return {}
    first_anchor_top = min((top for _, top in number_anchors), default=None)
    by_task: dict[int, list[dict]] = {}
    for w in code_words:
        is_orphaned_above = first_anchor_top is None or first_anchor_top - w["top"] > ORPHAN_GAP
        if carry_over_task is not None and is_orphaned_above:
            n = carry_over_task
        elif number_anchors:
            n = min(number_anchors, key=lambda a: abs(a[1] - w["top"]))[0]
        else:
            continue
        by_task.setdefault(n, []).append(w)
    return {n: "".join(w["text"] for w in sorted(ws, key=lambda w: w["top"])) for n, ws in by_task.items()}


def structure_legacy(pdf, position_code: str) -> tuple[list[dict], str | None]:
    full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = IPS_REFERENCE_RE.search(full_text)
    ips_reference = f"350-{m.group(1)}" if m else None

    # Column x-positions are one fixed template for the whole document;
    # deriving them per-page is fragile on pages that happen to contain only
    # bullet continuations (no fresh "N." task-start line to anchor on).
    pages_words = [p.extract_words(use_text_flow=False, keep_blank_chars=False) for p in pdf.pages]
    cols = _find_columns(pages_words)
    if cols is None:
        return [], ips_reference

    results: list[dict] = []
    code_by_number: dict[int, str] = {}
    current_category = ""
    current: dict | None = None
    in_bullet = False
    # Set while the most recent line was a "Behavior:" heading (or one of
    # its wrapped continuation lines): (heading x0, that line's top).
    heading_tail: tuple[float, float] | None = None

    def close_task():
        nonlocal current
        if current is not None and current["text_words"]:
            results.append(current)
        current = None

    for page_number, page in enumerate(pdf.pages, start=1):
        raw_words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        is_task_table_page = any(w["text"] == "TASK" for w in raw_words) or FOOTER_MARKER in (
            page.extract_text() or ""
        )
        if not is_task_table_page:
            # Record forms, certification/signature pages, and instructions
            # pages have no task-table structure at all; without this check
            # a still-open task (the last one on the previous task-table
            # page) never gets closed and keeps absorbing this boilerplate
            # into its verbatim_text.
            close_task()
            continue

        carry_over_task = current["task_number"] if current is not None else None
        heading_tail = None  # a heading never wraps across a page break
        page_words = _filtered_page_words(page)
        lines = _page_lines(page_words)

        number_anchors = [
            (int(TASK_NUM_RE.match(w["text"]).group(1)), w["top"])
            for line in lines
            for w in line[:1]
            if abs(w["x0"] - cols["margin"]) < 9 and TASK_NUM_RE.match(w["text"])
        ]
        code_by_number.update(_assign_codes_by_page(page_words, cols, number_anchors, carry_over_task))

        for line in lines:
            if not line:
                continue
            x0 = line[0]["x0"]
            text0 = line[0]["text"]
            num_match = TASK_NUM_RE.match(text0) if abs(x0 - cols["margin"]) < 9 else None
            body = [w for w in line if not _is_code_token(w, cols)]

            if num_match:
                close_task()
                number = int(num_match.group(1))
                # pdfplumber sometimes merges "25." with the next word when
                # the source PDF has no space after the period ("25.Ensure");
                # keep that glued remainder as the task's first text word.
                remainder = num_match.group(2)
                opening_words = [{**body[0], "text": remainder}] if remainder else []
                current = {
                    "position_code": position_code,
                    "task_number": number,
                    "category": current_category,
                    "text_words": opening_words + body[1:],
                    "clarifications": [],
                    "page": page_number,
                }
                in_bullet = False
                heading_tail = None
            elif text0 == "Behavior:" and x0 < cols["code"] - 30:
                # A "Behavior:" heading is a section break wherever it is
                # indented: FAL1 page 12 prints its heading at the text
                # column (x0 84 vs margin 72), and with the margin-only test
                # it was read as a continuation of the task still open from
                # page 11 (#20) — or, after a bullet, as bullet text (#22).
                # The open task must close here; the heading's own wrapped
                # continuation lines are not task text (they extend the
                # category instead, next branch).
                close_task()
                current_category = " ".join(w["text"] for w in line[1:])
                in_bullet = False
                heading_tail = (x0, line[0]["top"])
            elif abs(x0 - cols["margin"]) < 9 and text0 in ("Competency:", "Description:"):
                in_bullet = False
                heading_tail = None
            elif (
                heading_tail is not None
                and abs(x0 - heading_tail[0]) < 9
                and x0 < cols["code"] - 30
                and 0 < line[0]["top"] - heading_tail[1] <= HEADING_WRAP_GAP
            ):
                # A long "Behavior:" heading wraps onto one or more further
                # lines printed at the heading's own indent, directly below
                # it and before its first task (LOFR page 7: "Behavior:
                # Ensure availability, qualifications, and capabilities of
                # resources to complete" / "assignment."; FAL1 page 12 the
                # same at the text column). Those lines arrive while no task
                # is open, so without this branch they fell through to the
                # furniture skip and the category kept only the heading's
                # first printed line (extraction.spec.md AC-E10).
                current_category = (current_category + " " + " ".join(w["text"] for w in body)).strip()
                heading_tail = (heading_tail[0], line[0]["top"])
            elif (
                text0 in BULLET_GLYPHS
                and current is not None
                and (abs(x0 - cols["text"]) < 9 or abs(x0 - cols["bullet_content"]) < 9)
            ):
                # Both "•" (top-level) and "-" (nested) bullets are non-evaluated
                # clarifications per spec; keep them as one flat list rather than
                # nesting, since the output contract's clarifications[] is flat.
                current["clarifications"].append(" ".join(w["text"] for w in body[1:]))
                in_bullet = True
            elif (
                in_bullet
                and current is not None
                and current["clarifications"]
                and (abs(x0 - cols["text"]) < 9 or abs(x0 - cols["bullet_content"]) < 9)
            ):
                current["clarifications"][-1] += " " + " ".join(w["text"] for w in body)
            elif abs(x0 - cols["text"]) < 9 and current is not None:
                current["text_words"].extend(body)
                in_bullet = False
            # else: unclassified furniture (page title, etc.) — skip

    close_task()

    tasks = []
    for t in results:
        verbatim = " ".join(w["text"] for w in t["text_words"])
        verbatim = re.sub(r"\s+", " ", verbatim).strip()
        code_raw = code_by_number.get(t["task_number"], "")
        if not verbatim or not code_raw:
            continue
        tasks.append(
            {
                "position_code": t["position_code"],
                "task_number": t["task_number"],
                "category": t["category"],
                "behavior": None,
                "level": None,
                "verbatim_text": verbatim,
                "code_raw": code_raw,
                "code_alternatives": code_raw.split("/"),
                "clarifications": [c.strip() for c in t["clarifications"] if c.strip()],
                "page": t["page"],
            }
        )
    return tasks, ips_reference
