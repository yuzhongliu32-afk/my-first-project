"""Optional live embedding index; lexical retrieval needs neither API nor this file."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from harbourline.sources import EvidenceLibrary
from harbourline.llm import ModelGateway
p=argparse.ArgumentParser();p.add_argument('--library',type=Path,default=ROOT/'data/evidence_library.json')
p.add_argument('--model',required=True);p.add_argument('--out',type=Path,default=ROOT/'data/semantic_index.json')
a=p.parse_args();lib=EvidenceLibrary(a.library);gateway=ModelGateway();chunks=[]
for doc in lib.documents:
    for line,text in enumerate(doc['lines'],1):
        if text.strip():chunks.append({'source':lib.ref(doc,line,line)})
for start in range(0,len(chunks),64):
    batch=chunks[start:start+64];vectors=gateway.embeddings([c['source']['quote'] for c in batch],a.model)
    for c,v in zip(batch,vectors):c['vector']=v
value={'format_version':'harbourline-semantic.v1','source_snapshot_id':lib.snapshot,'model':a.model,'chunks':chunks,'build_metrics':gateway.metrics()}
a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(value)+'\n');print(a.out)
