"""Structuring for nwcg_nextgen Position Task Books.

The Next Gen "position evaluation table" is a 3-column form (task number,
task text, evaluation-context code) plus a 4-column blank rating grid that is
pure furniture. pdfplumber's plain-text extraction interleaves these columns
in an order that varies task to task (see extraction.spec.md's pitfall #1),
so this parser works from word bounding boxes instead of line order: each
word's x-position places it in the number/text/code column, and each column
word is assigned to the task whose printed number-anchor is vertically
closest to it. That survives the code/number marker landing before, in the
middle of, or after its own task's wrapped text.
"""

from __future__ import annotations

import re
from collections import Counter

CODE_TOKEN_RE = re.compile(r"^(I|W|RX|R|S|O|ALL)(/(I|W|RX|R|S|O|ALL))*$")


def split_code_alternatives(code_raw: str) -> list[str]:
    """'W/RX' -> ['W', 'RX']; 'I, S' -> ['I', 'S'] (both separators occur in
    print; the parsed list is what matching/gap logic consumes)."""
    return [a for a in re.split(r"[/,]\s*", code_raw) if a]
IPS_REFERENCE_RE = re.compile(r"PMS\s*350-(\d+[A-Za-z]?)")


def _cluster_lines(words: list[dict], tolerance: float = 3.0) -> list[list[dict]]:
    """Group words with near-identical 'top' into visual lines, top-to-bottom."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def _find_column_bands(words: list[dict]) -> dict | None:
    """Derive the number/text/code/label column x-ranges from this page's own
    header words, so the parser isn't pinned to one document's exact pixel
    layout."""
    code_headers = [w for w in words if w["text"] == "CODE"]
    if not code_headers:
        return None
    code_x0 = min(w["x0"] for w in code_headers)

    # The "Record Number" grid header always sits right of the CODE header;
    # a task whose text begins with "Record" (FOBS #9 "Record relevant or
    # appropriate features on a map.", September 2026) must not be mistaken
    # for it, or the code band collapses and the page yields no tasks.
    grid_headers = [w for w in words if w["text"] in ("Record", "Number") and w["x0"] > code_x0]
    grid_x0 = min((w["x0"] for w in grid_headers), default=code_x0 + 60)

    # Body text words: left of the code column, excluding digit-only tokens
    # (those are task numbers, a narrower column further left) and excluding
    # the "Position"/"Evaluation" repeating label (its own column, right of
    # the grid start in this template).
    candidates = [w for w in words if w["x0"] < code_x0 - 15 and not w["text"].strip().isdigit()]
    if not candidates:
        return None
    # Mode, not min: the table's body-text column is overwhelmingly the most
    # common left edge; a stray checkbox/instruction line elsewhere on the
    # page can sit further left and would skew a min() estimate.
    text_left = Counter(round(w["x0"]) for w in candidates).most_common(1)[0][0]

    return {
        "number": (0.0, text_left - 8),
        "text": (text_left - 8, code_x0 - 12),
        "code": (code_x0 - 20, grid_x0 - 10),
        "grid": (grid_x0 - 30, grid_x0 + 400),  # blank "1 2 3 4" rating columns
    }


def _in(x0: float, band: tuple[float, float]) -> bool:
    return band[0] <= x0 < band[1]


def _row_edges(page, min_length: float = 200.0, merge_tolerance: float = 3.0) -> list[float]:
    """Y positions of the position-evaluation table's horizontal rulings
    (long edges only; the double-stroked borders a few tenths of a point
    apart are merged), sorted top to bottom. Empty when the page has none."""
    tops = sorted(e["top"] for e in page.horizontal_edges if e["x1"] - e["x0"] >= min_length)
    merged: list[float] = []
    for t in tops:
        if merged and t - merged[-1] <= merge_tolerance:
            continue
        merged.append(t)
    return merged


def _row_index(row_edges: list[float], top: float) -> int | None:
    """Index of the ruling-bounded row containing a word/line top (None when
    the page has no rulings or the top lies outside the ruled table)."""
    if len(row_edges) < 2 or top < row_edges[0] or top >= row_edges[-1]:
        return None
    lo, hi = 0, len(row_edges) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if row_edges[mid] <= top:
            lo = mid
        else:
            hi = mid
    return lo


def _drop_bracketed(lines: list[list[dict]]) -> list[list[dict]]:
    """Remove '[See the NWCG Incident Position Standards ...]' reference notes.
    Narrowly triggered on the "[See" opener specifically — task text can
    contain ordinary inline brackets too (e.g. an abbreviation like
    "Potential Operational Delineations [PODS],"), and those must not start
    a multi-line drop that swallows every task after them."""
    out = []
    in_brackets = False
    for line in lines:
        text = " ".join(w["text"] for w in line)
        if not in_brackets and re.match(r"^\[See\b", text.lstrip(), re.IGNORECASE):
            in_brackets = True
        if not in_brackets:
            out.append(line)
        if in_brackets and "]" in text:
            in_brackets = False
    return out


def parse_page(page, page_number: int) -> list[dict]:
    """Parse one page of a Next Gen position evaluation table.
    Returns a list of raw task dicts: {task_number, verbatim_text, code_raw, page}.
    Category name is attached separately by the caller (it can span page
    breaks and this function only sees one page at a time)... actually category
    headers never span pages in the fixtures, so category is resolved here too,
    returned as {category, task_number, verbatim_text, code_raw, page}.
    """
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    # Drop the repeating page footer ("NWCG Position Task Book for ... N of M"),
    # which otherwise gets swept into whichever task is vertically nearest —
    # always the page's last one.
    words = [w for w in words if w["top"] < 730]
    bands = _find_column_bands(words)
    if bands is None:
        return []
    row_edges = _row_edges(page)

    # The repeating "Position Evaluation" column label sits in its own
    # right-hand furniture column (outside the body-text band), never mixed
    # with task text there — even on the layouts where a long category name
    # wraps onto the very same visual row as the label (e.g. "Perform
    # Helicopter Crewmember-Specific | Position Evaluation" sharing one row),
    # so this can't require the label to be alone on its line the way a
    # simpler "exact 2-word line" check would. "Position"/"Evaluation" can
    # also occur inside ordinary task text (e.g. "Global Position System"),
    # but that always renders in the body-text column, which this excludes.
    label_words = [w for w in words if w["text"] in ("Position", "Evaluation") and not _in(w["x0"], bands["text"])]
    label_lines = _cluster_lines(label_words)
    block_starts = sorted(
        {line[0]["top"] for line in label_lines if {w["text"] for w in line} == {"Position", "Evaluation"}}
    )
    if not block_starts:
        return []
    block_starts.append(float("inf"))

    results = []
    for i in range(len(block_starts) - 1):
        top0, top1 = block_starts[i], block_starts[i + 1]
        block_words = [w for w in words if top0 - 1 <= w["top"] < top1 - 1]

        number_words = [
            w for w in block_words if _in(w["x0"], bands["number"]) and w["text"].strip().rstrip(".").isdigit()
        ]
        text_words = [w for w in block_words if _in(w["x0"], bands["text"])]
        grid_words = [w for w in block_words if _in(w["x0"], bands["grid"])]

        anchors = sorted({int(w["text"].rstrip(".")): w["top"] for w in number_words}.items())
        if not anchors:
            continue

        # The blank "1 2 3 4" rating-column header row marks the boundary
        # between the (possibly multi-line, possibly wrapped onto this same
        # row) category name above it and real task content below it. Its
        # own digits can also land inside the (generously widened) code
        # x-band on some documents, so this row's exact 'top' must be
        # excluded from code-word candidates below, not just used as the
        # category/task split point.
        grid_digit_tops = {round(w["top"], 1) for w in grid_words if w["text"] in ("1", "2", "3", "4")}
        boundary_top = min(grid_digit_tops) if grid_digit_tops else anchors[0][1] - 30

        # A font-encoding bug in a handful of source PDFs maps the code
        # column's capital "I" glyph to the digit "1" in the extracted text
        # (confirmed by position: it only ever appears alone, in the code
        # column, never alongside the other rating-grid digits at that same
        # row) — safe to normalize once the grid header row itself is excluded.
        code_words = [
            {**w, "text": "I"} if w["text"] == "1" else w
            for w in block_words
            if _in(w["x0"], bands["code"]) and round(w["top"], 1) not in grid_digit_tops
        ]
        # Codes print as "W/RX" (one token, or "W/" + "RX" across two lines)
        # and, in a few books, as a comma list "I, S" / "I, W, RX" (INCM,
        # ABRO, RADO): the comma-bearing tokens must be kept, not dropped.
        code_words = [w for w in code_words if w["text"] != "CODE" and re.match(r"^[A-Z/,]+$", w["text"])]

        text_lines = _drop_bracketed(_cluster_lines(text_words))
        category_lines = [line for line in text_lines if line[0]["top"] <= boundary_top + 1]
        category = " ".join(w["text"] for line in category_lines for w in line)
        category = re.sub(r"\s+", " ", category).strip()

        def nearest_anchor(top: float) -> int:
            return min(anchors, key=lambda a: abs(a[1] - top))[0]

        # A task's number and code are vertically centred in their table
        # row, so for a long wrapped task the row's last text line can sit
        # closer to the NEXT task's number than to its own (GISS #59, five
        # lines, September 2026 — its tail landed on #60). The table's own
        # horizontal rulings define the rows exactly: a line belongs to the
        # anchor that shares its row; nearest-anchor is only the fallback for
        # pages without usable rulings.
        anchor_row = {n: _row_index(row_edges, top) for n, top in anchors}
        anchor_by_row = {r: n for n, r in anchor_row.items() if r is not None}

        def owning_anchor(top: float) -> int:
            r = _row_index(row_edges, top)
            if r is not None and r in anchor_by_row:
                return anchor_by_row[r]
            return nearest_anchor(top)

        tasks_by_num: dict[int, dict] = {n: {"text_words": [], "code_words": []} for n, _ in anchors}
        for line in text_lines:
            line_top = line[0]["top"]
            if line_top <= boundary_top + 1:
                continue  # category name, already consumed
            n = owning_anchor(line_top)
            tasks_by_num[n]["text_words"].extend(line)
        for w in code_words:
            n = owning_anchor(w["top"])
            tasks_by_num[n]["code_words"].append(w)

        for n, _ in anchors:
            bucket = tasks_by_num[n]
            lines = _cluster_lines(bucket["text_words"])
            verbatim = " ".join(" ".join(w["text"] for w in line) for line in lines)
            verbatim = re.sub(r"\s+", " ", verbatim).strip()
            code_tokens = [w["text"] for w in sorted(bucket["code_words"], key=lambda w: (w["top"], w["x0"]))]
            # Preserve the printed form: slash-joined pieces glue together
            # ("W/" + "RX" -> "W/RX"); comma-separated pieces keep a space
            # ("I," + "S" -> "I, S").
            code_raw = "".join(t + (" " if t.endswith(",") else "") for t in code_tokens).strip()
            if not verbatim or not code_raw:
                continue
            results.append(
                {
                    "category": category,
                    "task_number": n,
                    "verbatim_text": verbatim,
                    "code_raw": code_raw,
                    "page": page_number,
                }
            )
    return results


def structure_nextgen(pdf, position_codes: list[str]) -> tuple[list[dict], str | None]:
    """Parse a whole Next Gen PTB. Returns (tasks, ips_reference).
    tasks are attributed to every position_code the document covers (Next Gen
    multi-position PTBs share a single task table across their codes).
    """
    full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = IPS_REFERENCE_RE.search(full_text)
    ips_reference = f"350-{m.group(1)}" if m else None

    raw_tasks: list[dict] = []
    for i, page in enumerate(pdf.pages, start=1):
        raw_tasks.extend(parse_page(page, i))

    tasks = []
    for code in position_codes:
        for t in raw_tasks:
            code_alts = split_code_alternatives(t["code_raw"])
            tasks.append(
                {
                    "position_code": code,
                    "task_number": t["task_number"],
                    "category": t["category"],
                    "behavior": None,
                    "level": None,
                    "verbatim_text": t["verbatim_text"],
                    "code_raw": t["code_raw"],
                    "code_alternatives": code_alts,
                    "clarifications": [],
                    "page": t["page"],
                }
            )
    return tasks, ips_reference
