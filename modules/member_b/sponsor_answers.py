"""Formal Sponsor answers (e.g. "Capstone Sponsor Answers — Round 1") as evidence.

Builds a SPONSOR_ANSWER registry record from the official PDF so that a Sponsor
question can be marked ANSWERED only by citing the Sponsor's own words. AI text
is never converted into sponsor evidence: this reads the PDF the course issued.

CLI:  python -m modules.member_b.sponsor_answers "<Sponsor Answers Round 1.pdf>" [--out data/sponsor_answers_registry.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

DOC_ID = 'SPONSOR-ANSWERS-R1'
PAGE_FOOTER = re.compile(r'^Page \d+ of \d+$')


def registry_from_pdf(pdf: Path | str, *, document_id: str = DOC_ID) -> dict:
    from pypdf import PdfReader
    pdf = Path(pdf)
    data = pdf.read_bytes()
    lines, pages = [], []
    for number, page in enumerate(PdfReader(str(pdf)).pages, start=1):
        for raw in (page.extract_text() or '').splitlines():
            line = ' '.join(raw.split())
            if not line or PAGE_FOOTER.match(line):
                continue
            lines.append(line)
            pages.append(number)
    if not lines:
        raise ValueError(f'No text could be read from {pdf.name}')
    if not any(re.match(r'^Q\d+\.', l) for l in lines):
        raise ValueError(f'{pdf.name} does not look like a Sponsor answers document (no "Q1." lines)')
    return {'document_id': document_id, 'version': hashlib.sha256(data).hexdigest()[:12],
            'source_type': 'SPONSOR_ANSWER', 'page': pages[0], 'lines': lines,
            'line_pages': pages, 'pdf_sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description='Build a SPONSOR_ANSWER registry from the official PDF')
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--out', type=Path,
                        default=Path(__file__).resolve().parents[2] / 'data/sponsor_answers_registry.json')
    args = parser.parse_args()
    record = registry_from_pdf(args.pdf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps([record], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{record['document_id']} {record['version']}: {len(record['lines'])} lines -> {args.out}")


if __name__ == '__main__':
    main()
