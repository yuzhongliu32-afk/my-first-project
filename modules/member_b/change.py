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

# The offline rules path only flags which existing IDs are now stale. It deliberately
# holds no pre-written findings about an event: the cost, funding, contingency and
# schedule effects are derived from the evidence, with cited rows, by the AI change
# impact note (change_note.py), so gap recall measures what the system finds itself.
RULES_NOTE = ("Offline rules mapping: the IDs below are a fixed starting list of what may be "
              "stale, not an impact analysis. Run the change impact note to derive the effects "
              "from the brief and data pack with cited rows.")

SPECIFIC_ACTIONS = {
    "GRANT_ELIGIBILITY_RULING": [
        "Record the grant body's written ruling as a source document before any baseline change",
        "Run the change impact note to derive cost, funding and contingency effects with cited rows",
    ],
    "OPERATOR_WITHDRAWAL": [
        "Record the withdrawal notice as a source document before any baseline change",
        "Run the change impact note to derive operator, grant-condition and schedule effects with cited rows",
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
    notes = [RULES_NOTE]
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
