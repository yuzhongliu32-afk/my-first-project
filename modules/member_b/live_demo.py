"""Standalone REAL OpenAI B run. Does not call A orchestration or old rules."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4
from harbourline.llm import ModelGateway
from harbourline.sources import EvidenceLibrary
from .agent import generate

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description='Generate Planning/Risk directly with OpenAI')
    parser.add_argument('--model',required=True,help='Model ID enabled in your API project')
    parser.add_argument('--library',type=Path,default=ROOT/'data/evidence_library.json')
    parser.add_argument('--request',type=Path,default=ROOT/'examples/member_b_pack_request.json')
    parser.add_argument('--cutoff',help='Verified evidence cut-off YYYY-MM-DD')
    parser.add_argument('--out',type=Path,default=ROOT/'.local/member_b_live_output.json')
    args=parser.parse_args()
    if not os.getenv('OPENAI_API_KEY'):
        parser.error('OPENAI_API_KEY missing. Store credentials locally, never in GitHub.')
    library=EvidenceLibrary(args.library)
    request=json.loads(args.request.read_text(encoding='utf-8'))
    request['run_id']='B-LIVE-'+str(uuid4())
    request['source_snapshot_id']=library.snapshot
    output=generate(request,library,ModelGateway(model=args.model),cutoff=args.cutoff,
                    max_rounds=request['request']['max_review_rounds'])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':output['status'],'mode':'LIVE_OPENAI',
         'api_calls':output['metrics']['api_calls'],
         'input_tokens':output['metrics']['input_tokens'],
         'output_tokens':output['metrics']['output_tokens'],
         'file':str(args.out)},ensure_ascii=False))

if __name__=='__main__':main()
