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
p.add_argument('--sponsor-answers',type=Path,action='append',default=[],
               help='Official Sponsor answers PDF (e.g. Round 1); added as SPONSOR_ANSWER evidence')
p.add_argument('--out',type=Path,default=ROOT/'data/evidence_library.json')
a=p.parse_args();prepare_sources(a.brief,a.pack,root=ROOT)
records=json.loads((ROOT/'data/brief_source_registry.json').read_text(encoding='utf-8'))
if a.pack:records.extend(load_pack_sources(ROOT/'data/Harbourline_Data_Pack').values())
for extra in a.additional_registry:records.extend(json.loads(extra.read_text(encoding='utf-8')))
if a.sponsor_answers:
    from modules.member_b.sponsor_answers import registry_from_pdf
    for i,pdf in enumerate(a.sponsor_answers,start=1):
        records.append(registry_from_pdf(pdf,document_id=f'SPONSOR-ANSWERS-R{i}'))
meta=json.loads(a.metadata.read_text(encoding='utf-8')) if a.metadata else {}
lib=build_library(records,a.out,metadata=meta,b_snapshot='PACK-JAN-MAR-2027-V1' if a.pack else 'BRIEF-2026-10-10-ONLY')
print(lib.snapshot);print(f'{len(records)} documents; unknown availability dates remain excluded from period reporting.')
