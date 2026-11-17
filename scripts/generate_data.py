#!/usr/bin/env python3
"""Generate a fictional, searchable 200-page washing-machine service manual."""

import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

TOPICS = [
    ("Drain pump and filter", "drain, E21, E20, water remains, pump, hose",
     "With the appliance isolated from power, inspect only the user-accessible drain filter and hose for lint, kinks, or blockage. Follow the model-specific procedure before any internal inspection. Record drain flow and the displayed code during a supervised test."),
    ("Water inlet valve and hose", "slow fill, E10, inlet, water supply, hose",
     "Confirm the water supply is available and the inlet hose is not kinked. Inspect the accessible inlet screen only as described for this model. Record fill time and the exact code; refer internal valve checks to a qualified technician."),
    ("Suspension and load balance", "spin, unbalanced load, vibration, drum",
     "Check for an uneven or single bulky load and confirm the unit is level and stable. Repeat the spin observation with a balanced load. Refer persistent excessive movement or internal suspension checks to a qualified technician."),
    ("Door seal and latch", "door leak, seal, latch, water at door",
     "Stop the cycle and inspect the visible door seal for trapped fabric, debris, or damage. Confirm the door closes evenly. Do not operate with a damaged seal; record where and when leakage occurs."),
    ("Installation and suspension", "vibration, transit bolts, leveling, spin",
     "Verify installation against the model instructions, including removal of transit restraints and stable contact of all feet with the floor. Repeat a supervised balanced-load spin test and record the conditions."),
    ("Heating system", "cold water, heating, temperature, warm cycle",
     "Compare the selected program and observed temperature behavior with the model specification. Heating-circuit measurements and internal repairs must be performed by a qualified technician using the model-specific procedure."),
    ("Door lock", "door locked, release, latch, cycle ended",
     "After the program ends, allow the normal release delay and confirm the drum is empty and drained. Record the lock indicator and exact sequence. Do not force the door; refer persistent lock faults to a qualified technician."),
    ("Drain pump", "grinding, noise, pump, drain, filter",
     "Record whether noise occurs during fill, wash, or drain. With power isolated, inspect only the accessible filter area for foreign objects. Internal pump inspection must use the approved model procedure and qualified personnel."),
    ("Drain pump and hose", "E20, drain, hose, water remains, rinse",
     "Check drain hose routing for kinks and the accessible filter for lint, following the model service procedure. Record drain flow and the point in the program when the code appears."),
    ("Dispenser drawer", "detergent drawer, softener, retained water, dispenser",
     "Remove and clean only the drawer parts identified as removable in the model instructions. Check the siphon insert is seated and run a supervised fill test; record which compartment retains water."),
]


def build_pages():
    pages = []
    for page in range(1, 201):
        component, keywords, procedure = TOPICS[(page - 1) % len(TOPICS)]
        title = f"{component}: service observation {page:03d}"
        text = (
            f"Component: {component}. Search terms: {keywords}. "
            f"Procedure: {procedure} "
            f"Record sheet: page-specific observation {page:03d}; note model, "
            "program phase, displayed code, and test result. "
            "Safety: stop use if there is a leak, burning smell, or damaged cable. "
            "Electrical/internal work is for qualified service personnel only."
        )
        pages.append({
            "id": f"SM-P{page:03d}",
            "page": page,
            "title": title,
            "text": text,
            "source": "Fictional washing-machine service manual (sample)",
        })
    return pages


def pdf_escape(value):
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(pages, output):
    objects = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    font_id = 3
    page_ids = [4 + index * 2 for index in range(len(pages))]
    content_ids = [page_id + 1 for page_id in page_ids]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for page, page_id, content_id in zip(pages, page_ids, content_ids):
        lines = [page["title"], f"Manual page {page['page']} | Citation: {page['id']}"]
        lines.extend(textwrap.wrap(page["text"], width=92))
        commands = ["BT", "/F1 10 Tf", "48 750 Td"]
        for index, line in enumerate(lines):
            if index:
                commands.append("0 -16 Td")
            commands.append(f"({pdf_escape(line)}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, max(objects) + 1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_id} 0 obj\n".encode())
        pdf.extend(objects[object_id])
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    output.write_bytes(pdf)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    pages = build_pages()
    (DATA / "manual_chunks.json").write_text(
        json.dumps({"pages": pages}, indent=2) + "\n", encoding="utf-8"
    )
    write_pdf(pages, DATA / "service_manual.pdf")
    print(f"Wrote {len(pages)} pages to data/service_manual.pdf")
    print(f"Wrote {len(pages)} searchable chunks to data/manual_chunks.json")


if __name__ == "__main__":
    main()
