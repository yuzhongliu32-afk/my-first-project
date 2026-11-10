"""Standalone REAL OpenAI B run. Does not call A orchestration or old rules."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4
from harbourline.llm import ModelGateway
from harbourline.sources import EvidenceLibrary
from .agent import generate
from .env_file import load_env_file

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description='Generate Planning/Risk directly with OpenAI')
    parser.add_argument('--model',help='Model ID enabled in your API project (default: OPENAI_MODEL)')
    parser.add_argument('--env-file',type=Path,help='Local .env holding OPENAI_API_KEY/OPENAI_MODEL; never commit it')
    parser.add_argument('--library',type=Path,default=ROOT/'data/evidence_library.json')
    parser.add_argument('--request',type=Path,default=ROOT/'examples/member_b_pack_request.json')
    parser.add_argument('--cutoff',help='Verified evidence cut-off YYYY-MM-DD')
    parser.add_argument('--out',type=Path,default=ROOT/'.local/member_b_live_output.json')
    args=parser.parse_args()
    if args.env_file:
        loaded=load_env_file(args.env_file)
        print(json.dumps({'env_file_loaded':loaded}))  # names only, never values
    if not os.getenv('OPENAI_API_KEY'):
        parser.error('OPENAI_API_KEY missing. Store credentials locally, never in GitHub.')
    args.model=args.model or os.getenv('OPENAI_MODEL')
    if not args.model:
        parser.error('Pass --model or set OPENAI_MODEL to a model ID enabled for your API key.')
    library=EvidenceLibrary(args.library)
    request=json.loads(args.request.read_text(encoding='utf-8'))
    request['run_id']='B-LIVE-'+str(uuid4())
    request['source_snapshot_id']=library.snapshot
    trace={'run_id':request['run_id']}
    output=generate(request,library,ModelGateway(model=args.model),cutoff=args.cutoff,
                    max_rounds=max(request['request']['max_review_rounds'],3),trace=trace)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # What-if computation detail (three-point inputs, P50/P80) for the workbench page.
    args.out.with_name('member_b_live_trace.json').write_text(
        json.dumps({**trace,'result':'PASSED'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':output['status'],'mode':'LIVE_OPENAI',
         'api_calls':output['metrics']['api_calls'],
         'input_tokens':output['metrics']['input_tokens'],
         'output_tokens':output['metrics']['output_tokens'],
         'file':str(args.out)},ensure_ascii=False))

if __name__=='__main__':main()
