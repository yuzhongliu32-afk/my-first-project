"""Planning/risk change impact review; advisory only, no Jira writes.

Two ID schemes exist and must not be mixed:

* BRIEF_ONLY: the deterministic draft built from the brief alone
  (planning_risk.py, risks R01-R07, no WBS 1.2.4 / 1.4.3).
* DATA_PACK: the draft amended with the course data pack (data_pack.py,
  risks R01-R17, WBS 1.2.4 / 1.3.6 / 1.4.3, milestones M10-M17).

The same risk ID means different things in the two schemes (for example R03 is
"Lift/M&E replacement disrupts programme" in BRIEF_ONLY but "Noise and dust
complaints" in DATA_PACK), so each scheme has its own link table.
"""
from hashlib import sha256
import json

# Changes are NOT treated as approved factual events without human-provided evidence.

# IDs from planning_risk.py (brief-only draft).
BRIEF_ONLY_LINKS = {
    "LIFT_DELAY": (["1.2.2", "1.4.1"], ["M05", "M08", "M09"], ["R03", "R06"]),
    "CHILDCARE_CHANGE": (["1.3.2", "1.4.1"], ["M07", "M08", "M09"], ["R02", "R06"]),
    "GRANT_CHANGE": (["1.4.2"], ["M08"], ["R04"]),
    "OPERATOR_CHANGE": (["1.3.3"], ["M06", "M08", "M09"], ["R05", "R06"]),
    "ACCESS_CHANGE": (["1.2.1", "1.2.2", "1.2.3"], ["M04", "M05", "M08", "M09"], ["R01", "R03", "R07"]),
}

# IDs from data_pack.py (brief + course data pack). Simulation-pack linked events;
# no approvals are claimed by this mapping.
DATA_PACK_LINKS = {
    "LIFT_DELAY": (["1.2.1", "1.2.2", "1.4.1"], ["M04", "M05", "M08"], ["R02", "R11", "R16"]),
    "CHILDCARE_CHANGE": (["1.3.2", "1.4.1"], ["M07", "M08"], ["R05", "R15", "R16"]),
    "GRANT_CHANGE": (["1.4.2", "1.4.3"], ["M11", "M12", "M13"], ["R01", "R14", "R17"]),
    "OPERATOR_CHANGE": (["1.3.3", "1.4.3"], ["M06", "M12"], ["R06", "R17"]),
    "ACCESS_CHANGE": (["1.2.1", "1.2.2", "1.2.3"], ["M04", "M05"], ["R02", "R11", "R13"]),
    "ASBESTOS_CONFIRMED": (["1.2.4", "1.2.3", "1.4.1"], ["M10", "M16", "M05", "M08"], ["R08", "R13", "R16"]),
    "CHILDCARE_HANDOVER_CONFLICT": (["1.3.2", "1.4.1"], ["M07", "M08", "M14"], ["R05", "R15", "R16"]),
    "GRANT_T2_GATE": (["1.3.3", "1.4.3"], ["M12"], ["R01", "R06", "R17"]),
    "ROOFTOP_SCOPE_DECISION": (["1.3.5", "1.3.6"], ["M15", "M06"], ["R12"]),
    # Week 12 course change events (memos issued 6 April 2027 in the scenario).
    # CE-01: asbestos removal ruled not grant-eligible; programme unchanged.
    "GRANT_ELIGIBILITY_RULING": (["1.2.4", "1.4.3", "1.1.2"], ["M16", "M11", "M13"],
                                 ["R01", "R08", "R09", "R13"]),
    # CE-02: sole active ageing operator respondent withdraws.
    "OPERATOR_WITHDRAWAL": (["1.3.3", "1.4.3", "1.4.2"], ["M12", "M06", "M08"],
                            ["R06", "R17", "R14", "R16"]),
}

# Convenience aliases so the Week 12 memo IDs can be passed as the change type.
ALIASES = {"CE-01": "GRANT_ELIGIBILITY_RULING", "CE-02": "OPERATOR_WITHDRAWAL"}

