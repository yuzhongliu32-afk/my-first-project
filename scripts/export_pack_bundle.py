"""Write the Data Pack as one JSON bundle for hosts that cannot hold the PDF/CSV originals.

The bundle carries exactly the lines B reads from each file plus that file's sha256, so B's output
from the bundle equals its output from the folder. Course material: keep it out of the repository.

    python scripts/export_pack_bundle.py --out data/pack_sources.json
then point B at it with HARBOURLINE_DATA_PACK_DIR=<path to the json>.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.member_b.data_pack import PACK_VERSION, load_pack_sources  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pack', type=Path, default=ROOT / 'data/Harbourline_Data_Pack')
    p.add_argument('--out', type=Path, default=ROOT / 'data/pack_sources.json')
    a = p.parse_args()
    sources = load_pack_sources(a.pack)
    bundle = {'pack_version': PACK_VERSION,
              'documents': {doc['document_id']: {k: doc[k] for k in ('source_type', 'page', 'lines', 'filename', 'sha256')}
                            for doc in sources.values()}}
    a.out.write_text(json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
    print(f'wrote {a.out} ({a.out.stat().st_size // 1024} KB, {len(bundle["documents"])} files)')


if __name__ == '__main__':
    main()
