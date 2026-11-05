"""Local source-provenance loader + evidence-grounded Pack reconciliation.

Only course-supplied synthetic files are read. No external services, LLMs,
Jira writes, sponsor approval, or fabricated certainty. Original seed rows stay
traceable, even if subsequently contradicted; proposed responses are advice.
"""
import csv
import hashlib
import os
from copy import deepcopy
from pathlib import Path
from pypdf import PdfReader

PACK_VERSION = "2027-04-SYNTHETIC-COURSE-PACK"
PACK_SNAPSHOT = "PACK-JAN-MAR-2027-V1"

FILES = {
    "PACK-EDC": "01_EDC_minutes_Jan-Mar2027.txt",
    "PACK-CONTRACT": "03_Contract_deliverables_schedule.csv",
    "PACK-SEED-RISK": "04_Seed_risk_register.csv",
    "PACK-CONSULTATION": "05_Resident_consultation_responses.csv",
    "PACK-LESSONS": "06_Lessons_learned_Seabreeze_Hub.txt",
    "PACK-GRANT": "07_Grant_milestone_tranche_schedule.txt",
    "PACK-JAN-PROGRESS": "02_Contractor_progress_report_Jan2027.pdf",
    "PACK-FEB-PROGRESS": "02_Contractor_progress_report_Feb2027.pdf",
    "PACK-MAR-PROGRESS": "02_Contractor_progress_report_Mar2027.pdf",
}


def resolve_pack_dir(root: Path, context: dict) -> Path:
    if context.get("data_pack_directory"):
        return Path(context["data_pack_directory"])
    if os.environ.get("HARBOURLINE_DATA_PACK_DIR"):
        return Path(os.environ["HARBOURLINE_DATA_PACK_DIR"])
    return root / "data" / "Harbourline_Data_Pack"


