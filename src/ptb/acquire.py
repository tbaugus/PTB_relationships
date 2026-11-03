"""Corpus acquisition for the PTB relationships project (Phase 1).

Scrapes the NWCG Position Task Book catalog, downloads every linked PTB PDF,
follows one level of embedded links to fetch each Next Gen PTB's companion
Incident Position Standards (PMS 350-xxx) and the PMS 310-1 qualification
standard, verifies the enhanced-PTB Google Doc export, and (re)writes
corpus/manifest.json.

Implements specs/acquisition.spec.md. Re-running with nothing changed
remotely writes no new files and leaves the manifest byte-identical except
the top-level `generated` date (AC-A7).

Corpus refresh (specs/acquisition.spec.md "Corpus refresh", 2026-11-02):
documents are matched across runs by (role, PMS number) — never by URL,
because NWCG renamed its S3 keys between editions — and every entry
records `edition_date` / `edition_date_source` / `page_count`. A prior
entry with no live counterpart is moved to the manifest's `retired[]` list
(with `superseded_by`) and its raw file deleted; archived copies are never
substituted. `--verify-urls` checks that every stored URL still resolves.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "corpus" / "raw"
MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"

CATALOG_URL = "https://www.nwcg.gov/training/nwcg-position-task-books-catalog"
GDOC_ID = "1rVGMJR67eftCjEcaoQuYDNBleoM7EOI9"
GDOC_URL_HUMAN = f"https://docs.google.com/document/d/{GDOC_ID}/edit"
GDOC_EXPORTS = {
    "pdf": (f"https://docs.google.com/document/d/{GDOC_ID}/export?format=pdf", "enhanced_ptbs_gdoc.pdf"),
    "docx": (f"https://docs.google.com/document/d/{GDOC_ID}/export?format=docx", "enhanced_ptbs_gdoc.docx"),
}
GDOC_POSITION_CODES = [
    "UAIS", "AIML", "RSEN", "GOPL", "SNTK", "FDSO", "FDMS", "ASOP", "RBFE", "ASWE", "CFMD",
]

PUBLICATION_PAGE = "https://www.nwcg.gov/publications/{slug}"
QUALIFICATION_STANDARD_PMS = "310-1"
PMS_350_RE = re.compile(r"PMS\s*350[\s-]?(\d+[A-Za-z]?)")

USER_AGENT = "PTB-relationships-research/1.0 (contact: tbaugus82@gmail.com)"
REQUEST_TIMEOUT = 30
POLITE_DELAY_SECONDS = 1.0

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


# ---------------------------------------------------------------- helpers --

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def polite_get(url: str) -> requests.Response:
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    time.sleep(POLITE_DELAY_SECONDS)
    resp.raise_for_status()
    return resp


def normalize_pms(pms_number: str) -> str:
    """'311-17' -> 'pms311-17'."""
    return "pms" + pms_number.strip()


def bare_pms(pms_number: str) -> str:
    """'PMS 311-14' or '311-14' -> '311-14', for comparing across manifest
    entries that store pms_number with or without the 'PMS ' prefix."""
    return re.sub(r"^PMS\s*", "", pms_number.strip(), flags=re.IGNORECASE)


def strip_version_id(url: str) -> str:
    """Identify the same underlying S3 object across revisions/re-scrapes,
    regardless of whether its URL currently carries a VersionId."""
    return re.sub(r"([?&])VersionId=[^&]*&?", r"\1", url).rstrip("?&")


def add_version_id_from_headers(url: str, headers: "requests.structures.CaseInsensitiveDict") -> str:
    """S3 returns the object's version in x-amz-version-id; capture it into
    the URL we store so every manifest entry preserves its VersionId (AC-A3),
    even for documents (companion standards, qualification standard) whose
    publication-page link doesn't carry one natively."""
    if "VersionId=" in url:
        return url
    version_id = headers.get("x-amz-version-id")
    if not version_id or version_id == "null":
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}VersionId={version_id}"


def looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def looks_like_docx(data: bytes) -> bool:
    return data[:2] == b"PK"


