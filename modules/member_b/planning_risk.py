"""Source-grounded *deterministic* Harbourline planning/risk draft engine.

This is a working, zero-cost local baseline, NOT an LLM agent, a Jira writer,
Sponsor approval, nor evidence of official plan/risk estimates. Scores and
what-if parameters are transparent proposals until accepted by a human.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from time import monotonic

from harbourline.contracts import ContractError, validate, verify_evidence

ROOT = Path(__file__).resolve().parents[2]
DOC_ID = "HARBOURLINE-BRIEF"
DOC_VERSION = "2026-10-10"
DEFAULT_SOURCE = ROOT / "data" / "brief_source_registry.json"


def load_sources(path=None):
    """Load locally held, versioned source material; never invent missing records."""
    path = Path(path or os.environ.get("HARBOURLINE_SOURCE_REGISTRY") or DEFAULT_SOURCE)
    if not path.is_file():
        raise FileNotFoundError(f"Source registry missing: {path}")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Source registry must be a list")
    indexes = {}
    for item in records:
        key = (item["document_id"], item["version"])
        if key in indexes:
            raise ValueError("Duplicate source ID/version")
        indexes[key] = item
    return indexes


def _brief(indexes):
    key = (DOC_ID, DOC_VERSION)
    if key not in indexes:
        raise ValueError("Official project brief and version are not loaded")
    item = indexes[key]
    if item.get("source_type") != "BRIEF" or item.get("page") != 3:
        raise ValueError("Unexpected brief source metadata")
    lines = item.get("lines", [])
    if not lines or not all(isinstance(line, str) for line in lines):
        raise ValueError("Brief source lines are missing")
    # A minimal integrity check against the specific course brief excerpt.
    for fragment in ("Scope. The refurbished Hub will include:",
                     "an upgraded multi-purpose sports hall", "central grant released in tranches",
                     "Harbour Learning wishes to begin enrolment in month 18."):
        if fragment not in "\n".join(lines):
            raise ValueError(f"Expected brief excerpt missing: {fragment}")
    return item


def _ref(source, fragment):
    for number, line in enumerate(source["lines"], start=1):
        if fragment in line:
            return {"document_id": source["document_id"],
                    "document_version": source["version"],
                    "source_type": "BRIEF", "page": source["page"],
                    "line_start": number, "line_end": number,
                    "chunk_id": f"p3-l{number}", "quote": line.strip()}
    raise ValueError(f"Required supporting quotation not found: {fragment}")


def _dictionary(description, deliverables, assumptions=(), acceptance=()):
    return {"work_description": description, "deliverables": list(deliverables),
            "acceptance_criteria": list(acceptance), "exclusions": [],
            "assumptions": list(assumptions), "owner": None}


def make_bundles(source):
    """Fixed transparent draft based *only* on verified Harbourline brief lines.

    Additional Data Pack facts and Sponsor answers must be merged after independent
    evidence review. A design proposal is explicitly not presented as sponsor fact.
    """
    r = lambda fragment: [_ref(source, fragment)]
    scope_specs = [
        ("S01", "Sports hall upgrade", "an upgraded multi-purpose sports hall"),
        ("S02", "Early childhood centre (~100 children)", "a new early childhood centre for about 100 children"),
        ("S03", "Active ageing centre", "an active ageing centre, operator to be appointed"),
        ("S04", "Community kitchen and food court", "a community kitchen and food court refresh"),
        ("S05", "Rooftop community garden", "a rooftop community garden"),
        ("S06", "Barrier-free access, lifts and M&E replacement", "full barrier-free access, new lifts and replacement of M&E systems"),
        ("S07", "Maintain community access during works", "residents throughout the works. Residents will be consulted"),
        ("S08", "Resident design consultation", "residents throughout the works. Residents will be consulted"),
        ("S09", "Design-and-build procurement", "Delivery. We intend a single design-and-build contract"),
        ("S10", "Grant and committee reporting", "Reporting. The Estate Development Committee meets weekly"),
    ]
    scope = [{"scope_id": id_, "title": title,
              "description": f"Brief-supported intended scope: {title}; technical specifications and acceptance criteria remain open.",
              "status": "IN_SCOPE", "source_refs": r(fragment)}
             for id_,title,fragment in scope_specs]

    question_specs = [
        ("Q01", "What is the approved commencement date, and how are 22 months of works reconciled with opening in Q4 2028?", "22-month duration and Q4 2028 deadline do not specify a compatible start date."),
        ("Q02", "How can the Hub remain open throughout construction while lifts and M&E are replaced? What phasing, closure allowances and safety constraints are approved?", "Continuity of public access and intrusive work require an agreed phasing/safety plan."),
        ("Q03", "Which grant milestones, evidence, tranche sizes and release conditions apply?", "The brief explicitly says grant conditions will follow."),
        ("Q04", "Who is the appointed active ageing centre operator, and when must their requirements be frozen?", "Operator is not yet appointed."),
        ("Q05", "Does 'enrolment in month 18' require the childhood centre to be licensed and operational then, or only to accept applications?", "Enrolment preference is not a confirmed occupancy milestone."),
        ("Q06", "What is the agreed baseline for detailed cost allocations, contingency, float and procurement lead times?", "Only the total approved budget is known."),
        ("Q07", "What accommodation and access arrangements are agreed with the current sports hall, tuition and food-court occupiers?", "Existing leases/licences and continued access may conflict with work phasing."),
        ("Q08", "What resident consultation method, accessibility criteria and sign-off authority will be used?", "Acceptance standards and decision authority are not specified."),
        ("Q09", "What is the approved commissioning, statutory approvals and safe occupancy sequence for each facility?", "Readiness and opening criteria are not yet specified."),
    ]
    questions = [{"question_id": id_, "question": q, "reason": reason,
                  "status": "OPEN", "answer": None, "answer_sources": []}
                 for id_,q,reason in question_specs]

    work = []
    def add(id_, parent, title, scopes, evidence, description, deliverables, predecessors=(), assumptions=(), acceptance=()):
        level = id_.count(".") + 1
        work.append({"wbs_id": id_, "parent_wbs_id": parent, "title": title, "level": level,
                     "dictionary": _dictionary(description, deliverables, assumptions, acceptance),
                     "scope_ids": list(scopes), "predecessor_wbs_ids": list(predecessors),
                     "source_refs": r(evidence), "status": "PROPOSED"})

    add("1",None,"Harbourline Community Hub Refurbishment",[s[0] for s in scope_specs],
        "Objectives. Refurbish the Hub", "Proposed overall decomposition; not an approved baseline.", ["Refurbished community hub"])
    add("1.1","1","Planning, consultation and procurement",["S08","S09"],
        "Delivery. We intend a single design-and-build contract", "Pre-construction workstreams (proposed).", ["Consultation and contract package"])
    add("1.1.1","1.1","Resident consultation and design inputs",["S08"],
        "residents throughout the works. Residents will be consulted", "Collect and review resident input for design.", ["Consultation record", "Design inputs"],
        assumptions=["Consultation format, sample and sign-off are unconfirmed"],
        acceptance=["Consultation summary approved by authorised reviewer (pending)"])
    add("1.1.2","1.1","Design-and-build tender and design freeze",["S09"],
        "Delivery. We intend a single design-and-build contract", "Define D&B scope, procure and confirm design.", ["D&B tender", "Design baseline"],
        predecessors=["1.1.1"], assumptions=["Tender and design freeze sequence proposed; no contract award date"])
    add("1.2","1","Live-site access and core building services",["S06","S07"],
        "full barrier-free access, new lifts and replacement of M&E systems", "Phased enabling works and core infrastructure.", ["Access/phasing plan", "Building services upgrades"])
    add("1.2.1","1.2","Occupant continuity and phased work zones",["S07"],
        "residents throughout the works. Residents will be consulted", "Propose and control safe phasing while public access continues.", ["Phasing and safe access plan"],
        predecessors=["1.1.2"], assumptions=["Detailed closures and fire/evacuation controls need Sponsor approval"])
    add("1.2.2","1.2","Barrier-free access and lift replacement",["S06"],
        "full barrier-free access, new lifts and replacement of M&E systems", "Proposed accessibility and lift work package.", ["Accessible routes", "New lifts"],
        predecessors=["1.2.1"], assumptions=["Detailed lift specifications and acceptance criteria not provided"])
    add("1.2.3","1.2","M&E system replacement and testing",["S06"],
        "full barrier-free access, new lifts and replacement of M&E systems", "Proposed mechanical and electrical replacement.", ["Replacement M&E systems", "Test records"],
        predecessors=["1.2.1"], assumptions=["Outage windows and commissioning acceptance not agreed"])
    add("1.3","1","New and refreshed community facilities",["S01","S02","S03","S04","S05"],
        "Scope. The refurbished Hub will include:", "Facility fit-out workstreams.", ["Five facility packages"])
    facility_specs=[
        ("1.3.1","Sports hall upgrade","S01","an upgraded multi-purpose sports hall",["Refurbished sports hall"]),
        ("1.3.2","Early childhood centre","S02","a new early childhood centre for about 100 children",["Childcare centre fit-out"]),
        ("1.3.3","Active ageing centre","S03","an active ageing centre, operator to be appointed",["Active ageing centre fit-out"]),
        ("1.3.4","Community kitchen and food court","S04","a community kitchen and food court refresh",["Refreshed kitchen and food court"]),
        ("1.3.5","Rooftop garden","S05","a rooftop community garden",["Rooftop garden"]),
    ]
    for wid,title,sid,fragment,deliverables in facility_specs:
        add(wid,"1.3",title,[sid],fragment,f"Proposed work package: {title}; specifications unconfirmed.", deliverables,
            predecessors=["1.2.1"], assumptions=["Fit-out and licensing criteria require design/operator confirmation"])
    add("1.4","1","Commissioning, opening and grant governance",["S10","S02","S06"],
        "Reporting. The Estate Development Committee meets weekly", "Controls for reporting and readiness.", ["Governance records", "Handover evidence"])
    add("1.4.1","1.4","Commissioning, inspection and opening readiness",["S02","S06"],
        "Works are to complete within 22 months", "Coordinate proposed testing, handover and occupancy readiness.", ["Commissioning sign-offs", "Handover record"],
        predecessors=["1.2.2","1.2.3","1.3.1","1.3.2","1.3.3","1.3.4","1.3.5"],
        assumptions=["Approval and commissioning sequence not yet confirmed"])
    add("1.4.2","1.4","Grant and committee progress reporting",["S10"],
        "Reporting. The Estate Development Committee meets weekly", "Coordinate status and grant reporting.", ["Weekly committee update", "Monthly grant progress report"],
        assumptions=["Grant conditions and milestone evidence not yet supplied"])

    milestone_specs = [
        ("M01", "Resolve sponsor baseline assumptions", "Before baseline approval (no agreed dates)", [], ["1.1.1","1.1.2"], "Works are to complete within 22 months"),
        ("M02", "Resident consultation reviewed", "Before design freeze (proposed sequence)", ["M01"], ["1.1.1"], "residents throughout the works. Residents will be consulted"),
        ("M03", "D&B design and contract baseline approved", "After consultations and sponsor decisions (date TBD)", ["M02"], ["1.1.2"], "Delivery. We intend a single design-and-build contract"),
        ("M04", "Live-site phasing and access plan approved", "Before disruptive works (proposed sequence)", ["M03"], ["1.2.1"], "residents throughout the works. Residents will be consulted"),
        ("M05", "Lifts and M&E commissioning evidence complete", "Before final safe occupancy; dates TBD", ["M04"], ["1.2.2","1.2.3"], "full barrier-free access, new lifts and replacement of M&E systems"),
        ("M06", "Community facility packages ready for inspection", "Before full opening; dates TBD", ["M04"], ["1.3.1","1.3.2","1.3.3","1.3.4","1.3.5"], "Scope. The refurbished Hub will include:"),
        ("M07", "Childcare enrolment decision / readiness", "Month 18 requested by operator; NOT an approved operational date", ["M04"], ["1.3.2"], "Harbour Learning wishes to begin enrolment in month 18."),
        ("M08", "Works complete and accepted", "Within 22 months from UNCONFIRMED commencement", ["M05","M06","M07"], ["1.4.1"], "Works are to complete within 22 months"),
        ("M09", "Hub fully open", "Q4 2028 per brief; exact date and baseline alignment unresolved", ["M08"], ["1.4.1"], "quarter of 2028."),
    ]
    milestones = [{"milestone_id": id_,"title": title,"relative_timing": rel,"calendar_date": None,
                   "predecessor_milestone_ids": preds,"related_wbs_ids": wbs,
                   "source_refs":r(fragment),"status":"UNRESOLVED" if id_ in ("M01","M07","M08","M09") else "PROPOSED"}
                  for id_,title,rel,preds,wbs,fragment in milestone_specs]
    planning = {"scope_statement":
        "Proposed refurbishment of the existing Harbourline Community Hub covering six facility/service upgrades, "
        "accessibility, lifts and M&E, with design consultation, single intended design-and-build delivery, "
        "ongoing resident access, weekly committee and monthly grant reporting. Approved total budget S$18.5m; "
        "60% grant funding subject to unpublished conditions. Works target 22 months; Q4 2028 full opening; "
        "month-18 childcare enrolment is a wish, not an approved commissioning requirement. "
        "Dates, detailed design, cost splits and grant gates remain unresolved; no formal baseline approved.",
        "sponsor_questions": questions,"scope_items":scope,"wbs_items":work,"milestones":milestones}

    def risk(id_,title,description,fragment,p,i,owner,trigger,response,work_ids,mile_ids):
        # Scores are transparent preliminary analyst judgments, NOT brief facts.
        return {"risk_id":id_,"title":title,
                "description":description+" [PROPOSED 1–5 ordinal probability/impact assessment; Sponsor has NOT approved the ratings.]",
                "probability":p,"impact":i,"score":p*i,
                "owner":f"PROPOSED ROLE (not assigned): {owner}",
                "trigger":trigger,"response_plan":response,
                "related_wbs_ids":work_ids,"related_milestone_ids":mile_ids,
                "source_refs":r(fragment),"status":"OPEN"}
    risks=[
        risk("R01","Resident safety and continued access", "Active public use during intrusive works may conflict with safe zoning and fire egress.",
             "residents throughout the works. Residents will be consulted",4,5,"D&B safety/operations lead", "Approved evacuation/access routes cannot be preserved", "Seek phased-access decision and safe work-zone plan; escalate closure needs",["1.2.1","1.2.2","1.2.3"],["M04","M08"]),
        risk("R02","Childcare month-18 readiness ambiguity", "Enrolment aspiration may be mistaken for centre occupancy approval.",
             "Harbour Learning wishes to begin enrolment in month 18.",3,4,"Childcare operator liaison", "Operator requests earlier live operations or licence date", "Clarify enrolment vs opening and obtain licensing milestones",["1.3.2"],["M07","M08"]),
        risk("R03","Lift/M&E replacement disrupts programme", "End-of-life equipment and live-site replacement could cause service interruptions or programme delays.",
             "M&E plant is at end of life",3,5,"D&B M&E package lead", "Commissioning test fails or equipment delivery slips", "Request lead times, isolation plan and sequence; use approved fallback access",["1.2.2","1.2.3"],["M05","M08"]),
        risk("R04","Grant tranche conditions not available", "Unpublished tranche rules could create funding and reporting exposure.",
             "central grant released in tranches",3,5,"Sponsor finance/grant liaison", "Payment application requires unknown evidence", "Obtain grant schedule and acceptance criteria before freeze",["1.4.2"],["M03","M08"]),
        risk("R05","Active ageing operator unappointed", "Unselected operator may change fit-out requirements late.",
             "an active ageing centre, operator to be appointed",4,3,"Sponsor operator procurement liaison", "Operator appointed after design freeze", "Request appointment date; reserve human-approved change process",["1.3.3"],["M06"]),
        risk("R06","22-month schedule versus Q4 2028 opening", "Unconfirmed start and handover assumptions make schedule feasibility unresolved.",
             "Works are to complete within 22 months",3,4,"Sponsor programme lead", "Confirmed start implies completion after opening target", "Escalate baseline conflict; do not invent a start date",["1.1.2","1.4.1"],["M01","M08","M09"]),
        risk("R07","Existing occupants and phasing", "Existing leases/licences may limit disruption windows or temporary moves.",
             "tuition centre and a small food court",3,4,"Sponsor tenant/estate liaison", "Tenant access agreement conflicts with work zone plan", "Review licence obligations and consult occupants before work sequencing",["1.2.1","1.3.4"],["M04","M06"]),
    ]

    def scenario(id_,description,assumptions,days,rate,wbs,risk_ids,fragment):
        return {"scenario_id":id_,"description":description,"assumptions":assumptions,
                "baseline_id":"PROPOSED-22-MONTH-NO-START-DATE",
                "schedule_impact_days":days,"cost_impact_sgd":days*rate,
                "calculation_basis":f"ILLUSTRATIVE ONLY: {days} calendar days × S${rate:,}/day = S${days*rate:,}; "
                    "zero available float and direct critical-path propagation assumed; this is not an approved project estimate.",
                "affected_wbs_ids":wbs,"affected_risk_ids":risk_ids,
                "source_refs":r(fragment),"estimate_status":"QUANTIFIED_ASSUMPTION"}
    scenarios=[
        scenario("SC01","Lift supplier delay: critical-path sensitivity test",[
            "Hypothetical lift delivery delay: 14 calendar days (not sourced)",
            "Illustrative site extension rate: S$6,000/day (not sourced)",
            "Assume no recoverable float and project completion shifts one-for-one"],14,6000,["1.2.2","1.4.1"],["R03","R06"],"full barrier-free access, new lifts and replacement of M&E systems"),
        scenario("SC02","Early childcare fit-out rework",[
            "Hypothetical fit-out/approval delay: 21 calendar days (not sourced)",
            "Illustrative prolonged works rate: S$4,000/day (not sourced)",
            "Assume affected works are critical and no mitigation is available"],21,4000,["1.3.2","1.4.1"],["R02","R06"],"Harbour Learning wishes to begin enrolment in month 18."),
        scenario("SC03","Grant milestone evidence rework",[
            "Hypothetical reporting/evidence delay: 30 calendar days (not sourced)",
            "Illustrative carrying cost: S$1,500/day (not sourced)",
            "Assume delay prevents critical milestone acceptance; otherwise schedule impact can be zero"],30,1500,["1.4.2","1.4.1"],["R04","R06"],"central grant released in tranches"),
    ]
    return planning, {"risks":risks,"scenarios":scenarios}


def run_real(request, context):
    start = monotonic()
    output = {key:deepcopy(request[key]) for key in (
        "schema_version","run_id","project_id","source_snapshot_id","request")}
    fingerprint = hashlib.sha256((request["run_id"]+":"+request["source_snapshot_id"]).encode()).hexdigest()[:14]
    output.update({"message_id":f"B-{fingerprint}", "producer":"B","recipient":"A",
                   "operation":"PLAN_RISK","status":"PARTIAL","source_evidence":[],
                   "planning":{"scope_statement":None,"sponsor_questions":[],"scope_items":[],"wbs_items":[],"milestones":[]},
                   "risk":{"risks":[],"scenarios":[]},
                   "metrics":{"api_calls":0,"input_tokens":None,"output_tokens":None,
                              "estimated_cost_usd":None,"elapsed_seconds":None},"errors":[]})
    try:
        pack_mode = request["source_snapshot_id"] == "PACK-JAN-MAR-2027-V1"
        if request["source_snapshot_id"] not in ("BRIEF-2026-10-10-ONLY", "PACK-JAN-MAR-2027-V1"):
            raise ValueError("Unsupported source_snapshot_id; only the brief-only and course Data Pack snapshots are implemented")
        if context.get("source_snapshot_id",request["source_snapshot_id"]) != request["source_snapshot_id"]:
            raise ValueError("Context/source snapshot mismatch")
        indexes = load_sources(context.get("source_registry_path"))
        brief = _brief(indexes)
        planning, risk = make_bundles(brief)
        if pack_mode:
            from .data_pack import load_pack_sources, resolve_pack_dir, update_plan_and_risks
            pack_dir=resolve_pack_dir(ROOT,context)
            pack_sources=load_pack_sources(pack_dir)
            indexes.update(pack_sources)
            planning,risk=update_plan_and_risks(planning,risk,indexes,pack_dir)
        output["planning"],output["risk"] = planning,risk
        # B's exchange contract only allows the evidence objects, not a free-form
        # assumption register. The draft status and assumptions are explicit above.
        unique = {}
        for part in (planning["scope_items"],planning["wbs_items"],planning["milestones"],risk["risks"],risk["scenarios"]):
            for row in part:
                for ref in row["source_refs"]:
                    unique[(ref["document_id"],ref["document_version"],ref["line_start"])] = ref
        output["source_evidence"] = [unique[key] for key in sorted(unique)]
        if pack_mode:
            output["errors"] = [{"code":"SPONSOR_ANSWERS_AND_BASELINE_APPROVAL_MISSING",
               "message":"Course Data Pack reconciled (Jan-Mar 2027), but posted Sponsor answers, approvals and reconciled baseline remain absent. Legacy ratings, simulated effects and decisions are not approved.","recoverable":True}]
        else:
            output["errors"] = [{"code":"MISSING_DATA_PACK_AND_SPONSOR_ANSWERS",
               "message":"Brief-only preliminary draft; official Data Pack and Sponsor answers have not been integrated. All ratings and scenarios are transparent assumptions.","recoverable":True}]
        verify_evidence(output,{k:v["lines"] for k,v in indexes.items()})
    except (FileNotFoundError,KeyError,ValueError,TypeError) as exc:
        output["status"]="BLOCKED"
        output["errors"]=[{"code":"AUTHORITATIVE_SOURCE_UNAVAILABLE",
                           "message":f"Cannot generate grounded plan: {exc}","recoverable":True}]
    finally:
        output["metrics"]["elapsed_seconds"] = monotonic()-start
    validate(output,"B",expected_producer="B")
    return output