def load_pack_sources(pack_dir: Path) -> dict:
    """Documents indexed by (id, content version). Re-reads physical source lines."""
    if not pack_dir.is_dir():
        raise FileNotFoundError(f"Data Pack directory missing: {pack_dir}")
    result = {}
    for doc_id, filename in FILES.items():
        path = pack_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Data Pack file missing: {filename}")
        if path.suffix.lower() == ".pdf":
            pdf = PdfReader(str(path))
            if len(pdf.pages) != 1:
                raise ValueError(f"Unexpected number of pages: {filename}")
            lines = pdf.pages[0].extract_text().splitlines()
            page = 1
        else:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            page = None
        result[(doc_id, PACK_VERSION)] = {
            "document_id": doc_id, "version": PACK_VERSION,
            "source_type": "DATA_PACK", "page": page,
            "lines": lines, "filename": filename,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return result


def pack_ref(sources: dict, doc_id: str, exact_fragment: str):
    item = sources[(doc_id, PACK_VERSION)]
    for index, line in enumerate(item["lines"], 1):
        if exact_fragment in line:
            return {"document_id": doc_id, "document_version": PACK_VERSION,
                    "source_type": "DATA_PACK", "page": item["page"],
                    "line_start": index, "line_end": index,
                    "chunk_id": f"{item['filename']}#line-{index}", "quote": line.strip()}
    raise ValueError(f"Source fragment not found: {doc_id} / {exact_fragment}")


def update_plan_and_risks(planning_in: dict, risk_in: dict, sources: dict, pack_dir: Path):
    """Apply the January-March record to the *brief-only* draft.

    This is reconciliation, not autonomous planning or Sponsor's endorsement.
    Exact source line snippets are validated by A's verify_evidence.
    """
    planning, risk = deepcopy(planning_in), deepcopy(risk_in)
    ref = lambda doc, fragment: pack_ref(sources, doc, fragment)
    ev = lambda *pairs: [ref(doc,frag) for doc,frag in pairs]
    work = {row["wbs_id"]: row for row in planning["wbs_items"]}
    milestones = {row["milestone_id"]: row for row in planning["milestones"]}
    questions = {row["question_id"]: row for row in planning["sponsor_questions"]}

    planning["scope_statement"] = (
        "COURSE DATA PACK BASELINE (not Sponsor-approved): D&B contract awarded 18 Dec 2026 "
        "at S$16.42m, plus estimated S$0.90m consultancy/authority fees outside contract; "
        "approved project budget S$18.5m. Site possession 4 Jan 2027; contractor's "
        "baseline targets practical completion 31 Dec 2028, but contract D22 requires "
        "31 Oct 2028 and Sponsor's brief requires fully open Q4 2028 (UNRECONCILED). "
        "Grant is 60% of eligible costs only, capped at S$17m (maximum S$10.2m); "
        "food court and rooftop garden excluded. Asbestos confirmed in level 2 west wing; "
        "phasing/closures, childcare month-18 handover versus contractor month-20, operator "
        "appointment, roof strengthening and grant-gate approvals remain unresolved. "
        "The Jan-Mar status evidence is historical, not a live November 2026 status update."
    )

    question_updates = {
        "Q01": ("Will the Sponsor approve the contractor's 31 Dec 2028 baseline despite contract D22's 31 Oct 2028 date and the 22-month/full-Q4-2028 commitments?", "Start date is now evidenced, but different completion commitments remain unreconciled."),
        "Q02": ("Will Council and NRF approve necessary lift/sports hall/food-court closures, or fund a priced temporary-access alternative preserving barrier-free access?", "EDC has not approved closures; NRF requires written consent for loss of access."),
        "Q03": ("Who owns each NRF grant tranche gate, what is the eligible-cost reconciliation, and when will T2 operator agreements be signed?", "Grant letter is available; eligible costs and operator-dependent gate remain unresolved."),
        "Q04": ("Who will be appointed as the active ageing operator after the EOI extension to 30 April 2027, and who will sign D14?", "Only one EOI response; D14 owner is blank."),
        "Q05": ("Can the childcare handover be advanced from contractor month 20 (Aug 2028) to contractual 30 Jun 2028/month 18, with enough licensing time for Jan 2029 intake?", "Operator requirement and contractor programme conflict."),
        "Q06": ("Is the approximately S$1.18m difference between budget, contract and estimated external fees contingency, and what variation approval limits apply?", "EDC 7 Jan explicitly recorded no decision on contingency."),
        "Q07": ("What temporary facility arrangements and resident access constraints are approved for 14-week lift, 10-week sports hall and 6-week food court closures?", "KHB proposed closures but Council did not approve them."),
        "Q08": ("When will the 214-response consultation summary be approved, and how will multilingual and senior representation bias be assessed?", "Summary deferred; source comments have diverse languages and may need fairness review."),
        "Q09": ("How will TOP, floor handover, commissioning and grant T3 evidence be sequenced against the conflicting October/December completion dates?", "TOP is a separate NRF funding gate."),
    }
    for qid, (question, reason) in question_updates.items():
        questions[qid].update(question=question,reason=reason)
    for qid,question,reason in [
        ("Q10","Who will authorise asbestos removal variation and sequencing, and how will its critical-path impact be evaluated?", "Confirmed chrysotile contamination; variation and sequence not agreed."),
        ("Q11","Will the rooftop garden proceed with required slab strengthening or be deferred, and how does that affect grant eligibility and contract scope?", "No sponsor decision on deferral; strengthening cost unpriced."),
        ("Q12","Who will correct seed risk register R06's arithmetic, R08's incorrect Closed status, and assign unowned or departed risk owners?", "Inherited risk register is obsolete and contains errors."),
    ]:
        planning["sponsor_questions"].append({"question_id":qid,"question":question,
            "reason":reason,"status":"OPEN","answer":None,"answer_sources":[]})

    def amend_wbs(wid, description, support, *, owner=None, assumptions=None, predecessors=None):
        row=work[wid]
        row["dictionary"]["work_description"] = description
        row["source_refs"].extend(support)
        if owner is not None:
            row["dictionary"]["owner"] = owner
        if assumptions:
            row["dictionary"]["assumptions"].extend(assumptions)
        if predecessors is not None:
            row["predecessor_wbs_ids"] = predecessors

    amend_wbs("1.1.2", "D&B contract awarded to Kestrel Harbour Builders for S$16.42m on 18 Dec 2026; design stage 2 remains overdue. Baseline submission does not imply Council approval.", ev(("PACK-EDC","1.1 Contract award."),("PACK-CONTRACT","D04,Design stage 2 report")), owner="KHB (contract); Council acceptance to confirm")
    amend_wbs("1.1.1", "Consultation held 1–28 Feb 2027 with 214 responses; committee summary overdue, representation and fairness review not complete.", ev(("PACK-EDC","5.3 Resident consultation closed"),("PACK-EDC","6.4 Consultation summary postponed")), owner="Community Engagement (recorded)")
    amend_wbs("1.2.1", "Council requires continued Hub access, but proposed east lift core closure 14 weeks, sports hall 10 weeks and food court 6 weeks are unapproved; NRF requires barrier-free access or written exception.", ev(("PACK-EDC","3.1 KHB phasing plan received"),("PACK-GRANT","5.1 Barrier-free access must be maintained")), assumptions=["Sponsor/NRF closure decisions outstanding"])
    amend_wbs("1.2.2", "East core lift work requires 14-week access interruption unless temporary lift approved; Council decision outstanding and temporary lift unpriced.", ev(("PACK-EDC","replacing the two lifts in the east core"),("PACK-JAN-PROGRESS","Temporary lift for east core closure")))
    amend_wbs("1.2.3", "M&E replacement and level-2 risers depend on approved asbestos remediation sequence, plus roof/access coordination.", ev(("PACK-MAR-PROGRESS","Critical path affected via level 2 M&E risers.")), predecessors=["1.2.1","1.2.4"])
    amend_wbs("1.3.2", "Childcare handover D21 contract due 30 Jun 2028, but contractor programme shows August 2028; operator seeks enough time for Jan 2029 intake.", ev(("PACK-CONTRACT","D21,Childcare floor handover"),("PACK-EDC","4.3 Ms Teo (by email")), owner="KHB for floor; operator Little Harbour Learning", assumptions=["Timing conflict requires Sponsor decision"])
    amend_wbs("1.3.3", "Active-ageing operator appointment overdue; EOI extended to 30 Apr after one response; agreement D14 has no named owner.", ev(("PACK-EDC","4.4 Active ageing operator EOI"),("PACK-CONTRACT","D14,Active ageing operator agreement")), assumptions=["Operator fit-out must remain provisional"])
    amend_wbs("1.3.5", "Rooftop garden is still brief scope, not removed. Roof strengthening required, cost unpriced, deferral discussed but not approved.", ev(("PACK-EDC","5.2 Structural engineer's note"),("PACK-EDC","6.3 A proposal to defer")), predecessors=["1.2.1","1.3.6"])
    amend_wbs("1.4.2", "EDC moved to fortnightly meetings in February with written updates on alternate weeks; NRF monthly reports due by 10th working day and require milestones, eligible expenditure, grants and top five risks.", ev(("PACK-EDC","2.3 To reduce load"),("PACK-GRANT","3.1 A monthly progress report")), assumptions=["EDC update cadence vs brief weekly meeting requirement must be reconciled"])
    amend_wbs("1.4.1", "TOP, licence, phased/final commissioning and practical completion; do not choose between D22 31 Oct 2028 and contractor 31 Dec 2028 without approval.", ev(("PACK-CONTRACT","D22,Practical completion"),("PACK-GRANT","T3      | 30%")), assumptions=["Conflicting completion dates remain unresolved"])

    def add_work(wid,parent,title,scope_id,description,deliverables,links,preds=()):
        planning["wbs_items"].append({"wbs_id":wid,"parent_wbs_id":parent,"title":title,
            "level":3,"dictionary":{"work_description":description,"deliverables":deliverables,
            "acceptance_criteria":[],"exclusions":[],"assumptions":["Human approval required before baseline update"],"owner":None},
            "scope_ids":[scope_id],"predecessor_wbs_ids":list(preds),"source_refs":links,"status":"UNRESOLVED"})
    add_work("1.2.4","1.2","Asbestos specialist survey, licensed removal and site clearance","S06",
        "Chrysotile confirmed in level 2 ceiling boards; licensed removal and variation pending.",
        ["Approved hazardous works sequence", "Clearance certificates"],ev(("PACK-EDC","6.5 Asbestos survey confirmed"),("PACK-MAR-PROGRESS","Licensed removal contractor required")),["1.2.1"])
    add_work("1.3.6","1.3","Rooftop structural reinforcement decision and execution","S05",
        "Engineer requires roof slab strengthening; price and proceed/defer decision outstanding.",
        ["Roof load verification", "Approved strengthening or deferral decision"],ev(("PACK-EDC","5.2 Structural engineer's note")),["1.2.1"])
    add_work("1.4.3","1.4","NRF grant conditions and tranche claims","S10",
        "Monitor T1 baseline submission, T2 signed agreements/rough-in, T3 TOP, T4 six-month operation and utilisation report.",
        ["Grant gate tracking", "Evidence packs", "Claims and approvals"],ev(("PACK-GRANT","T2      | 30%"),("PACK-GRANT","T3      | 30%")),["1.4.2"])

    def amend_m(mid,title,timing,date,pre,links,status):
        m=milestones[mid]
        m.update(title=title,relative_timing=timing,calendar_date=date,
                 predecessor_milestone_ids=list(pre),status=status)
        m["source_refs"].extend(links)

    amend_m("M01","Site possession and start of contract works","Recorded actual 4 Jan 2027; not a Sponsor-approved programme baseline", "2027-01-04",["M03"],ev(("PACK-EDC","Site possession given Monday 4 January 2027.")),"CONFIRMED")
    amend_m("M02","Resident consultation responses closed","Completed 28 Feb 2027; summary still overdue", "2027-02-28",["M01"],ev(("PACK-EDC","5.3 Resident consultation closed")),"CONFIRMED")
    amend_m("M03","D&B contract award","Awarded 18 Dec 2026; not equivalent to design baseline approval", "2026-12-18",[],ev(("PACK-EDC","1.1 Contract award.")),"CONFIRMED")
    amend_m("M04","Council/NRF closure and phasing approval","Phasing submitted 1 Feb 2027; actual approval not recorded",None,["M01"],ev(("PACK-EDC","3.1 KHB phasing plan received")),"UNRESOLVED")
    amend_m("M05","Lift/M&E completion and safe accessibility evidence","After remediation and Council/NRF clearance; no approved date",None,["M04","M10"],ev(("PACK-MAR-PROGRESS","Critical path affected via level 2 M&E risers.")),"UNRESOLVED")
    amend_m("M06","Community facilities ready for commissioning","After operator and roof decisions; timing unconfirmed",None,["M04","M15"],ev(("PACK-EDC","6.3 A proposal to defer")),"UNRESOLVED")
    amend_m("M07","Childcare floor handover for fit-out","D21 contractual due 30 Jun 2028 vs contractor programme month 20 / Aug 2028 (unreconciled)",None,["M04"],ev(("PACK-CONTRACT","D21,Childcare floor handover"),("PACK-EDC","month 20 (August 2028)")),"UNRESOLVED")
    amend_m("M08","Practical completion / acceptance","D22 due 31 Oct 2028 versus contractor baseline 31 Dec 2028; Sponsor reconciliation needed",None,["M05","M06","M07","M14"],ev(("PACK-CONTRACT","D22,Practical completion"),("PACK-MAR-PROGRESS","Contract completion date (baseline): 31 December 2028.")),"UNRESOLVED")
    amend_m("M09","Hub fully open","Brief target Q4 2028, does not prove occupancy/TOP or operator readiness",None,["M08","M13"],ev(("PACK-GRANT","Temporary Occupation Permit (TOP)")),"UNRESOLVED")
    def add_milestone(mid,title,timing,date,pre,work_ids,links,status="UNRESOLVED"):
        planning["milestones"].append({"milestone_id":mid,"title":title,"relative_timing":timing,
            "calendar_date":date,"predecessor_milestone_ids":list(pre),
            "related_wbs_ids":list(work_ids),"source_refs":links,"status":status})
    add_milestone("M10","Asbestos confirmed in 25 Mar EDC","Chrysotile confirmed in EDC meeting; removal approval outstanding", "2027-03-25",["M01"],["1.2.4"],ev(("PACK-EDC","6.5 Asbestos survey confirmed")),"CONFIRMED")
    add_milestone("M11","NRF Tranche 1 claim submitted","Claim submitted 19 Mar 2027 (receipt/release not verified)","2027-03-19",["M01"],["1.4.3"],ev(("PACK-EDC","6.1 NRF Tranche 1 claim submitted")),"CONFIRMED")
    add_milestone("M12","Operator agreements signed for T2 gate","D13 and D14 planned 30 Jun 2027; D14 owner unknown",None,["M03"],["1.3.2","1.3.3","1.4.3"],ev(("PACK-GRANT","agreements for ALL social service spaces"),("PACK-CONTRACT","D14,Active ageing operator agreement")))
    add_milestone("M13","Whole-building TOP for NRF T3","Subject to authority approval; date unresolved",None,["M05","M06"],["1.4.1","1.4.3"],ev(("PACK-GRANT","Temporary Occupation Permit (TOP)")))
    add_milestone("M14","Contract-versus-programme reconciliation approved","Before rebaselining handover or completion",None,["M01"],["1.4.1"],ev(("PACK-EDC","4.2 The Chair queried")))
    add_milestone("M15","Rooftop garden scope/strengthening decision","Sponsor and possibly NRF written approval as required",None,["M01"],["1.3.5","1.3.6"],ev(("PACK-EDC","6.3 A proposal to defer")))
    add_milestone("M16","Asbestos variation and licensed removal authorised","After confirmation and specialist approval, date unknown",None,["M10"],["1.2.4"],ev(("PACK-MAR-PROGRESS","Variation to be submitted.")))
    add_milestone("M17","Consultation summary approved","Responses closed; report postponed until subsequent EDC",None,["M02"],["1.1.1"],ev(("PACK-EDC","6.4 Consultation summary postponed")))

    # Historical register: retain ALL inherited IDs and input provenance; never
    # silently 'correct' a conflicting row or turn a realised incident into forecast.
    risk_path=pack_dir / FILES["PACK-SEED-RISK"]
    with risk_path.open(encoding="utf-8-sig",newline="") as f:
        f.readline()  # an explanatory one-line comment precedes CSV header
        seed=list(csv.DictReader(f))

    mapping = {
        "R01":(["1.4.3"],["M11","M12","M13"],"Grant eligible costs capped at S$17m, maximum S$10.2m; prior listed owner left Council."),
        "R02":(["1.2.1","1.2.2"],["M04","M08"],"Unapproved closures mean work cannot proceed as programmed."),
        "R03":(["1.2.1","1.3.1"],["M04"],"Noise complaints risk; survey representation needs monitoring."),
        "R04":(["1.2.1","1.3.1"],["M04"],"POTENTIAL DUPLICATE OF R03; do not double count."),
        "R05":(["1.3.2"],["M07","M12"],"Operator enrolment and handover deadlines conflict."),
        "R06":(["1.3.3","1.4.3"],["M12"],"EOI extended and grant T2 agreements at risk; historic score 6 disagrees with 2×4=8."),
        "R07":(["1.2.3"],["M05"],"Older building and sprinkler mains surprise."),
        "R08":(["1.2.4","1.2.3"],["M10","M16"],"CONFIRMED ISSUE: chrysotile present; historic Closed status is false as of March 2027."),
        "R09":(["1.1.2","1.4.1"],["M08"],"Unallocated contingency and variation exposure."),
        "R10":(["1.4.1"],["M13"],"TOP/licensing approval lag."),
        "R11":(["1.2.1","1.2.2"],["M04","M05"],"NRF condition requires accessible public floors unless written exception."),
        "R12":(["1.3.5","1.3.6"],["M15"],"Roof strengthening needed; not yet priced."),
        "R13":(["1.2.1","1.2.4"],["M04","M16"],"Live-site work and asbestos remediation interface."),
        "R14":(["1.4.2","1.4.3"],["M11"],"Committee now meets fortnightly; grant is monthly, late reports could delay funding."),
    }
    extra_source = {
        "R01": ev(("PACK-GRANT","Maximum grant S$10.2 million.")),
        "R02": ev(("PACK-MAR-PROGRESS","Closures still not accepted by Council.")),
        "R03": ev(("PACK-LESSONS","31 formal noise complaints")),
        "R04": ev(("PACK-SEED-RISK","R03,Stakeholder")),
        "R05": ev(("PACK-EDC","month 20 (August 2028)")),
        "R06": ev(("PACK-EDC","4.4 Active ageing operator EOI"),("PACK-GRANT","agreements for ALL social service spaces")),
        "R07": ev(("PACK-JAN-PROGRESS","Existing sprinkler mains in worse condition")),
        "R08": ev(("PACK-EDC","6.5 Asbestos survey confirmed"),("PACK-MAR-PROGRESS","Asbestos (chrysotile) confirmed.")),
        "R09": ev(("PACK-EDC","No decision recorded.")),
        "R10": ev(("PACK-GRANT","Temporary Occupation Permit (TOP)")),
        "R11": ev(("PACK-GRANT","5.1 Barrier-free access must be maintained")),
        "R12": ev(("PACK-EDC","5.2 Structural engineer's note")),
        "R13": ev(("PACK-EDC","Works in that zone stopped")),
        "R14": ev(("PACK-EDC","2.3 To reduce load"),("PACK-GRANT","Two consecutive late or incomplete reports")),
    }
    refreshed=[]
    for entry in seed:
        rid=entry["risk_id"]
        links, mlinks, update=mapping[rid]
        historic_p=int(entry["likelihood_1to5"])
        historic_i=int(entry["impact_1to5"])
        historic_s=int(entry["score"])
        special = rid in ("R08", "R06", "R01", "R11")
        prob = None if special else historic_p
        imp = None if special else historic_i
        score = None if special else prob * imp
        old_owner=entry["owner"]
        owner = None if not old_owner or "left Council" in old_owner else old_owner
        description = (
            f"LEGACY SEED (June 2025): {entry['description']} [status={entry['status']}; "
            f"P={historic_p}, I={historic_i}, recorded score={historic_s}; owner={old_owner or 'UNASSIGNED'}]. "
            f"CURRENT PACK UPDATE: {update} "
            "Current rating is still pending owner/human reassessment; inherited scores are not evidence of current probability."
        )
        refreshed.append({"risk_id":rid,"title":entry["description"],"description":description,
            "probability":prob,"impact":imp,"score":score,"owner":owner,
            "trigger":"Review after current issue or predecessor milestone status changes; precise threshold to be confirmed",
            "response_plan":entry["mitigation"]+"; re-evaluate using 2027 evidence, assign accountable owner and escalate overdue decisions",
            "related_wbs_ids":links,"related_milestone_ids":mlinks,
            "source_refs": ev(("PACK-SEED-RISK",rid+","))+extra_source[rid],
            "status":"UNRESOLVED" if special else "MONITORING"})
    # Clear explicit *new* risk/issue items, noncolliding with seed identifiers.
    refreshed.extend([
        {"risk_id":"R15","title":"Childcare handover and licensing gap",
         "description":"CONFLICT: D21 due 30 Jun 2028 vs August 2028 programme; Little Harbour Learning needs licensing lead time to Jan 2029 intake. Likelihood not reassessed.",
         "probability":None,"impact":None,"score":None,"owner":"Council PM / KHB (roles; confirmation pending)",
         "trigger":"Contractor refuses revised handover or licensing schedule misses requirement",
         "response_plan":"Sponsor resolve handover milestone; get licensing critical-path evidence",
         "related_wbs_ids":["1.3.2","1.4.1"],"related_milestone_ids":["M07","M08"],
         "source_refs":ev(("PACK-CONTRACT","D21,Childcare floor handover"),("PACK-EDC","4.3 Ms Teo (by email")),"status":"UNRESOLVED"},
        {"risk_id":"R16","title":"Completion date commitments conflict",
         "description":"CONFLICT: contract D22 31 Oct 2028 vs contractor 31 Dec 2028, with brief fully-open Q4 2028. A later finish is not approved.",
         "probability":None,"impact":None,"score":None,"owner":"Council Project Manager (recorded role)",
         "trigger":"Council rejects contractor baseline or NRF completion extension required",
         "response_plan":"Formal baseline reconciliation; protect approvals and stakeholder communication",
         "related_wbs_ids":["1.4.1"],"related_milestone_ids":["M08","M09","M14"],
         "source_refs":ev(("PACK-CONTRACT","D22,Practical completion"),("PACK-MAR-PROGRESS","Contract completion date (baseline): 31 December 2028.")),"status":"UNRESOLVED"},
        {"risk_id":"R17","title":"NRF T2 delayed by missing social service operator agreements",
         "description":"Funding dependency is explicit: signed ALL operator agreements plus rough-in. Active-ageing operator not appointed at 25 March.",
         "probability":None,"impact":None,"score":None,"owner":"Council Finance Manager (recorded role)",
         "trigger":"Operator agreement incomplete when structural/M&E rough-in reaches gate",
         "response_plan":"Track D13/D14 and responsible owners; escalate EOI outcome",
         "related_wbs_ids":["1.3.3","1.4.3"],"related_milestone_ids":["M12"],
         "source_refs":ev(("PACK-EDC","6.2 Ms Ong drew attention"),("PACK-GRANT","agreements for ALL social service spaces")),"status":"UNRESOLVED"}
    ])
    risk["risks"] = refreshed

    # Only quantities grounded in actual reports are used. Upper-bound what-if
    # assumes no float; NOT a forecast of finished-project schedule impact.
    risk["scenarios"] = [
        {"scenario_id":"SC01","description":"Confirmed asbestos: upper-bound critical-path sensitivity",
         "assumptions":["Chrysotile presence is CONFIRMED; removal estimate in Mar report is S$0.35–0.60m and 4–6 weeks",
            "Use source upper bounds of S$600,000 and 6 weeks (42 calendar days); no cost beyond removal is added",
            "Conditional schedule effect assumes full 6 weeks propagates through critical path with zero recovery; actual end-date impact unproven",
            "Variation remains pending and estimate is not approved"],
         "baseline_id":"KHB-2027-02-24-UNAPPROVED", "schedule_impact_days":42,"cost_impact_sgd":600000,
         "calculation_basis":"March contractor report: 4–6 weeks removal, S$350k–600k variation estimate; 6 × 7 = 42 calendar days (conditional maximum, NOT guaranteed project slip).",
         "affected_wbs_ids":["1.2.4","1.2.3","1.4.1"],"affected_risk_ids":["R08","R13","R16"],
         "source_refs":ev(("PACK-MAR-PROGRESS","estimate S$0.35–0.60M, 4–6 weeks."),("PACK-MAR-PROGRESS","Critical path affected via level 2 M&E risers.")),
         "estimate_status":"QUANTIFIED_ASSUMPTION"},
        {"scenario_id":"SC02","description":"Lift closures not approved: conditional schedule sensitivity",
         "assumptions":["Contractor forecasts 6–8 weeks delay IF lift works cannot start Jun 2027",
            "Upper bound 8 × 7 = 56 calendar days assumes none of the delay can be recovered",
            "Temporary lift and access mitigation have not been priced; cost is unknown"],
         "baseline_id":"KHB-2027-02-24-UNAPPROVED", "schedule_impact_days":56,"cost_impact_sgd":None,
         "calculation_basis":"March contractor report: conditional delay estimate 6–8 weeks; 8 × 7 = 56 days; no reliable cost quote.",
         "affected_wbs_ids":["1.2.1","1.2.2","1.4.1"],"affected_risk_ids":["R02","R11","R16"],
         "source_refs":ev(("PACK-MAR-PROGRESS","KHB estimates 6–8 weeks of delay"),("PACK-EDC","3.2 The Chair stated")),
         "estimate_status":"QUANTIFIED_ASSUMPTION"},
        {"scenario_id":"SC03","description":"Childcare handover month-18 vs month-20 conflict",
         "assumptions":["D21 contractual date 30 Jun 2028; contractor's programme indicates month 20 (August 2028)",
            "August day not specified, so exact gap cannot be computed faithfully",
            "Cost and recovery actions not priced; only milestone mismatch is identified"],
         "baseline_id":"KHB-2027-02-24-UNAPPROVED", "schedule_impact_days":None,"cost_impact_sgd":None,
         "calculation_basis":"Date conflict between D21 contract and EDC record; no exact August day, float or fit-out cost supplied.",
         "affected_wbs_ids":["1.3.2","1.4.1"],"affected_risk_ids":["R05","R15","R16"],
         "source_refs":ev(("PACK-CONTRACT","D21,Childcare floor handover"),("PACK-EDC","month 20 (August 2028)")),
         "estimate_status":"UNRESOLVED"},
    ]
    return planning,risk
