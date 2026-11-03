"""Offline reproducible Member B demo; optionally exercises A/C fixture handoff.

Run: python -m modules.member_b.demo [--integrate] [--out .local/member_b_demo]
"""
import argparse
import json
from pathlib import Path
from harbourline.contracts import validate, verify_evidence
from harbourline.integration import run_handoff
from modules.member_b.adapter import run as run_b
from modules.member_b.change import analyse_change
from modules.member_b.planning_risk import ROOT, load_sources
from modules.member_c.adapter import run as run_c


def main():
    parser=argparse.ArgumentParser(description="Run Member B brief-only local baseline")
    parser.add_argument("--out",type=Path,default=Path(".local/member_b_demo"))
    parser.add_argument("--integrate",action="store_true",help="Use A handoff and C's FIXTURE adapter; NOT production reports or Jira")
    parser.add_argument("--sources",type=Path,default=None)
    parser.add_argument("--pack",action="store_true",help="Use local synthetic 2027 Jan-Mar course Data Pack (not current status)")
    parser.add_argument("--pack-dir",type=Path,default=None,help="Directory containing the nine source documents")
    args=parser.parse_args()
    req=json.loads((ROOT/"examples/member_b_request.json").read_text(encoding="utf-8"))
    if args.pack:
        req["source_snapshot_id"]="PACK-JAN-MAR-2027-V1"
    context={"source_snapshot_id":req["source_snapshot_id"]}
    if args.sources: context["source_registry_path"]=str(args.sources)
    if args.pack_dir: context["data_pack_directory"]=str(args.pack_dir)
    b=run_b(req,context)
    if b["status"]=="BLOCKED":
        raise SystemExit(f"Member B BLOCKED: {b['errors']}")
    indexes=load_sources(args.sources)
    if args.pack:
        from .data_pack import load_pack_sources,resolve_pack_dir
        indexes.update(load_pack_sources(resolve_pack_dir(ROOT,context)))
    docs={k:v["lines"] for k,v in indexes.items()}
    validate(b,"B",expected_producer="B")
    verify_evidence(b,docs)
    args.out.mkdir(parents=True,exist_ok=True)
    def write(name,data):
        (args.out/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    write("b_live_output.json",b)
    change=analyse_change({"event_id":"DEMO-NOT-A-SPONSOR-EVENT","change_type":"ASBESTOS_CONFIRMED" if args.pack else "LIFT_DELAY",
                           "description":"Hypothetical lift delivery delay for stale-output detection"},b["planning"],b["risk"])
    write("b_change_review.json",change)
    if args.integrate:
        def c_fixture_with_snapshot(request, ctx):
            # A's C fixture has a literal snapshot embedded in report records.
            # Normalise ONLY these fixture metadata fields for a schema handoff test.
            mock=run_c(request,ctx)
            for report in mock["reporting"]["reports"]:
                report["source_snapshot_id"]=request["source_snapshot_id"]
            return mock
        full, trace = run_handoff(req, lambda request, ctx:run_b(request,{**ctx,**context}),c_fixture_with_snapshot,docs)
        write("combined_demo_with_C_FIXTURE.json",full)
        write("handoff_trace.json",trace)
        print("A->B->A->C(fixture)->A handoff schema/evidence checks: PASS. NO Jira write, AI call, critic or real C reporting.")
    print(f"B: {len(b['planning']['scope_items'])} scope, {len(b['planning']['wbs_items'])} WBS, "
          f"{len(b['planning']['milestones'])} milestones, {len(b['risk']['risks'])} risks, "
          f"{len(b['risk']['scenarios'])} proposed what-if scenarios; status={b['status']}.")
    print(f"Outputs: {args.out}")

if __name__ == "__main__":
    main()
