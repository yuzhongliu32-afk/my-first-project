"""Set up *local-only* course sources; avoids committing PDFs/CSV into Git.

Example:
python -m modules.member_b.prepare_sources --brief "path/to/MA6094 Capstone Brief.pdf" --pack "path/to/Harbourline_Data_Pack.zip"
"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
from pypdf import PdfReader
from .data_pack import FILES
from .planning_risk import ROOT, DOC_ID, DOC_VERSION, _brief


def prepare_sources(brief_pdf: Path, pack_zip: Path | None = None, root: Path = ROOT):
    root = Path(root)
    brief_pdf = Path(brief_pdf)
    pages = PdfReader(str(brief_pdf)).pages
    if len(pages) < 3:
        raise ValueError("Brief PDF must have at least 3 pages")
    lines = pages[2].extract_text().splitlines()
    record = {"document_id": DOC_ID, "version": DOC_VERSION, "source_type": "BRIEF",
              "page": 3, "lines": lines,
              "pdf_sha256": hashlib.sha256(brief_pdf.read_bytes()).hexdigest()}
    _brief({(DOC_ID, DOC_VERSION): record})
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    target = data / "brief_source_registry.json"
    target.write_text(json.dumps([record], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extracted=[]
    if pack_zip is not None:
        pack_zip = Path(pack_zip)
        with ZipFile(pack_zip) as z:
            paths={n.rsplit("/",1)[-1]:n for n in z.namelist() if not n.endswith("/")}
            missing=set(FILES.values())-set(paths)
            if missing:
                raise ValueError(f"Data Pack zip missing expected files: {sorted(missing)}")
            out_dir=data/"Harbourline_Data_Pack"
            out_dir.mkdir(parents=True,exist_ok=True)
            for filename in FILES.values():
                src=paths[filename]
                info=z.getinfo(src)
                if info.file_size > 15_000_000:
                    raise ValueError(f"Unexpected large data file: {filename}")
                (out_dir/filename).write_bytes(z.read(info))
                extracted.append(filename)
    return target,extracted


def main():
    parser=argparse.ArgumentParser(description="Prepare Member B source files locally (excluded by .gitignore).")
    parser.add_argument("--brief", required=True, type=Path, help="Path to instructor's MA6094 Capstone Brief PDF")
    parser.add_argument("--pack", type=Path, default=None, help="Path to Harbourline_Data_Pack.zip")
    args=parser.parse_args()
    registry,extracted=prepare_sources(args.brief,args.pack)
    print(f"Prepared local brief registry: {registry}")
    if args.pack: print(f"Prepared {len(extracted)} official synthetic Data Pack source files (local only)")
    print("Source files remain under data/ and are excluded from the Git repository.")

if __name__=="__main__":
    main()