def looks_like_html(data: bytes) -> bool:
    head = data[:1024].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


# ------------------------------------------------------- edition / currency --

MONTHS = {
    name: i
    for i, name in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"],
        start=1,
    )
}
# "PMS 311-20 October 2018" / "PMS 311-16 SEPTEMBER 2026" — month name is
# case-insensitive (seven legacy books print it in mixed case).
PRINTED_EDITION_RE = re.compile(r"PMS\s*[\d-]+[A-Za-z]?\s+([A-Za-z]+)\s+(\d{4})")
CATALOG_DATE_RE = re.compile(r"^\d{4}-\d{2}$")

# Per-run refresh log: filename -> "unchanged" | "revised" | "new"; retired
# entries are tracked separately in main(). Printed as the refresh summary.
REFRESH_LOG: dict[str, str] = {}


def printed_edition_to_iso(printed: str | None) -> str | None:
    """'SEPTEMBER 2026' / 'October 2018' -> '2026-09' / '2018-10'; None if unparseable."""
    if not printed:
        return None
    parts = printed.strip().split()
    if len(parts) != 2 or parts[0].lower() not in MONTHS or not parts[1].isdigit():
        return None
    return f"{int(parts[1]):04d}-{MONTHS[parts[0].lower()]:02d}"


def scan_printed_edition(pdf_path: Path) -> tuple[str | None, int]:
    """Return (printed 'Month YYYY' from the first page that carries the
    'PMS <n> <Month YYYY>' line, page_count) for a PDF on disk."""
    import pdfplumber

    printed = None
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages[:3]:
            m = PRINTED_EDITION_RE.search(page.extract_text() or "")
            if m and m.group(1).lower() in MONTHS:
                printed = f"{m.group(1)} {m.group(2)}"
                break
    return printed, page_count


def docx_modified_date(docx_path: Path) -> str | None:
    """The DOCX core-properties `modified` timestamp (the only date a Google
    Doc export carries; the document itself prints no edition line)."""
    from docx import Document

    modified = Document(str(docx_path)).core_properties.modified
    return modified.date().isoformat() if modified else None


def annotate_currency(entry: dict, *, catalog_date: str | None = None, docx_date: str | None = None) -> None:
    """Set edition_date / edition_date_source / page_count on a manifest
    entry from the file on disk (deterministic, so AC-A7 idempotence holds).
    Preference order per the spec: catalog "Date Published" for catalog
    PTBs (cross-checked against the printed month, which is also recorded
    as edition_date_printed), the printed page-1 line for other PDFs, the
    DOCX modified date for the Google Doc exports. Never a guess: null when
    no source exists."""
    path = RAW_DIR / entry["filename"]
    printed, page_count = (None, None)
    if entry["filename"].endswith(".pdf") and path.exists():
        printed, page_count = scan_printed_edition(path)
    printed_iso = printed_edition_to_iso(printed)

    entry.pop("edition_date_conflict", None)
    if catalog_date and CATALOG_DATE_RE.match(catalog_date) and printed_iso and printed_iso != catalog_date:
        # The catalog column and the PDF disagree (observed 2026-11-02: EQTR
        # catalog 2016-09 vs printed SEPTEMBER 2024; FELB 2024-07 vs JUNE
        # 2024). The document's own printed edition is what the PDF IS, so it
        # wins; the disagreement is recorded on the entry, never resolved
        # silently (AC-A12).
        entry["edition_date"] = printed_iso
        entry["edition_date_source"] = "pdf page-1 'PMS <n> <Month YYYY>' line (catalog Date Published disagrees)"
        entry["edition_date_conflict"] = {"catalog": catalog_date, "printed": printed}
        print(
            f"  CONFLICT {entry['filename']}: catalog Date Published {catalog_date} != "
            f"printed edition {printed!r} ({printed_iso}); printed value used, conflict recorded",
            file=sys.stderr,
        )
    elif catalog_date and CATALOG_DATE_RE.match(catalog_date):
        entry["edition_date"] = catalog_date
        entry["edition_date_source"] = "catalog Date Published"
    elif printed_iso:
        entry["edition_date"] = printed_iso
        entry["edition_date_source"] = "pdf page-1 'PMS <n> <Month YYYY>' line"
    elif docx_date:
        entry["edition_date"] = docx_date
        entry["edition_date_source"] = "docx core-properties modified (same Google Doc)"
    else:
        entry["edition_date"] = None
        entry["edition_date_source"] = "none"
    if printed is not None:
        entry["edition_date_printed"] = printed
    else:
        entry.pop("edition_date_printed", None)
    if page_count is not None:
        entry["page_count"] = page_count


