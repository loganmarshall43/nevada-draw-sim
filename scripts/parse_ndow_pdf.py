import re
import json
import requests
import pdfplumber
from pathlib import Path

PDF_URL = "https://www.ndow.org/wp-content/uploads/2026/01/Elk-Antlered-ALW-Bonus-Point-and-Application-Trend-NonResident-2025.pdf"

OUT_RAW = Path("data/raw/ndow.pdf")
OUT_JSON = Path("data/processed/ndow_nv_elk_antlered_nr_2025.json")

def download_pdf(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    out_path.write_bytes(r.content)

def clean_int(x):
    if x is None:
        return 0
    s = str(x).strip().replace(",", "")
    if s == "":
        return 0
    # sometimes pdfplumber gives '1,176' or '1'
    try:
        return int(float(s))
    except:
        return 0

def extract_metadata(block_text: str):
    # Example lines in the PDF:
    # NR Elk Antlered
    # Units: 061, 071
    # Season: Oct 05, 2025 - Oct 21, 2025
    # Quota: 1
    # Weapon Any Legal Weapon
    title = None
    units = None
    season = None
    quota = None
    weapon = None

    # Title is first non-empty line
    lines = [l.strip() for l in block_text.split("\n") if l.strip()]
    if lines:
        title = lines[0]

    m = re.search(r"Units:\s*(.+)", block_text)
    if m: units = m.group(1).strip()

    m = re.search(r"Season:\s*(.+)", block_text)
    if m: season = m.group(1).strip()

    m = re.search(r"Quota:\s*(\d+)", block_text)
    if m: quota = int(m.group(1))

    m = re.search(r"Weapon\s*(.+)", block_text)
    if m: weapon = m.group(1).strip()

    return {
        "title": title,
        "units": units,
        "season": season,
        "quota": quota,
        "weapon": weapon,
    }

def normalize_table(table):
    """
    Expected table columns (from the PDF layout):
      Bonus Points |
      Successful Applicants by Choice: 1st..5th |
      Total Applicants by Choice: 1st..5th |
      Total Applicants
    Many successful cells are blank => treat as 0.
    """
    # find header row index (contains 'Bonus Points')
    header_idx = None
    for i, row in enumerate(table):
        row_join = " ".join([str(c or "").strip() for c in row])
        if "Bonus Points" in row_join:
            header_idx = i
            break
    if header_idx is None:
        return None

    data_rows = []
    for row in table[header_idx + 1:]:
        # stop at totals row
        first = (row[0] or "").strip()
        if first.lower() == "total":
            # could capture totals here if you want
            break

        # Some rows may be None/empty
        if not first or not re.match(r"^\d+$", first.strip()):
            continue

        bp = clean_int(first)

        # Expect 1 + 5 + 5 + 1 = 12 columns, but sometimes extraction merges/splits
        cells = [clean_int(c) for c in row[1:]]
        # pad to at least 11 remaining columns
        while len(cells) < 11:
            cells.append(0)

        successful = cells[0:5]
        total_by_choice = cells[5:10]
        total_applicants = cells[10]

        data_rows.append({
            "bp": bp,
            "successfulByChoice": successful,
            "totalByChoice": total_by_choice,
            "totalApplicants": total_applicants,
        })

    # sort by bonus points asc
    data_rows.sort(key=lambda r: r["bp"])
    return data_rows

def parse_pdf(pdf_path: Path):
    hunts = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""

            # The PDF repeats blocks starting with "NR Elk Antlered"
            # We'll split blocks by occurrences of the title.
            # Keep the delimiter by re-adding it after split.
            parts = re.split(r"\n(?=NR Elk Antlered\b)", text)
            for part in parts:
                if not part.strip().startswith("NR Elk Antlered"):
                    continue

                meta = extract_metadata(part)

                # Extract tables from the page and choose the one that matches this block.
                # Since each block has one table right below metadata, we can take the next table.
                tables = page.extract_tables({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "intersection_tolerance": 5,
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                    "edge_min_length": 50,
                    "min_words_vertical": 1,
                    "min_words_horizontal": 1,
                }) or []

                # Heuristic: pick the first table on this page that looks like it has Bonus Points.
                chosen = None
                for t in tables:
                    t_text = " ".join(" ".join([str(c or "").strip() for c in r]) for r in t)
                    if "Bonus Points" in t_text and "Total Applicants" in t_text:
                        chosen = t
                        break

                if not chosen:
                    continue

                rows = normalize_table(chosen)
                if not rows:
                    continue

                hunts.append({
                    "state": "NV",
                    "year": 2025,
                    "residency": "NR",
                    "species": "elk",
                    "category": "antlered",
                    **meta,
                    "rows": rows,
                    "sourcePdf": PDF_URL,
                    "sourcePage": page_num + 1,
                })

    return hunts

def main():
    download_pdf(PDF_URL, OUT_RAW)
    hunts = parse_pdf(OUT_RAW)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(hunts, indent=2), encoding="utf-8")
    print(f"Wrote {len(hunts)} hunt blocks to {OUT_JSON}")

if __name__ == "__main__":
    main()
