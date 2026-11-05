"""Planning/risk change impact review; advisory only, no Jira writes."""
from hashlib import sha256
import json

# Changes are NOT treated as approved factual events without human-provided evidence.
LINKS = {
    "LIFT_DELAY":(["1.2.2","1.4.1"],["M05","M08","M09"],["R03","R06"]),
    "CHILDCARE_CHANGE":(["1.3.2","1.4.1"],["M07","M08","M09"],["R02","R06"]),
    "GRANT_CHANGE":(["1.4.2"],["M08"],["R04"]),
    "OPERATOR_CHANGE":(["1.3.3"],["M06","M08","M09"],["R05","R06"]),
    "ACCESS_CHANGE":(["1.2.1","1.2.2","1.2.3"],["M04","M05","M08","M09"],["R01","R03","R07"]),
    # Simulation-pack linked events; no approvals are claimed by this mapping.
    "ASBESTOS_CONFIRMED":(["1.2.4","1.2.3","1.4.1"],["M10","M16","M05","M08"],["R08","R13","R16"]),
    "CHILDCARE_HANDOVER_CONFLICT":(["1.3.2","1.4.1"],["M07","M08","M14"],["R05","R15","R16"]),
    "GRANT_T2_GATE":(["1.3.3","1.4.3"],["M12"],["R01","R06","R17"]),
    "ROOFTOP_SCOPE_DECISION":(["1.3.5","1.3.6"],["M15","M06"],["R12"]),
}


def analyse_change(event: dict, planning: dict, risk: dict) -> dict:
    """Produce a review queue for A's governance layer, not a modified baseline."""
    kind=event.get("change_type")
    event_id=event.get("event_id")
    if not kind or not event_id:
        raise ValueError("change_type and event_id are required")
    if kind not in LINKS:
        return {"event_id":event_id,"change_type":kind,"status":"UNCLASSIFIED_REVIEW_REQUIRED",
                "stale_wbs_ids":[],"stale_milestone_ids":[],"stale_risk_ids":[],
                "stale_reports":["WEEKLY_COMMITTEE","MONTHLY_GRANT"],
                "human_actions":["Human must classify change and verify supporting source before updating baseline"],
                "approved":False}
    w,m,r=LINKS[kind]
    known_w={x["wbs_id"] for x in planning["wbs_items"]}
    known_m={x["milestone_id"] for x in planning["milestones"]}
    known_r={x["risk_id"] for x in risk["risks"]}
    return {"event_id":event_id,"change_type":kind,"status":"REVIEW_REQUIRED",
            "stale_wbs_ids":[x for x in w if x in known_w],
            "stale_milestone_ids":[x for x in m if x in known_m],
            "stale_risk_ids":[x for x in r if x in known_r],
            "stale_reports":["WEEKLY_COMMITTEE","MONTHLY_GRANT"],
            "change_digest":sha256(json.dumps(event,sort_keys=True).encode()).hexdigest(),
            "human_actions":["Verify change evidence and Sponsor authority",
                "Reassess affected WBS and milestone dependencies",
                "Re-score affected risks and re-run what-if after assumptions are approved",
                "Have C regenerate stale reports, pass Critic, then seek human checkpoint",
                "Have A approve proposed Jira updates before write/read-back"],
            "approved":False}