def identity_of(entry: dict) -> tuple[str, str]:
    """Cross-refresh identity: (role, bare PMS number) for NWCG documents,
    (role, filename) for the Google Doc exports (no PMS number)."""
    role = entry.get("role", "ptb")
    pms = entry.get("pms_number")
    if entry["filename"].startswith("requirements/"):
        # Source-4 pages all carry pms_number 310-1; they are identified by
        # their own filename, never by the PMS number of the PDF they cite.
        return (role, entry["filename"])
    return (role, bare_pms(str(pms))) if pms else (role, entry["filename"])


# ------------------------------------------------------------- manifest io --

def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "generated": None,
        "note": "Regenerated by src/ptb/acquire.py.",
        "sources": {
            "catalog_page": CATALOG_URL,
            "enhanced_gdoc": GDOC_URL_HUMAN,
        },
        "documents": [],
        "pending": [],
        "retired": [],
    }


def save_manifest(manifest: dict) -> None:
    manifest["generated"] = date.today().isoformat()
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ------------------------------------------------------------ catalog scrape --

def fetch_catalog_entries() -> list[dict]:
    """Parse the NWCG PTB catalog table into raw entries with a format hint."""
    resp = polite_get(CATALOG_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    entries = []
    for row in table.find("tbody").find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6:
            continue
        pms_link = cells[0].find("a")
        pms_number = (pms_link.get_text(strip=True) if pms_link else cells[0].get_text(strip=True))
        # dict.fromkeys, not set(): a handful of catalog rows link the same
        # position code twice (e.g. PMS 311-53 PTRC) — dedupe while keeping order.
        position_codes = list(dict.fromkeys(a.get_text(strip=True) for a in cells[1].find_all("a")))
        title_link = cells[2].find("a")
        if title_link is None:
            continue
        title = title_link.get_text(strip=True)
        url = title_link["href"]
        date_published = cells[3].get_text(strip=True)  # "YYYY-MM" (catalog "Date Published" column)
        format_hint = cells[5].get_text(strip=True)  # "Classic" | "Next Gen" -- catalog hint only, not persisted
        entries.append(
            {
                "pms_number": pms_number,
                "position_codes": position_codes,
                "title": title,
                "url": url,
                "date_published": date_published,
                "format_hint": format_hint,
            }
        )
    return entries


# --------------------------------------------------- companion standard lookup --

def resolve_publication_pdf_url(pms_number_norm: str) -> str | None:
    """Given e.g. 'pms350-14', find its download PDF via the NWCG publications page."""
    page_url = PUBLICATION_PAGE.format(slug=pms_number_norm)
    try:
        resp = polite_get(page_url)
    except requests.RequestException:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    # The link must name the publication itself ("pms350-12.pdf",
    # "pms-350-51.pdf"): a publications page can also link unrelated PDFs
    # (nwcg.gov/publications/pms310-1 links a mailing-list flyer, "IPTM SME
    # Duties Spring 2027", as its only PDF — observed 2026-11-02), and
    # recording one of those as the standard would be a false provenance
    # claim.
    slug_re = re.compile(re.escape(pms_number_norm).replace("pms", "pms-?").replace(r"\-", "-?"), re.IGNORECASE)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().split("?")[0].endswith(".pdf") and "/publication/" in href and slug_re.search(href.rsplit("/", 1)[-1]):
            return href
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().split("?")[0].endswith(".pdf") and slug_re.search(href.rsplit("/", 1)[-1]):
            return href
    return None


def find_pms350_references(pdf_path: Path) -> set[str]:
    import pdfplumber

    refs: set[str] = set()
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for m in PMS_350_RE.finditer(text):
                refs.add(f"350-{m.group(1)}")
    return refs


# --------------------------------------------------------------- download --

def download_document(
    manifest: dict,
    existing: dict | None,
    *,
    url: str,
    filename: str,
    pms_number: str | None,
    position_codes: list[str],
    title: str,
    role: str,
    fixture: bool,
    extra: dict | None = None,
) -> dict | None:
    """Download (or reuse cached) content for one manifest entry. Returns the entry or None on failure."""

    def backfilled(entry: dict) -> dict:
        """Fill in any schema fields a legacy/hand-written manifest entry is missing."""
        merged = dict(entry)
        merged.setdefault("role", role)
        # The manifest contract: acquisition writes "unclassified"; format is
        # assigned by extraction (a hand-written 2026-07 fixture entry carried
        # "enhanced_gdoc" here).
        merged["format"] = "unclassified"
        merged.setdefault("fixture", fixture)
        # Always refresh from the live catalog scrape (not setdefault): it's
        # the authoritative source and this is how a prior acquisition bug
        # (e.g. a duplicated position code) gets corrected on rerun.
        merged["position_codes"] = position_codes
        if merged.get("pms_number"):
            merged["pms_number"] = bare_pms(str(merged["pms_number"]))
        if extra:
            for k, v in extra.items():
                merged.setdefault(k, v)
        return merged

    # `existing` is the prior manifest entry with the same (role, PMS number)
    # identity — resolved by the caller, never by URL (NWCG renames S3 keys
    # between editions). Reuse its filename (e.g. a hand-curated fixture's)
    # only while it still covers the same position codes; a changed code
    # set is a split/rename, which gets the live row's own filename and
    # retires the old entry (handled in main()).
    if existing is not None and set(existing.get("position_codes", [])) != set(position_codes):
        print(
            f"  split/rename: {existing['filename']} ({'/'.join(existing.get('position_codes', []))}) "
            f"-> {filename} ({'/'.join(position_codes)})",
            file=sys.stderr,
        )
        existing = None
    filename = existing.get("filename", filename) if existing else filename
    dest = RAW_DIR / filename

    if existing is not None and dest.exists() and "VersionId=" in existing.get("url", ""):
        on_disk_hash = sha256_bytes(dest.read_bytes())
        if on_disk_hash == existing.get("sha256"):
            # unchanged: no network fetch, no new download
            REFRESH_LOG[filename] = "unchanged"
            return backfilled(existing)

    try:
        resp = polite_get(url)
    except requests.RequestException as exc:
        manifest["pending"].append(
            {
                "url": url,
                "pms_number": pms_number,
                "role": role,
                "reason": f"download failed: {exc}",
            }
        )
        return None

    data = resp.content
    if len(data) == 0:
        manifest["pending"].append(
            {"url": url, "pms_number": pms_number, "role": role, "reason": "zero-byte response"}
        )
        return None
    if filename.endswith(".pdf") and not looks_like_pdf(data):
        manifest["pending"].append(
            {
                "url": url,
                "pms_number": pms_number,
                "role": role,
                "reason": "expected PDF but response is not PDF (magic bytes mismatch, possibly HTML)"
                if not looks_like_html(data)
                else "response is HTML, not PDF (link may require auth or sharing regressed)",
            }
        )
        return None
    if filename.endswith(".docx") and not looks_like_docx(data):
        manifest["pending"].append(
            {
                "url": url,
                "pms_number": pms_number,
                "role": role,
                "reason": "expected DOCX but response is not a zip/DOCX (magic bytes mismatch, possibly HTML)"
                if not looks_like_html(data)
                else "response is HTML, not DOCX (link may require auth or sharing regressed)",
            }
        )
        return None

    resolved_url = add_version_id_from_headers(url, resp.headers)

    new_hash = sha256_bytes(data)
    superseded = list(existing.get("superseded", [])) if existing else []
    if existing is not None and existing.get("sha256") != new_hash:
        superseded.append(
            {
                "sha256": existing["sha256"],
                "downloaded_at": existing["downloaded_at"],
                "url": existing.get("url"),
                "edition_date": existing.get("edition_date"),
            }
        )

    if existing is not None and existing.get("sha256") == new_hash:
        # content identical to what the manifest already records; only (re)write file if missing
        if not dest.exists():
            dest.write_bytes(data)
        merged = backfilled(existing)
        if "VersionId=" not in merged.get("url", ""):
            merged["url"] = resolved_url
        REFRESH_LOG[filename] = "unchanged"
        return merged

    dest.write_bytes(data)
    REFRESH_LOG[filename] = "revised" if existing is not None else "new"
    entry = {
        "filename": filename,
        "position_codes": position_codes,
        "title": title,
        "pms_number": pms_number,
        "format": "unclassified",
        "url": resolved_url,
        "sha256": new_hash,
        "downloaded_at": date.today().isoformat(),
        "role": role,
        "fixture": fixture,
    }
    if superseded:
        entry["superseded"] = superseded
    if extra:
        entry.update(extra)
    return entry


# ------------------------------------------------------------------ retire --

def retire_missing(manifest: dict, prior_documents: list[dict], new_documents: list[dict]) -> list[dict]:
    """Move every prior NWCG entry (ptb / companion_standards) with no live
    counterpart in `new_documents` to the append-only `retired[]` list,
    naming the live filenames that now cover any of its position codes, and
    delete its raw file. Archived copies are never fetched in its place."""
    live_filenames = {d["filename"] for d in new_documents}
    retired = list(manifest.get("retired", []))
    already = {r["filename"] for r in retired}
    newly: list[dict] = []
    for prior in prior_documents:
        if prior.get("role") not in ("ptb", "companion_standards"):
            continue  # source-4 pages are rewritten wholesale by acquire_requirements.py
        if prior["filename"] in live_filenames or prior["filename"] in already:
            continue
        codes = set(prior.get("position_codes", []))
        superseded_by = sorted(
            d["filename"] for d in new_documents
            if d.get("role") == prior.get("role") and codes and codes & set(d.get("position_codes", []))
        )
        status = None
        try:
            status = session.head(prior["url"], timeout=REQUEST_TIMEOUT, allow_redirects=True).status_code
        except requests.RequestException as exc:  # noqa: BLE001
            status = f"error: {exc}"
        time.sleep(POLITE_DELAY_SECONDS)
        reason = (
            "not in the live NWCG catalog on this refresh"
            if prior.get("role") == "ptb"
            else "no longer referenced by any live Next Gen PTB"
        )
        reason += f"; stored URL returns HTTP {status}"
        edition = prior.get("edition_date")
        if edition is None:
            # Pre-refresh manifests carried no edition_date; the extraction
            # layer's JSON (still present until extract.py removes it)
            # records the printed edition, so the retired entry keeps it.
            extracted = REPO_ROOT / "extracted" / f"{prior['filename']}.json"
            if extracted.exists():
                printed = json.loads(extracted.read_text(encoding="utf-8")).get("document", {}).get("edition_date")
                edition = printed_edition_to_iso(printed)
        entry = {
            "filename": prior["filename"],
            "pms_number": prior.get("pms_number"),
            "position_codes": prior.get("position_codes", []),
            "role": prior.get("role"),
            "sha256": prior.get("sha256"),
            "downloaded_at": prior.get("downloaded_at"),
            "url": prior.get("url"),
            "edition_date": edition,
            "retired_at": date.today().isoformat(),
            "reason": reason,
            "superseded_by": superseded_by,
        }
        raw = RAW_DIR / prior["filename"]
        if raw.exists():
            raw.unlink()
            entry["raw_file_deleted"] = True
        retired.append(entry)
        newly.append(entry)
    manifest["retired"] = retired
    return newly


def verify_urls(manifest: dict) -> list[tuple[str, str]]:
    """HEAD every `documents` entry's stored URL; return [(filename, status)]
    for any that is not HTTP 200 (AC-A10). Google export URLs answer HEAD
    with a redirect chain, so follow redirects."""
    bad: list[tuple[str, str]] = []
    for d in manifest["documents"]:
        try:
            resp = session.head(d["url"], timeout=REQUEST_TIMEOUT, allow_redirects=True)
            status = str(resp.status_code)
            if resp.status_code == 405:  # HEAD not allowed; fall back to a streamed GET
                resp = session.get(d["url"], timeout=REQUEST_TIMEOUT, stream=True)
                status = str(resp.status_code)
                resp.close()
        except requests.RequestException as exc:  # noqa: BLE001
            status = f"error: {exc}"
        time.sleep(POLITE_DELAY_SECONDS)
        if status != "200":
            bad.append((d["filename"], status))
    return bad


# ------------------------------------------------------------------- main --

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Acquire the NWCG PTB corpus (Phase 1 / corpus refresh).")
    parser.add_argument(
        "--verify-urls",
        action="store_true",
        help="after acquisition, HEAD every manifest URL and report any that is not HTTP 200 (AC-A10)",
    )
    args = parser.parse_args(argv)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    manifest["pending"] = []  # recomputed fresh every run, never accumulated
    manifest.setdefault("retired", [])
    prior_documents = list(manifest.get("documents", []))
    existing_by_identity = {identity_of(d): d for d in prior_documents}

    new_documents: list[dict] = []
    seen_urls: set[str] = set()

    print("Fetching catalog page...", file=sys.stderr)
    catalog_entries = fetch_catalog_entries()
    print(f"  {len(catalog_entries)} PTB rows found", file=sys.stderr)

    nextgen_pms_numbers: list[str] = []
    live_by_identity: dict[tuple[str, str], dict] = {}
    catalog_urls_by_identity: dict[tuple[str, str], list[str]] = {}

    for row in catalog_entries:
        pms_norm = normalize_pms(row["pms_number"])
        codes = "-".join(c.upper() for c in row["position_codes"]) or "UNKNOWN"
        filename = f"{pms_norm}_{codes}.pdf"
        seen_urls.add(row["url"])
        identity = ("ptb", bare_pms(row["pms_number"]))
        first = live_by_identity.get(identity)
        if first is not None and set(first["position_codes"]) == set(row["position_codes"]):
            # The catalog lists the same PMS number twice (311-12 CREP, two
            # S3 keys, 2026-11-02). Identical content is one document with an
            # alternate URL; different content would be a catalog conflict.
            try:
                dup = polite_get(row["url"]).content
            except requests.RequestException as exc:
                manifest["pending"].append({"url": row["url"], "pms_number": row["pms_number"], "role": "ptb",
                                            "reason": f"duplicate catalog row; download failed: {exc}"})
                continue
            if sha256_bytes(dup) == first["sha256"]:
                catalog_urls_by_identity[identity].append(row["url"])
                print(f"  duplicate catalog row: {filename} listed twice, identical content; alternate URL recorded", file=sys.stderr)
            else:
                manifest["pending"].append({"url": row["url"], "pms_number": row["pms_number"], "role": "ptb",
                                            "reason": "catalog lists this PMS number twice with DIFFERENT content; first row kept"})
                print(f"  CONFLICT duplicate catalog row with different content: {filename}", file=sys.stderr)
            continue
        existing = existing_by_identity.get(identity)
        entry = download_document(
            manifest,
            existing,
            url=row["url"],
            filename=filename,
            pms_number=row["pms_number"],
            position_codes=row["position_codes"],
            title=row["title"],
            role="ptb",
            fixture=bool((existing or {}).get("fixture", False)),
        )
        if entry is not None:
            annotate_currency(entry, catalog_date=row["date_published"])
            entry.pop("alternate_urls", None)  # recomputed from this run's catalog
            new_documents.append(entry)
            live_by_identity[identity] = entry
            catalog_urls_by_identity[identity] = [row["url"]]
            if row["format_hint"] == "Next Gen":
                nextgen_pms_numbers.append(row["pms_number"])

    # A PMS number the catalog lists more than once (identical content, checked
    # above) keeps one entry; the canonical URL is the plain "pmsNNN-NN.pdf"
    # key (a "_0"-style suffix marks the duplicate upload) and every other
    # catalog link is kept under alternate_urls (AC-A1 covers all links).
    for identity, urls in catalog_urls_by_identity.items():
        if len(urls) < 2:
            continue
        entry = live_by_identity[identity]
        candidates = sorted(set(urls) | {entry["url"]}, key=lambda u: (bool(re.search(r"_\d+\.pdf", strip_version_id(u))), u))
        entry["url"] = candidates[0]
        entry["alternate_urls"] = sorted(set(candidates[1:]))

    print(f"Scanning {len(nextgen_pms_numbers)} Next Gen PTBs for PMS 350-xxx references...", file=sys.stderr)
    companion_links: dict[str, set[str]] = {}  # companion pms -> set of linking PTB pms numbers
    for pms in nextgen_pms_numbers:
        entry = next(
            (
                d
                for d in new_documents
                if d.get("pms_number") and bare_pms(str(d["pms_number"])) == bare_pms(pms) and d.get("role") == "ptb"
            ),
            None,
        )
        if entry is None:
            continue
        pdf_path = RAW_DIR / entry["filename"]
        if not pdf_path.exists():
            continue
        refs = find_pms350_references(pdf_path)
        if not refs:
            manifest["pending"].append(
                {
                    "pms_number": pms,
                    "role": "companion_standards",
                    "reason": "Next Gen PTB text has no detectable PMS 350-xxx reference",
                }
            )
            continue
        for ref in refs:
            companion_links.setdefault(ref, set()).add(pms)

    for companion_pms, linking_ptbs in sorted(companion_links.items()):
        companion_norm = normalize_pms(companion_pms)
        pdf_url = resolve_publication_pdf_url(companion_norm)
        if pdf_url is None:
            manifest["pending"].append(
                {
                    "pms_number": companion_pms,
                    "role": "companion_standards",
                    "reason": f"could not resolve download URL from {PUBLICATION_PAGE.format(slug=companion_norm)}",
                    "linked_ptb_pms": sorted(linking_ptbs),
                }
            )
            continue
        seen_urls.add(pdf_url)
        filename = f"{companion_norm}.pdf"
        entry = download_document(
            manifest,
            existing_by_identity.get(("companion_standards", bare_pms(companion_pms))),
            url=pdf_url,
            filename=filename,
            pms_number=companion_pms,
            position_codes=[],
            title=f"NWCG Incident Position Standards, PMS {companion_pms}",
            role="companion_standards",
            fixture=False,
            extra={"linked_ptb_pms": sorted(linking_ptbs)},
        )
        if entry is not None:
            # linked_ptb_pms is refreshed from this run's live references, not
            # setdefault'ed from the prior entry (a split such as 311-30 ->
            # 311-30 + 311-71 changes which PTBs cite a given standard).
            entry["linked_ptb_pms"] = sorted(linking_ptbs)
            annotate_currency(entry)
            new_documents.append(entry)

    print("Resolving PMS 310-1 qualification standard...", file=sys.stderr)
    qual_norm = normalize_pms(QUALIFICATION_STANDARD_PMS)
    qual_pdf_url = resolve_publication_pdf_url(qual_norm)
    if qual_pdf_url is None:
        manifest["pending"].append(
            {
                "pms_number": QUALIFICATION_STANDARD_PMS,
                "role": "qualification_standard",
                "reason": (
                    "PMS 310-1 has no downloadable PDF: "
                    f"{PUBLICATION_PAGE.format(slug=qual_norm)} links no PDF naming the publication "
                    "(its only PDF link is an unrelated flyer, 2026-11-02). The per-position data is "
                    "acquired from each position's qualification-requirements page by "
                    "src/ptb/acquire_requirements.py (source 4) instead."
                ),
            }
        )
    else:
        seen_urls.add(qual_pdf_url)
        entry = download_document(
            manifest,
            existing_by_identity.get(("qualification_standard", QUALIFICATION_STANDARD_PMS)),
            url=qual_pdf_url,
            filename=f"{qual_norm}.pdf",
            pms_number=QUALIFICATION_STANDARD_PMS,
            position_codes=[],
            title="NWCG Standards for Wildland Fire Position Qualifications, PMS 310-1",
            role="qualification_standard",
            fixture=False,
        )
        if entry is not None:
            annotate_currency(entry)
            new_documents.append(entry)

    print("Verifying enhanced PTB Google Doc export...", file=sys.stderr)
    gdoc_entries: list[dict] = []
    for fmt, (url, filename) in GDOC_EXPORTS.items():
        seen_urls.add(url)
        existing = existing_by_identity.get(("ptb", filename))
        entry = download_document(
            manifest,
            existing,
            url=url,
            filename=filename,
            pms_number=None,
            position_codes=GDOC_POSITION_CODES,
            title=(
                "FireTech Position Task Books (NWCG-format drafts, 11 positions; "
                "codes without a printed abbreviation assigned provisionally)"
                if fmt == "pdf"
                else "FireTech Position Task Books (DOCX export of the same Google Doc)"
            ),
            role="ptb",
            fixture=bool((existing or {}).get("fixture", False)),
            extra={"official": False},
        )
        if entry is not None:
            gdoc_entries.append(entry)
            new_documents.append(entry)
    docx_path = RAW_DIR / GDOC_EXPORTS["docx"][1]
    docx_date = docx_modified_date(docx_path) if docx_path.exists() else None
    for entry in gdoc_entries:
        annotate_currency(entry, docx_date=docx_date)

    # Source-4 qualification-requirement pages are owned by
    # acquire_requirements.py; carry their entries through unchanged.
    new_documents.extend(d for d in prior_documents if d.get("role") == "qualification_standard" and d.get("pms_number") == "310-1" and d["filename"].startswith("requirements/"))

    newly_retired = retire_missing(manifest, prior_documents, new_documents)
    manifest["documents"] = new_documents
    save_manifest(manifest)

    # Refresh summary (specs/acquisition.spec.md "Corpus refresh").
    by_status: dict[str, list[str]] = {}
    for fn, st in REFRESH_LOG.items():
        by_status.setdefault(st, []).append(fn)
    print(
        f"Refresh summary: unchanged={len(by_status.get('unchanged', []))} "
        f"revised={len(by_status.get('revised', []))} new={len(by_status.get('new', []))} "
        f"retired={len(newly_retired)} pending={len(manifest['pending'])}",
        file=sys.stderr,
    )
    for st in ("revised", "new"):
        for fn in sorted(by_status.get(st, [])):
            print(f"  {st}: {fn}", file=sys.stderr)
    for r in newly_retired:
        print(f"  retired: {r['filename']} -> {r['superseded_by'] or 'no successor'} ({r['reason']})", file=sys.stderr)
    pdf_name, docx_name = GDOC_EXPORTS["pdf"][1], GDOC_EXPORTS["docx"][1]
    if REFRESH_LOG.get(pdf_name) == "revised" and REFRESH_LOG.get(docx_name) == "unchanged":
        print(f"  note: {pdf_name} pdf-only hash change; docx unchanged (Google export nondeterminism)", file=sys.stderr)

    print(f"Documents: {len(new_documents)}  Pending: {len(manifest['pending'])}  Retired (total): {len(manifest['retired'])}", file=sys.stderr)

    if args.verify_urls:
        print("Verifying every manifest URL (HEAD)...", file=sys.stderr)
        bad = verify_urls(manifest)
        print(f"  dead URLs: {len(bad)}", file=sys.stderr)
        for fn, status in bad:
            print(f"    {fn}: HTTP {status}", file=sys.stderr)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
