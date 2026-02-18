import re
import json
import hashlib
import requests
import pdfplumber
from pathlib import Path
from urllib.parse import urlparse

YEAR = 2025
URLS_FILE = Path(f"data/inputs/ndow_pdfs_{YEAR}.txt")
CACHE_DIR = Path(f"data/cache/{YEAR}")
OUT_JSON = Path(f"data/processed/nv_bonuspoints_{YEAR}.json")

def safe_filename_from_url(url: str) -> str:
    name = Path(urlparse(url).path).name
    if name.lower().endswith(".pdf") and len(name) > 4:
        return name
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"ndow_{h}.pdf"

def download_cached(url: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fn = safe_filename_from_url(url)
    fp = CACHE_DIR / fn
    if fp.exists() and fp.stat().st_size > 10_000:
        return fp
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    fp.write_bytes(r.content)
    return fp

def ints_from_line(line: str):
    return [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", line)]

def parse_block_rows(row_lines):
    """
    Robust against blank 'successful' columns collapsing.
    Rule:
      bp = first number
      last 5 numbers = totalByChoice (1..5)
      any numbers before those = successfulByChoice (pad to 5)
      totalApplicants = sum(totalByChoice)
    """
    rows = []
    for line in row_lines:
        nums = ints_from_line(line)
        if not nums:
            continue
        bp = nums[0]
        remaining = nums[1:]
        if len(remaining) < 5:
            continue

        success_count = len(remaining) - 5
        success_raw = remaining[:success_count]
        totals = remaining[success_count:success_count + 5]
        successful = (success_raw + [0, 0, 0, 0, 0])[:5]

        rows.append({
            "bp": bp,
            "successfulByChoice": successful,
            "totalByChoice": totals,
            "totalApplicants": sum(totals),
        })

    rows.sort(key=lambda r: r["bp"])
    return rows

def infer_residency_from_url(url: str):
    u = url.lower()
    if "nonresident" in u:
        return "NR"
    if "resident" in u:
        return "R"
    return None  # Some PDFs are combined / not residency-specific

def infer_species_from_url(url: str):
    u = Path(urlparse(url).path).name.lower()
    # crude but works well for your file list
    if "elk" in u: return "elk"
    if "mule-deer" in u or "mule_deer" in u: return "deer"
    if "antelope" in u: return "antelope"
    if "bighorn" in u: return "sheep"
    if "goat" in u: return "goat"
    if "moose" in u: return "moose"
    if "bear" in u: return "bear"
    return "unknown"

def extract_all_lines(pdf_path: Path):
    all_lines = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pnum, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            # drop footer-ish page markers if present
            lines = [l for l in lines if not re.search(r"Page\s+\d+\s+of\s+\d+", l)]
            for l in lines:
                all_lines.append((pnum, l))
    return all_lines

def parse_pdf_blocks(pdf_path: Path, source_url: str):
    all_lines = extract_all_lines(pdf_path)
    pages = [p for (p, _) in all_lines]
    lines = [l for (_, l) in all_lines]

    inferred_res = infer_residency_from_url(source_url)
    inferred_species = infer_species_from_url(source_url)

    blocks = []
    i = 0

    # Helper: find previous non-empty line (title) before Units:
    def prev_nonempty(idx):
        j = idx - 1
        while j >= 0:
            if lines[j].strip():
                return lines[j].strip()
            j -= 1
        return None

    while i < len(lines):
        line = lines[i]

        # Block anchor: Units:
        if line.startswith("Units:"):
            title = prev_nonempty(i) or "Unknown Title"
            start_page = pages[i]

            # metadata
            units = line.replace("Units:", "").strip()
            season = None
            quota = None
            weapon = None

            j = i + 1
            # read metadata until we hit table header "Bonus Points"
            while j < len(lines):
                l = lines[j]
                if l.startswith("Season:"):
                    season = l.replace("Season:", "").strip()
                elif l.startswith("Quota:"):
                    q = ints_from_line(l)
                    quota = q[0] if q else None
                elif l.startswith("Weapon"):
                    weapon = l.replace("Weapon", "").strip()

                if l.startswith("Bonus Points"):
                    break

                # Safety: if we hit another Units: before Bonus Points, abandon this one
                if l.startswith("Units:"):
                    break

                j += 1

            if j >= len(lines) or not lines[j].startswith("Bonus Points"):
                i += 1
                continue

            # gather rows after header until Total OR next Units:
            row_lines = []
            k = j + 1
            end_page = pages[j]

            while k < len(lines):
                l = lines[k]
                if l.startswith("Total"):
                    end_page = pages[k]
                    break
                if l.startswith("Units:"):
                    k -= 1
                    end_page = pages[k] if k >= 0 else end_page
                    break
                if re.match(r"^\d+\b", l):
                    row_lines.append(l)
                k += 1

            rows = parse_block_rows(row_lines)
            if rows:
                # Title sometimes includes residency prefix (R/NR). If so, prefer it.
                title_res = "NR" if title.startswith("NR ") else ("R" if title.startswith("R ") else None)

                blocks.append({
                    "state": "NV",
                    "year": YEAR,
                    "residency": title_res or inferred_res,   # may be None
                    "species": inferred_species,
                    "title": title,
                    "units": units,
                    "season": season,
                    "quota": quota,
                    "weapon": weapon,
                    "rows": rows,
                    "sourceUrl": source_url,
                    "sourceFile": pdf_path.name,
                    "startPage": start_page,
                    "endPage": end_page,
                })

        i += 1

    return blocks

def main():
    if not URLS_FILE.exists():
        raise SystemExit(f"Missing URL list file: {URLS_FILE}")

    # Read + dedupe URLs while preserving order
    seen = set()
    urls = []
    for line in URLS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        urls.append(line)

    all_blocks = []
    for url in urls:
        try:
            pdf_path = download_cached(url)
            blocks = parse_pdf_blocks(pdf_path, url)
            print(f"{pdf_path.name}: {len(blocks)} blocks")
            all_blocks.extend(blocks)
        except Exception as e:
            print(f"FAILED: {url}\n  -> {e}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(all_blocks, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_blocks)} total blocks to {OUT_JSON}")

if __name__ == "__main__":
    main()
