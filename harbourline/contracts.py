"""Validate supplied contracts and cross-field invariants without changing them."""
from datetime import date
import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
ROLES = {"Common", "A", "B", "C", "Full"}


class ContractError(ValueError):
    pass


def schema(role):
    if role not in ROLES:
        raise ContractError("Unknown contract role")
    return json.loads((ROOT / "schemas" / f"Harbourline_{role}_Schema.json").read_text(encoding='utf-8'))


def check_schemas():
    for role in sorted(ROLES):
        Draft202012Validator.check_schema(schema(role))


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _require(condition, message):
    if not condition:
        raise ContractError(message)


def _iso(value):
    try:
        return date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False


def _unique(rows, field):
    ids = [row[field] for row in rows]
    _require(len(ids) == len(set(ids)), f"Duplicate {field}")
    _require(all(x.strip() for x in ids), f"Empty {field}")
    return set(ids)


def _acyclic(rows, field, links):
    graph = {r[field]: links(r) for r in rows}
    visiting, done = set(), set()

    def visit(node):
        _require(node not in visiting, f"Cycle in {field}: {node}")
        if node in done:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            _require(dep in graph, f"Unknown {field} reference: {dep}")
            visit(dep)
        visiting.remove(node)
        done.add(node)

    for node in graph:
        visit(node)


