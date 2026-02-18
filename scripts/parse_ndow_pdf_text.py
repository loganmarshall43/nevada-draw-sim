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

def ints_from_line(line: str):
    # grabs integers including commas: 1,176
    return [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", line)]

def parse_block_rows(row_lines):
    """
    NDOW rows are tricky because "Successful Applicants by Choice" columns are often blank (zeros),
    so extracted text collapses them.

    What we DO reliably have per row:
      - bonus points (bp)
      - then 5 totals-by-choice numbers (1st..5th)
      - sometimes some leading successful counts appear (non-zero) before the totals

    Strategy:
      remaining = numbers after bp
      last 5 numbers are ALWAYS totalByChoice
      any numbers before those are successfulByChoice (1..5), padded with zeros.
      totalApplicants = sum(totalByChoice)
    """
    rows = []
    for line in row_lines:
        nums = ints_from_line(line)
        if not nums:
            continue
        bp = nums[0]
        remaining = nums[1:]

        # must have at least 5 totals-by-choice
        if len(remaining) < 5:
            continue

        success_count = len(remaining) - 5
        success_raw = remaining[:success_count]
        totals = remaining[success_count:success_count + 5]

        # pad success to length 5
        successful = (success_raw + [0, 0, 0, 0, 0])[:5]

        rows.append({
            "bp": bp,
            "successfulByChoice": successful,   # length 5
            "totalByChoice": totals,            # length 5
            "totalApplicants": sum(totals),
        })

    rows.sort(key=lambda r: r["bp"])
    return rows

def parse_pdf(pdf_path: Path):
    # Pull all lines across all pages (handles tables that break across pages)
    all_lines = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pnum, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            # remove footer-ish lines like "1/5/2026 Page X of Y"
            lines = [l for l in lines if not re.search(r"Page\s+\d+\s+of\s+\d+", l)]
            for l in lines:
                all_lines.append((pnum, l))

    hunts = []
    i = 0

    while i < len(all_lines):
        pnum, line = all_lines[i]

        # Start of a hunt block
        if line == "NR Elk Antlered":
            block = {
                "state": "NV",
                "year": 2025,
                "residency": "NR",
                "species": "elk",
                "category": "antlered",
                "title": line,
                "units": None,
                "season": None,
                "quota": None,
                "weapon": None,
                "rows": [],
                "sourcePdf": PDF_URL,
                "startPage": pnum,
            }

            # read metadata lines that follow
            i += 1
            while i < len(all_lines):
                p, l = all_lines[i]

                if l.startswith("Units:"):
                    block["units"] = l.replace("Units:", "").strip()
                elif l.startswith("Season:"):
                    block["season"] = l.replace("Season:", "").strip()
                elif l.startswith("Quota:"):
                    q = ints_from_line(l)
                    block["quota"] = q[0] if q else None
                elif l.startswith("Weapon"):
                    block["weapon"] = l.replace("Weapon", "").strip()

                # header line that signals table begins
                if l.startswith("Bonus Points"):
                    break

                # next hunt started unexpectedly (rare)
                if l == "NR Elk Antlered":
                    # don't advance; let outer loop pick it up
                    i -= 1
                    break

                i += 1

            # now skip the 2-3 header lines and read rows until "Total ..."
            row_lines = []
            i += 1
            while i < len(all_lines):
                p, l = all_lines[i]

                if l.startswith("Total"):
                    # totals row can be parsed if you want, but we stop here
                    block["endPage"] = p
                    break

                # next block begins
                if l == "NR Elk Antlered":
                    i -= 1
                    block["endPage"] = p
                    break

                # data rows start with a number (bonus points)
                if re.match(r"^\d+\b", l):
                    row_lines.append(l)

                i += 1

            block["rows"] = parse_block_rows(row_lines)

            # only keep blocks that actually got rows
            if block["rows"]:
                hunts.append(block)

        i += 1

    return hunts

def main():
    download_pdf(PDF_URL, OUT_RAW)
    hunts = parse_pdf(OUT_RAW)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(hunts, indent=2), encoding="utf-8")

    print(f"Wrote {len(hunts)} hunt blocks to {OUT_JSON}")
    if hunts:
        print("Example block:", hunts[0]["units"], hunts[0]["season"], "rows:", len(hunts[0]["rows"]))

if __name__ == "__main__":
    main()
