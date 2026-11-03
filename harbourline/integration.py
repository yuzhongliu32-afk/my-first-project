"""A-owned boundary and aggregation. Module proposals cannot write governance."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from time import monotonic
from uuid import uuid4
from .contracts import ContractError, common_projection, validate, verify_evidence


def empty_backend(common):
    """Created by A, never by an LLM. No approval or Jira success is fabricated."""
    return {**deepcopy(common), "producer": "A", "recipient": "HUMAN", "operation": "FULL_RUN",
            "integration": {"jira_project_key": None, "jira_actions": [], "handoff_completed": False, "handoff_trace_ids": []},
            "change": {"events": [], "stale_artifacts": [], "human_actions": []},
            "governance": {"approvals": [], "audit_entries": [], "fairness_checks": [], "incidents": []},
            "metrics": {"api_calls": 0, "input_tokens": None, "output_tokens": None, "estimated_cost_usd": None, "elapsed_seconds": None},
            "errors": []}


def aggregate(a, b, c):
    """a MUST be loaded from A's trusted backend, not module/user JSON."""
    for role, msg in (("A", a), ("B", b), ("C", c)):
        validate(msg, role, expected_producer=role)
    for part in (b, c):
        for field in ("run_id", "project_id", "source_snapshot_id", "request"):
            if part[field] != a[field]:
                raise ContractError(f"Module {field} mismatch; mixed snapshots/runs are not allowed")
    output = deepcopy(a)
    output.update(planning=deepcopy(b["planning"]), risk=deepcopy(b["risk"]),
                  memory=deepcopy(c["memory"]), reporting=deepcopy(c["reporting"]))
    rank = {"SUCCESS": 0, "PARTIAL": 1, "BLOCKED": 2, "FAILED": 3}
    output["status"] = max((p["status"] for p in (a, b, c)), key=rank.get)
    output["errors"] = [deepcopy(e) for p in (a, b, c) for e in p["errors"]]
    output["metrics"] = {}
    for field in a["metrics"]:
        vals = [p["metrics"][field] for p in (a, b, c)]
        output["metrics"][field] = None if any(x is None for x in vals) else sum(vals)
    return validate(output, "Full", expected_producer="A")


def run_handoff(common, module_b, module_c, documents):
    """run(request: dict, context: dict) -> module-specific exchange dict.

    Copies prevent a module mutating A state. No external writes or model calls
    are implemented here. Actual team modules replace the explicit fixture adapters.
    """
    started = monotonic()
    common = deepcopy(common)
    validate(common, "Common", expected_producer="A")
    a = empty_backend(common)
    trace = []

    def record(event, payload):
        trace.append({"trace_id": str(uuid4()), "run_id": common["run_id"], "event": event,
                      "occurred_at": datetime.now(timezone.utc).isoformat(),
                      "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()})

    request_b = {**common, "recipient": "B", "operation": "PLAN_RISK"}
    b = module_b(deepcopy(request_b), {"source_snapshot_id": common["source_snapshot_id"]})
    validate(b, "B", expected_producer="B")
    verify_evidence(b, documents)
    record("B_OUTPUT_VALIDATED", b)
    if b["status"] not in ("SUCCESS", "PARTIAL") or b["recipient"] != "A" or b["operation"] != "PLAN_RISK":
        raise ContractError("B is blocked/failed or routed incorrectly; handoff stopped")
    for field in ("run_id", "project_id", "source_snapshot_id", "request"):
        if b[field] != common[field]:
            raise ContractError("B context mismatch; handoff stopped")
    request_c = {**common, "recipient": "C", "operation": "GENERATE_REPORTS"}
    context = {"source_snapshot_id": common["source_snapshot_id"], "planning": b["planning"], "risk": b["risk"]}
    record("A_HANDOFF_TO_C", context)
    c = module_c(deepcopy(request_c), deepcopy(context))
    validate(c, "C", expected_producer="C")
    verify_evidence(c, documents)
    if c["recipient"] != "A" or c["operation"] not in ("GENERATE_REPORTS", "CRITIC_REVIEW"):
        raise ContractError("C response routed incorrectly")
    record("C_OUTPUT_VALIDATED", c)
    a["integration"]["handoff_completed"] = True
    a["integration"]["handoff_trace_ids"] = [t["trace_id"] for t in trace]
    # Metrics only measure this local process. API usage remains the adapters' responsibility.
    a["metrics"]["elapsed_seconds"] = 0
    result = aggregate(a, b, c)
    result["metrics"]["elapsed_seconds"] = monotonic() - started
    return result, trace
