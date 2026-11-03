"""Fixture adapter only. No report generation or model critic is simulated as live."""
from copy import deepcopy
import json
from pathlib import Path


def run(request: dict, context: dict) -> dict:
    root = Path(__file__).resolve().parents[2]
    output = json.loads((root / "examples/c_output.json").read_text())
    for key in ("run_id", "project_id", "source_snapshot_id", "request"):
        output[key] = deepcopy(request[key])
    # Consume B's output programmatically, demonstrating an actual data handoff.
    count = len(context["planning"]["wbs_items"])
    output["memory"]["open_questions"].append(
        f"Fixture context received {count} proposed WBS items; no model report generated.")
    return output
