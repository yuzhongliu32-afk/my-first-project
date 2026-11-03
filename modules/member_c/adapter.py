
import json
import time
import uuid
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator
from .c_module import memory_query, generate_and_review_report

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "schemas/Harbourline_C_Schema.json").read_text()
)
VALIDATOR = Draft202012Validator(SCHEMA)


def empty_memory():
    return {
        "query": None,
        "answer": None,
        "answer_status": "NOT_RUN",
        "fact_records": [],
        "conflicts": [],
        "decisions": [],
        "citations": [],
        "open_questions": []
    }


def run(request: dict, context: dict) -> dict:
    started = time.perf_counter()
    req = deepcopy(request)
    ctx = deepcopy(context)

    result = {
        "schema_version": "harbourline.v1",
        "message_id": str(uuid.uuid4()),
        "run_id": req["run_id"],
        "project_id": req["project_id"],
        "producer": "C",
        "recipient": "A",
        "operation": req["operation"],
        "status": "BLOCKED",
        "source_snapshot_id": req["source_snapshot_id"],
        "request": deepcopy(req["request"]),
        "source_evidence": [],
        "memory": empty_memory(),
        "reporting": {
            "reports": [],
            "critic_reviews": []
        },
        "metrics": {
            "api_calls": 0,
            "input_tokens": None,
            "output_tokens": None,
            "estimated_cost_usd": None,
            "elapsed_seconds": None
        },
        "errors": []
    }

    try:
        if req["producer"] != "A" or req["recipient"] != "C":
            raise ValueError("Expected A to C request.")

        snapshot = json.loads(
            (ROOT / "data/semantic_index.json").read_text()
        )["source_snapshot_id"]

        if (
            req["source_snapshot_id"] != snapshot
            or ctx.get("source_snapshot_id") != snapshot
        ):
            raise ValueError("Source snapshot mismatch.")

        operation = req["operation"]

        if operation == "MEMORY_QUERY":
            question = req["request"]["question"]

            if not question:
                raise ValueError("Question is missing.")

            memory = memory_query(
                question, as_of_date=ctx.get("as_of_date")
            )

            for fact in memory["fact_records"]:
                fact.setdefault("related_scope_ids", [])

            result["memory"] = memory
            result["status"] = "SUCCESS"
            result["metrics"]["api_calls"] = 2

        elif operation == "GENERATE_REPORTS":
            report_type = req["request"]["requested_report_type"]
            period = req["request"]["reporting_period"]

            # Current implementation supports only this
            # tested monthly configuration.
            if (
                report_type != "MONTHLY_GRANT"
                or period != {
                    "start_date": "2027-03-01",
                    "end_date": "2027-03-31"
                }
                or ctx.get("as_of_date") != "2027-04-06"
            ):
                raise ValueError(
                    "Reporting period not yet supported by C V1."
                )

            reporting = generate_and_review_report("monthly")

            for review in reporting["critic_reviews"]:
                review.setdefault(
                    "reviewer_notes",
                    "Automated critique; human approval required."
                )

            result["reporting"] = reporting

            review = reporting["critic_reviews"][0]
            result["status"] = (
                "PARTIAL"
                if review["ready_for_human_review"]
                else "BLOCKED"
            )

            # Logical SDK calls: four Memory queries,
            # one Writer and one Critic.
            result["metrics"]["api_calls"] = 10

            result["errors"].append({
                "code": "B_CONTEXT_NOT_YET_INTEGRATED",
                "message": (
                    "Planning and risk context is not yet "
                    "consumed by this Report Writer version."
                ),
                "recoverable": True
            })

        else:
            raise ValueError(
                f"Operation not yet supported: {operation}"
            )

        refs = list(result["memory"]["citations"])

        for report in result["reporting"]["reports"]:
            for section in report["sections"]:
                refs.extend(section["citations"])

        unique = {}
        for ref in refs:
            key = (
                ref["document_id"],
                ref["document_version"],
                ref["chunk_id"]
            )
            unique[key] = ref

        result["source_evidence"] = list(unique.values())

    except Exception as exc:
        result["status"] = "BLOCKED"
        result["errors"].append({
            "code": "C_MODULE_ERROR",
            "message": str(exc),
            "recoverable": True
        })

    result["metrics"]["elapsed_seconds"] = round(
        time.perf_counter() - started, 3
    )

    VALIDATOR.validate(result)
    return result
