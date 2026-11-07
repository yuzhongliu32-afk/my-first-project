"""Build portable evidence from exact local brief/pack; dates require supplied metadata."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from modules.member_b.prepare_sources import prepare_sources
from modules.member_b.data_pack import load_pack_sources
from harbourline.sources import build_library

p=argparse.ArgumentParser();p.add_argument('--brief',type=Path,required=True)
p.add_argument('--additional-registry',type=Path,action='append',default=[]);p.add_argument('--pack',type=Path);p.add_argument('--metadata',type=Path)
p.add_argument('--root',type=Path,default=ROOT)
p.add_argument('--out',type=Path)
a=p.parse_args();prepare_sources(a.brief,a.pack,root=a.root)
records=json.loads((a.root/'data/brief_source_registry.json').read_text())
if a.pack:records.extend(load_pack_sources(a.root/'data/Harbourline_Data_Pack').values())
for extra in a.additional_registry:records.extend(json.loads(extra.read_text()))
meta=json.loads(a.metadata.read_text()) if a.metadata else {}
lib=build_library(records,a.out or a.root/'data/evidence_library.json',metadata=meta,b_snapshot='PACK-JAN-MAR-2027-V1' if a.pack else 'BRIEF-2026-10-10-ONLY')
print(lib.snapshot);print(f'{len(records)} documents; unknown availability dates remain excluded from period reporting.')
