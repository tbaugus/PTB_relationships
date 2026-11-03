"""Acquisition + structuring for per-position qualification requirements
(PMS 310-1), addressing the Phase 1 acquisition gap noted in
specs/acquisition.spec.md's `pending` entry: PMS 310-1 is published as a
paginated web document, not a single downloadable PDF, so this data has no
equivalent to the PTB catalog's PDF-download path.

Source: the NWCG Position Catalog (nwcg.gov/positions/position-catalog)
lists every position with a link to its own detail page; each detail page
has a sibling "<slug>/qualification-requirements" page holding the actual
PMS 310-1 elements for that position (required training, required
experience, physical fitness level, currency relationships, other
training). This script:

1. Scrapes the Position Catalog table for (code, title, slug).
2. Fetches each position's qualification-requirements page and saves the
   raw HTML to corpus/raw/requirements/<CODE>.html with a manifest entry
   (role: "qualification_standard", pms_number: "310-1").
3. Parses the structured sections into extracted/requirements/<CODE>.json,
   ready for Phase 3 to load into position_requirements.

Idempotence note: unlike the PDF sources in acquire.py, these pages embed
page-wide dynamic content unrelated to the requirements data itself (a
"NWCG Latest Announcements" widget with rotating images/links) — so the raw
HTML's sha256 changes on essentially every fetch and cannot be used to skip
re-downloading. Every run therefore rewrites every raw HTML file and manifest
entry (no `superseded` history is kept for these, since "changed" is not a
meaningful signal here). What *is* stable across runs, and is the property
that actually matters for Phase 3, is the structured JSON output: it's
parsed only from the "Qualification Requirements" section, and reruns
produce byte-identical extracted/requirements/*.json files.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ptb.acquire import (  # noqa: E402
    MANIFEST_PATH,
    REPO_ROOT,
    looks_like_html,
    polite_get,
    sha256_bytes,
)

CATALOG_URL = "https://www.nwcg.gov/positions/position-catalog"
RAW_DIR = REPO_ROOT / "corpus" / "raw" / "requirements"
OUT_DIR = REPO_ROOT / "extracted" / "requirements"

PREREQ_POSITION_RE = re.compile(r"\b([A-Z]{2,6}\d?)\s*\)")


def fetch_position_catalog() -> list[dict]:
    resp = polite_get(CATALOG_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    entries = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        title_link = cells[1].find("a")
        if title_link is None:
            continue
        code = cells[2].get_text(strip=True)
        entries.append(
            {
                "code": code,
                "title": title_link.get_text(strip=True),
                "slug": title_link["href"],
                "functional_area": cells[3].get_text(strip=True) if len(cells) > 3 else None,
            }
        )
    return entries


def _list_items(heading) -> list[str]:
    """Text of each <li> in the first list following a heading, or the
    heading's own trailing text if there's no list (e.g. 'None')."""
    sib = heading.find_next_sibling()
    while sib is not None and sib.name not in ("h2", "h3", "ul", "p"):
        sib = sib.find_next_sibling()
    if sib is None or sib.name in ("h2", "h3"):
        return []
    if sib.name == "ul":
        return [li.get_text(" ", strip=True) for li in sib.find_all("li") if li.get_text(strip=True)]
    text = sib.get_text(" ", strip=True)
    return [text] if text else []


def extract_prereq_codes(text: str) -> list[str]:
    """Pull position codes out of parenthetical mentions like
    'Intermediate Faller ( FAL2 )' — best-effort, used only as a hint
    alongside the raw text, never a replacement for it."""
    return sorted(set(PREREQ_POSITION_RE.findall(text.replace("(", "( "))))


def structure_requirements_page(html: bytes, code: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h2", string=lambda s: s and "Qualification Requirements" in s)
    if heading is None:
        return {
            "position_code": code,
            "required_training": [],
            "required_experience": [],
            "physical_fitness": None,
            "currency_maintained_by": [],
            "maintains_currency_for": [],
            "other_training": [],
            "note": None,
        }

    sections: dict[str, list[str]] = {}
    for h3 in heading.find_all_next("h3"):
        # stop once we've left the qualification-requirements block (the
        # page moves on to "Position Endorsement" / feedback-form furniture)
        prior_h2 = h3.find_previous_sibling("h2") or h3.find_previous("h2")
        if prior_h2 is not heading:
            break
        sections[h3.get_text(strip=True)] = _list_items(h3)

    required_experience = sections.get("Required Experience", [])
    # the fitness heading's own text carries the level (e.g. "Physical
    # Fitness Level: Arduous"); re-find it directly since its key varies.
    fitness_heading = heading.find_next(
        lambda tag: tag.name == "h3" and tag.get_text(strip=True).startswith("Physical Fitness Level")
    )
    physical_fitness = fitness_heading.get_text(strip=True) if fitness_heading else None

    note_heading = heading.find_next("h3", string="Note")
    note = None
    if note_heading is not None:
        nxt = note_heading.find_next_sibling()
        if nxt is not None:
            note = nxt.get_text(" ", strip=True) or None

    def _clean(items: list[str]) -> list[str]:
        # "None" is the site's placeholder text for an empty section.
        return [] if items == ["None"] else items

    prereq_codes = sorted({c for text in required_experience for c in extract_prereq_codes(text)} - {code})

    return {
        "position_code": code,
        "required_training": _clean(sections.get("Required Training", [])),
        "required_experience": required_experience,
        "required_experience_prereq_codes": prereq_codes,
        "physical_fitness": physical_fitness,
        "currency_maintained_by": _clean(sections.get(f"These Positions Maintain Currency For {code}", [])),
        "maintains_currency_for": _clean(sections.get(f"{code} Maintains Currency For These Positions", [])),
        "other_training": _clean(sections.get("Other Training Which Supports Development Of Knowledge And Skills", [])),
        "note": note,
    }


def acquire_one(entry: dict, existing_by_code: dict) -> tuple[dict | None, dict | None]:
    """Returns (manifest_entry, structured_json) or (None, None) on failure."""
    code = entry["code"]
    url = f"https://www.nwcg.gov{entry['slug']}/qualification-requirements"
    try:
        resp = polite_get(url)
    except Exception as exc:  # noqa: BLE001
        return {"pms_number": "310-1", "role": "qualification_standard", "position_codes": [code], "pending_reason": str(exc)}, None

    data = resp.content
    if not data or not looks_like_html(data):
        return (
            {
                "pms_number": "310-1",
                "role": "qualification_standard",
                "position_codes": [code],
                "pending_reason": "response is not HTML (magic-byte check failed)",
            },
            None,
        )

    new_hash = sha256_bytes(data)
    dest = RAW_DIR / f"{code}.html"
    prior = existing_by_code.get(code)
    if prior is not None and prior.get("sha256") == new_hash and dest.exists():
        manifest_entry = prior
    else:
        dest.write_bytes(data)
        manifest_entry = {
            "filename": f"requirements/{code}.html",
            "position_codes": [code],
            "title": f"{entry['title']} — Qualification Requirements",
            "pms_number": "310-1",
            "format": "unclassified",
            "url": url,
            "sha256": new_hash,
            "downloaded_at": date.today().isoformat(),
            "role": "qualification_standard",
            "fixture": False,
        }
    # These web pages publish no edition date (specs/acquisition.spec.md
    # "Corpus refresh"): recorded explicitly as none, never guessed.
    manifest_entry = {**manifest_entry, "edition_date": None, "edition_date_source": "none"}

    structured = structure_requirements_page(data, code)
    return manifest_entry, structured


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    existing_by_code = {
        d["position_codes"][0]: d
        for d in manifest["documents"]
        if d.get("role") == "qualification_standard" and d.get("pms_number") == "310-1" and d.get("position_codes")
    }

    print("Fetching NWCG Position Catalog...", file=sys.stderr)
    catalog = fetch_position_catalog()
    print(f"  {len(catalog)} positions found", file=sys.stderr)

    # Only this script's own per-position pages are replaced; acquire.py's
    # PMS 310-1 PDF entry (same role and PMS number, filename pms310-1.pdf)
    # is carried through untouched.
    other_documents = [d for d in manifest["documents"] if not d["filename"].startswith("requirements/")]
    new_entries = []
    # Drop any prior PMS 310-1 pending note — including acquire.py's original
    # "no single PDF found" entry — since this script is precisely the
    # web-scrape acquisition path that note said was still needed.
    pending = [p for p in manifest.get("pending", []) if p.get("pms_number") != "310-1"]

    ok, failed = 0, 0
    for entry in catalog:
        manifest_entry, structured = acquire_one(entry, existing_by_code)
        if manifest_entry and "pending_reason" in manifest_entry:
            pending.append(manifest_entry)
            failed += 1
            continue
        new_entries.append(manifest_entry)
        (OUT_DIR / f"{entry['code']}.json").write_text(json.dumps(structured, indent=2), encoding="utf-8")
        ok += 1

    manifest["documents"] = other_documents + new_entries
    manifest["pending"] = pending
    manifest["generated"] = date.today().isoformat()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Requirements pages: {ok} ok, {failed} pending/failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