# Facts the reviewer needs next to the IDs. Each line names its data-pack file;
# derived arithmetic is labelled as derived. These are review notes, not approvals.
IMPACT_NOTES = {
    "GRANT_ELIGIBILITY_RULING": [
        "Grant = 60% of eligible cost, eligible cost capped at S$17.0m, maximum grant S$10.2m; "
        "food court and rooftop amenity were already ineligible (07 grant conditions s.1). "
        "Under the memo, asbestos removal and associated works join the ineligible items.",
        "Contractor estimate for licensed removal: S$0.35-0.60m and 4-6 weeks "
        "(02 March contractor report; 01 EDC minutes 5.1).",
        "Derived: budget S$18.5m - contract S$16.42m - fees S$0.90m = about S$1.18m headroom, "
        "never confirmed as contingency (01 EDC 1.1-1.2). Removal at S$0.35-0.60m would leave "
        "about S$0.58-0.83m before roof strengthening, which is unpriced and must stay UNKNOWN, "
        "not zero (01 EDC 5.2).",
        "Seed register R08 (hazardous materials) is still marked Closed although chrysotile was "
        "confirmed (04 seed risk register; 01 EDC 6.5).",
        "The memo agrees no programme change, so no new schedule delay is asserted here.",
    ],
    "OPERATOR_WITHDRAWAL": [
        "Tranche 2 (30% of the grant) requires signed operator agreements for ALL social service "
        "spaces (07 grant conditions s.2).",
        "The EOI had one response against a policy minimum of three and was extended to "
        "30 April 2027 (01 EDC 4.4); after the withdrawal there are no respondents.",
        "D14, the active ageing operator agreement due 2027-06-30, has no owner assigned "
        "(03 contract deliverables D14).",
        "The respondent cited uncertainty over opening dates, which links to the unreconciled "
        "completion dates: contract D22 31 Oct 2028 vs contractor baseline 31 Dec 2028 (R16, M08).",
        "Two consecutive late or incomplete grant reports may suspend the next tranche "
        "(07 s.3.3); the February report was late (03 D09).",
    ],
}

SPECIFIC_ACTIONS = {
    "GRANT_ELIGIBILITY_RULING": [
        "Record the grant body's written ruling as a source document before any baseline change",
        "Re-score R08 and R01 with an accountable owner; R08's Closed status is out of date",
        "Recompute the Council-funded share and remaining headroom; keep roof strengthening UNKNOWN",
        "Sponsor to decide how the asbestos variation is funded and what approval limit applies",
    ],
    "OPERATOR_WITHDRAWAL": [
        "Record the withdrawal notice and current EOI status as source documents",
        "Assign an owner to D14 and agree a dated route to appoint an operator",
        "Re-score R06 and R17 and tell the grant body that the Tranche 2 condition is at risk",
        "Report the status of each tranche condition in the next monthly grant report",
    ],
}

GENERIC_ACTIONS = [
    "Verify change evidence and Sponsor authority",
    "Reassess affected WBS and milestone dependencies",
    "Re-score affected risks and re-run what-if after assumptions are approved",
    "Have C regenerate stale reports, pass Critic, then seek human checkpoint",
    "Have A approve proposed Jira updates before write/read-back",
]


def id_scheme(planning: dict, risk: dict) -> str:
    """Tell the brief-only draft from the data-pack draft by IDs only the pack adds."""
    wbs = {x["wbs_id"] for x in planning.get("wbs_items", [])}
    risks = {x["risk_id"] for x in risk.get("risks", [])}
    if wbs & {"1.2.4", "1.3.6", "1.4.3"} or risks & {"R15", "R16", "R17"}:
        return "DATA_PACK"
    return "BRIEF_ONLY"


def analyse_change(event: dict, planning: dict, risk: dict) -> dict:
    """Produce a review queue for A's governance layer, not a modified baseline."""
    kind = event.get("change_type")
    event_id = event.get("event_id")
    if not kind or not event_id:
        raise ValueError("change_type and event_id are required")
    classified = ALIASES.get(kind, kind)
    scheme = id_scheme(planning, risk)
    links = DATA_PACK_LINKS if scheme == "DATA_PACK" else BRIEF_ONLY_LINKS
    if classified not in links:
        return {"event_id": event_id, "change_type": kind, "classified_as": None,
                "id_scheme": scheme, "status": "UNCLASSIFIED_REVIEW_REQUIRED",
                "stale_wbs_ids": [], "stale_milestone_ids": [], "stale_risk_ids": [],
                "stale_reports": ["WEEKLY_COMMITTEE", "MONTHLY_GRANT"],
                "impact_notes": [],
                "human_actions": ["Human must classify change and verify supporting source before updating baseline"],
                "approved": False}
    w, m, r = links[classified]
    known_w = {x["wbs_id"] for x in planning["wbs_items"]}
    known_m = {x["milestone_id"] for x in planning["milestones"]}
    known_r = {x["risk_id"] for x in risk["risks"]}
    notes = IMPACT_NOTES.get(classified, []) if scheme == "DATA_PACK" else []
    return {"event_id": event_id, "change_type": kind, "classified_as": classified,
            "id_scheme": scheme, "status": "REVIEW_REQUIRED",
            "stale_wbs_ids": [x for x in w if x in known_w],
            "stale_milestone_ids": [x for x in m if x in known_m],
            "stale_risk_ids": [x for x in r if x in known_r],
            "stale_reports": ["WEEKLY_COMMITTEE", "MONTHLY_GRANT"],
            "impact_notes": list(notes),
            "change_digest": sha256(json.dumps(event, sort_keys=True).encode()).hexdigest(),
            "human_actions": SPECIFIC_ACTIONS.get(classified, []) + GENERIC_ACTIONS,
            "approved": False}
