"""B planning/risk entry point with the published Round 1 decisions applied.

Call run(request, context) with the regular B inputs plus context["evidence_library"].
The library must include the official Round 1 answers as a SPONSOR_ANSWER document.
"""
from harbourline.contracts import validate
from harbourline.sources import EvidenceLibrary
from modules.member_b.adapter import run as original_run


def run(request, context):
    result = original_run(request, context)
    if result["status"] not in ("SUCCESS", "PARTIAL"):
        return result
    library = EvidenceLibrary(context["evidence_library"])
    if result["source_snapshot_id"] != library.bundle["b_source_mode"] or result["source_snapshot_id"] != "PACK-JAN-MAR-2027-V1":
        raise ValueError("Round 1 revision requires the course Data Pack")
    documents = [doc for doc in library.documents if doc["source_type"] == "SPONSOR_ANSWER"]
    anchors = {
        "schedule": "22 months is construction only",
        "award": "awarded on 18 December 2026",
        "start": "Site possession is Monday 4 January 2027",
        "operator": "at least three responses",
        "operator_owner": "Town Council appoints the operator",
        "access": "barrier-free access to every floor in public",
        "phasing": "contractor is responsible for the phasing plan",
        "consultation": "runs 1 to 28 February 2027",
        "consultation_owner": "Community Engagement team runs it",
        "funding": "balance from its own capital reserves",
        "grant": "60% applies to eligible cost",
    }
    refs = {}
    for key, phrase in anchors.items():
        for doc in documents:
            for index, line in enumerate(doc["lines"], 1):
                if phrase.casefold() in line.casefold():
                    refs[key] = library.ref(doc, index, index)
        if key not in refs:
            raise ValueError(f"Round 1 evidence missing: {phrase}")

    planning = result["planning"]
    work = {row["wbs_id"]: row for row in planning["wbs_items"]}
    milestones = {row["milestone_id"]: row for row in planning["milestones"]}
    risks = {row["risk_id"]: row for row in result["risk"]["risks"]}

    def cite(row, *keys):
        row["source_refs"].extend(refs[key] for key in keys)

    planning["scope_statement"] += (
        " Round 1 confirms the 22-month construction window starts at site possession. "
        "Tendering is complete and contractor design remains on the critical path. "
        "Council capital reserves fund the balance; no fundraising work package is required."
    )
    work["1.1"]["title"] = "Planning, resident consultation and contractor design"
    work["1.1"]["dictionary"]["work_description"] = (
        "Coordinate Council consultation and contractor design after contract award."
    )
    work["1.1"]["dictionary"]["deliverables"] = ["Consultation summary", "Contractor design baseline"]
    cite(work["1.1"], "award", "consultation_owner")
    design = work["1.1.2"]
    design["title"] = "Contractor design and design freeze"
    design["dictionary"]["deliverables"] = ["Design stage 2 report", "Design baseline"]
    design["dictionary"]["assumptions"] = ["Design freeze and Council acceptance remain unconfirmed."]
    cite(design, "award", "schedule")
    consultation = work["1.1.1"]
    consultation["dictionary"]["assumptions"] = ["Council summary sign-off and representation review remain open."]
    cite(consultation, "consultation", "consultation_owner")
    phasing = work["1.2.1"]
    phasing["dictionary"]["work_description"] += (
        " The contractor owns the phasing plan. Keep barrier-free access to every public floor."
    )
    cite(phasing, "phasing", "access")
    operator = work["1.3.3"]
    operator["dictionary"]["work_description"] += (
        " The Council appoints the operator separately from the construction contract, "
        "after at least three responses. Appointment date is unconfirmed."
    )
    cite(operator, "operator", "operator_owner")
    cite(work["1.4.3"], "funding", "grant")
    for mid, keys in {"M01": ("start",), "M02": ("consultation",), "M03": ("award",),
                      "M04": ("phasing", "access"), "M08": ("schedule", "start"),
                      "M12": ("operator", "operator_owner")}.items():
        cite(milestones[mid], *keys)
    milestones["M08"]["relative_timing"] += "; the 22-month construction window starts 4 Jan 2027"
    milestones["M12"]["relative_timing"] += "; Council appointment depends on at least three responses"
    for rid, keys in {"R01": ("grant",), "R02": ("access", "phasing"),
                      "R06": ("operator", "operator_owner")}.items():
        cite(risks[rid], *keys)
    decisions = [
        ("Does tendering count toward the 22 months?", "Construction only, from 4 Jan 2027. Contract awarded 18 Dec 2026.", ("schedule", "award", "start")),
        ("Who appoints the active ageing centre operator?", "The Council appoints separately and requires three responses. Appointment date remains open.", ("operator_owner", "operator")),
        ("Who plans phasing and what access is required?", "The contractor plans phasing. Public floors must remain accessible; closures remain unapproved.", ("phasing", "access")),
        ("Who runs consultation and when?", "Council Community Engagement runs consultation from 1 to 28 Feb 2027 as a design input.", ("consultation", "consultation_owner")),
        ("Who funds the remaining costs?", "Council capital reserves fund the balance. The grant covers 60% of eligible costs, subject to the grant conditions.", ("funding", "grant")),
    ]
    for number, (question, answer, keys) in enumerate(decisions, 1):
        planning["sponsor_questions"].append({
            "question_id": f"ROUND1-Q{number}", "question": question,
            "reason": "Published Round 1 sponsor decision",
            "status": "ANSWERED", "answer": answer,
            "answer_sources": [refs[key] for key in keys],
        })
    result["source_evidence"].extend(refs.values())
    result["errors"] = [{
        "code": "BASELINE_APPROVAL_PENDING",
        "message": "Round 1 answers incorporated. Completion dates, closures, operator appointment and risk estimates still require review.",
        "recoverable": True,
    }]
    for ref in refs.values():
        library.verify(ref)
    return validate(result, "B", expected_producer="B")
