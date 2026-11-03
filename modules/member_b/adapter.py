"""Fixture adapter only. Replace with B's real implementation before live testing."""
from copy import deepcopy
import json
from pathlib import Path


def run(request: dict, context: dict) -> dict:
    root = Path(__file__).resolve().parents[2]
    output = json.loads((root / "examples/b_output.json").read_text())
    for key in ("run_id", "project_id", "source_snapshot_id", "request"):
        output[key] = deepcopy(request[key])
    return output