def validate(message, role, *, expected_producer=None):
    errors = sorted(Draft202012Validator(schema(role)).iter_errors(message), key=lambda e: str(e.path))
    if errors:
        e = errors[0]
        # Do not echo submitted values: they may contain credentials or private text.
        raise ContractError(f"{role} schema violation at /{'/'.join(map(str, e.path))}: {e.validator}")
    if expected_producer:
        _require(message["producer"] == expected_producer, "Unexpected module producer")
    for key in ("message_id", "run_id", "project_id", "source_snapshot_id"):
        _require(bool(message[key].strip()), f"Empty {key}")
    _require(1 <= message["request"]["max_review_rounds"] <= 5, "Review rounds must be between 1 and 5")
    for obj in _walk(message):
        for key in ("start_date", "end_date", "calendar_date"):
            if obj.get(key) is not None:
                _require(_iso(obj[key]), f"Invalid ISO date: {key}")
        if "start_date" in obj and obj["start_date"] and obj["end_date"]:
            _require(obj["start_date"] <= obj["end_date"], "Reporting period is reversed")
        if "document_id" in obj and "source_type" in obj:
            _require(bool(obj["document_id"].strip()) and bool(obj["document_version"].strip()), "Source identity is empty")
            _require(bool(obj["quote"].strip()), "Evidence quote is empty")
            _require(obj["line_start"] is not None and obj["line_end"] is not None,
                     "Evidence needs line_start and line_end")
            _require(1 <= obj["line_start"] <= obj["line_end"], "Invalid source line range")
            _require(obj["page"] is None or obj["page"] >= 1, "Invalid source page")
        if "api_calls" in obj:
            for key in ("api_calls", "input_tokens", "output_tokens", "estimated_cost_usd", "elapsed_seconds"):
                _require(obj[key] is None or obj[key] >= 0, f"Negative runtime metric: {key}")
    if "planning" in message:
        plan = message["planning"]
        work = plan["wbs_items"]
        wids = _unique(work, "wbs_id")
        mids = _unique(plan["milestones"], "milestone_id")
        sids = _unique(plan["scope_items"], "scope_id")
        _unique(plan["sponsor_questions"], "question_id")
        by_id = {r["wbs_id"]: r for r in work}
        for row in work:
            _require(1 <= row["level"] <= 3, "WBS level must be 1 to 3")
            parent = row["parent_wbs_id"]
            _require((row["level"] == 1 and parent is None) or
                     (parent in by_id and by_id[parent]["level"] == row["level"] - 1),
                     "WBS parent must exist at the preceding level")
            _require(set(row["scope_ids"]) <= sids, "Unknown WBS scope reference")
        _acyclic(work, "wbs_id", lambda r: r["predecessor_wbs_ids"])
        _acyclic(plan["milestones"], "milestone_id", lambda r: r["predecessor_milestone_ids"])
        for row in plan["milestones"]:
            _require(set(row["related_wbs_ids"]) <= wids, "Unknown milestone WBS reference")
        for q in plan["sponsor_questions"]:
            if q["status"] == "ANSWERED":
                _require(bool(q["answer"]) and bool(q["answer_sources"]), "Answered sponsor question needs evidence")
        if "risk" in message:
            risk = message["risk"]
            rids = _unique(risk["risks"], "risk_id")
            _unique(risk["scenarios"], "scenario_id")
            for r in risk["risks"]:
                p, i, score = r["probability"], r["impact"], r["score"]
                _require(set(r["related_wbs_ids"]) <= wids and set(r["related_milestone_ids"]) <= mids,
                         "Unknown risk work or milestone reference")
                if p is None or i is None:
                    _require(score is None, "Partial risk rating must have null score")
                else:
                    _require(p >= 1 and i >= 1 and score == p * i, "Risk score must equal probability * impact")
            for s in risk["scenarios"]:
                _require(set(s["affected_wbs_ids"]) <= wids and set(s["affected_risk_ids"]) <= rids,
                         "Unknown scenario work or risk reference")
                if s["estimate_status"] == "QUANTIFIED_ASSUMPTION":
                    _require(bool(s["assumptions"]) and bool(s["calculation_basis"]), "Quantified scenario needs assumptions and calculation basis")
    if "memory" in message:
        facts = message["memory"]["fact_records"]
        fids = _unique(facts, "fact_id")
        if "planning" in message:
            for fact in facts:
                for field, allowed in (("related_scope_ids", sids), ("related_wbs_ids", wids),
                                       ("related_milestone_ids", mids), ("related_risk_ids", rids)):
                    _require(set(fact[field]) <= allowed, f"Unknown fact {field} reference")
        for fact in facts:
            if fact["status"] == "SUPPORTED":
                _require(bool(fact["source_refs"]), "Supported fact needs source references")
        reports = message["reporting"]["reports"]
        report_ids = _unique(reports, "report_id")
        reviews = message["reporting"]["critic_reviews"]
        _unique(reviews, "review_id")
        for report in reports:
            _require(report["source_snapshot_id"] == message["source_snapshot_id"], "Report source snapshot mismatch")
            _require(report["revision"] >= 1, "Report revision must be positive")
            _require(set(report["included_fact_ids"]) <= fids, "Unknown report fact reference")
            section_ids = _unique(report["sections"], "section_id")
            for section in report["sections"]:
                _require(set(section["supporting_fact_ids"]) <= set(report["included_fact_ids"]), "Unknown section fact reference")
            related = [r for r in reviews if r["report_id"] == report["report_id"]]
            rounds = [r["review_round"] for r in related]
            _require(len(rounds) == len(set(rounds)), "Duplicate report review round")
            for review in related:
                _require(1 <= review["review_round"] <= message["request"]["max_review_rounds"], "Critic round limit exceeded")
                _require(all(f["section_id"] is None or f["section_id"] in section_ids for f in review["findings"]), "Unknown critic section reference")
                if review["verdict"] == "PASS":
                    _require(review["stop_reason"] == "PASS" and not any(f["severity"] == "BLOCKER" for f in review["findings"]), "PASS cannot contain a blocker")
                expected = review["verdict"] == "PASS" and not report["is_stale"]
                _require(review["ready_for_human_review"] == expected, "Critic readiness inconsistent with verdict or stale state")
            if report["status"] == "READY_FOR_HUMAN_REVIEW":
                _require(bool(related) and not report["is_stale"] and
                         max(related, key=lambda r: r["review_round"])["verdict"] == "PASS", "Ready report needs latest PASS and fresh data")
        _require(all(r["report_id"] in report_ids for r in reviews), "Unknown critic report reference")
    return message


def verify_evidence(message, documents):
    """documents[(document_id, version)] = line list for that exact version.

    Physical page mapping and semantic claim support still need separate checking.
    """
    for ref in _walk(message):
        if "document_id" not in ref or "source_type" not in ref:
            continue
        key = (ref["document_id"], ref["document_version"])
        _require(key in documents, "Evidence document version not loaded")
        lines = documents[key]
        start, end = ref["line_start"], ref["line_end"]
        _require(isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(lines), "Evidence lines out of range")
        _require(ref["quote"] in "\n".join(lines[start - 1:end]), "Evidence quote does not match cited lines")


def common_projection(message):
    return {k: message[k] for k in schema("Common")["properties"]}
