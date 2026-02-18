import re
import json
import requests
import pdfplumber
from pathlib import Path

# --- CONFIG ---
YEAR = 2025
PDF_DIR = Path(f"data/raw/pdfs/{YEAR}")
OUT_JSON = Path(f"data/processed/nv_bonuspoints_{YEAR}.json")

# --- HELPERS ---
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

def infer_species_and_category(title: str):
    """
    Title examples (vary by PDF):
      'NR Elk Antlered'
      'R Elk Antlered'
      'NR Mule Deer'
      'NR Antelope Horns Longer Than Ears'
    We'll extract the second token as species (elk, deer, antelope, sheep, goat),
    and the remainder as category.
    """
    parts = title.split()
    residency = parts[0]  # R or NR
    rest = parts[1:]
    if not rest:
        return residency, None, None

    # Normalize species keys
    raw_species = rest[0].lower()
    species_map = {
        "elk": "elk",
        "deer": "deer",
        "antelope": "antelope",
        "sheep": "sheep",
        "goat": "goat",
    }
    species = species_map.get(raw_species, raw_species)
    category = " ".join(rest[1:]).strip() or None
    return residency, species, category

def extract_metadata(lines, start_i):
    """
    After title line, expect metadata lines like:
      Units: ...
      Season: ...
      Quota: ...
      Weapon ...
    until 'Bonus Points' header.
    """
    meta = {"units": None, "season": None, "quota": None, "weapon": None}
    i = start_i
    while i < len(lines):
        l = lines[i]
        if l.startswith("Units:"):
            meta["units"] = l.replace("Units:", "").strip()
        elif l.startswith("Season:"):
            meta["season"] = l.replace("Season:", "").strip()
        elif l.startswith("Quota:"):
            q = ints_from_line(l)
            meta["quota"] = q[0] if q else None
        elif l.startswith("Weapon"):
            meta["weapon"] = l.replace("Weapon", "").strip()

        if l.startswith("Bonus Points"):
            break
        i += 1
    return meta, i

def parse_single_pdf(pdf_path: Path, year: int):
    hunts = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        all_lines = []
        for pnum, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            page_lines = [l.strip() for l in text.split("\n") if l.strip()]
            page_lines = [l for l in page_lines if not re.search(r"Page\s+\d+\s+of\s+\d+", l)]
            for l in page_lines:
                all_lines.append((pnum, l))

    # Flatten for easier scanning but keep page info
    pages = [p for (p, _) in all_lines]
    lines = [l for (_, l) in all_lines]

    i = 0
    while i < len(lines):
        line = lines[i]

        # Title line heuristic: starts with R or NR and has at least 2 words
        if re.match(r"^(R|NR)\s+\S+", line):
            title = line
            start_page = pages[i]

            residency, species, category = infer_species_and_category(title)

            meta, j = extract_metadata(lines, i + 1)

            # If we never found table header, skip block
            if j >= len(lines) or not lines[j].startswith("Bonus Points"):
                i += 1
                continue

            # Collect row lines after header until Total or next title
            row_lines = []
            k = j + 1
            end_page = pages[j]

            while k < len(lines):
                l = lines[k]
                if l.startswith("Total"):
                    end_page = pages[k]
                    break
                if re.match(r"^(R|NR)\s+\S+", l):
                    # next block
                    k -= 1
                    end_page = pages[k] if k >= 0 else end_page
                    break
                if re.match(r"^\d+\b", l):
                    row_lines.append(l)
                k += 1

            rows = parse_block_rows(row_lines)
            if rows:
                hunts.append({
                    "state": "NV",
                    "year": year,
                    "residency": residency,
                    "species": species,
                    "category": category,
                    "title": title,
                    **meta,
                    "rows": rows,
                    "sourceFile": pdf_path.name,
                    "startPage": start_page,
                    "endPage": end_page,
                })

        i += 1

    return hunts

def main():
    if not PDF_DIR.exists():
        raise SystemExit(f"PDF directory not found: {PDF_DIR}")

    all_hunts = []
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {PDF_DIR}")

    for pdf_path in pdfs:
        hunts = parse_single_pdf(pdf_path, YEAR)
        print(f"{pdf_path.name}: {len(hunts)} blocks")
        all_hunts.extend(hunts)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(all_hunts, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_hunts)} total hunt blocks to {OUT_JSON}")

if __name__ == "__main__":
    main()
