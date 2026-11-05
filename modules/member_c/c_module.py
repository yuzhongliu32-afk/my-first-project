
import json
from pathlib import Path

from .memory_agent import retrieve_answer
from .report_writer import generate_report
from .critic_agent import critique_report


def memory_query(question, as_of_date=None):
    """Module 3: Return a grounded MemoryBundle."""
    return retrieve_answer(
        question,
        as_of_date=as_of_date
    )


def generate_and_review_report(kind="monthly"):
    """Module 5: Generate and review a report."""

    if kind not in ("weekly", "monthly"):
        raise ValueError("Choose weekly or monthly.")

    # Step 1: Writer
    report = generate_report(kind)

    path = Path(f"data/report_{kind}.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Step 2: Independent Critic
    review = critique_report(kind)

    # Never release a report that did not pass.
    if not review["ready_for_human_review"]:
        report["status"] = "BLOCKED"

    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Module C's ReportingBundle
    return {
        "reports": [report],
        "critic_reviews": [review]
    }
