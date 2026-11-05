"""Small local HTTP client to verify B's endpoint without Postman/curl."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from .planning_risk import ROOT


def main():
    p=argparse.ArgumentParser(description="Call the local Member B HTTP server")
    p.add_argument("--url",default="http://127.0.0.1:8765/v1/plan-risk")
    p.add_argument("--request",type=Path,default=ROOT/"examples/member_b_pack_request.json")
    p.add_argument("--output",type=Path,default=ROOT/".local/member_b_http_output.json")
    a=p.parse_args()
    request=json.loads(a.request.read_text(encoding="utf-8"))
    payload={"request":request,"context":{"source_snapshot_id":request["source_snapshot_id"]}}
    data=json.dumps(payload).encode("utf-8")
    http=Request(a.url,data=data,headers={"Content-Type":"application/json"},method="POST")
    with urlopen(http,timeout=20) as response:
        output=json.loads(response.read())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"B HTTP response: {output.get('status')}; WBS={len(output.get('planning',{}).get('wbs_items',[]))}, risks={len(output.get('risk',{}).get('risks',[]))}")
    print(f"Saved: {a.output}")

if __name__=="__main__":
    main()
