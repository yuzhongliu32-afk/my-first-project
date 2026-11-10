"""Run optional schedule supplement against an existing Member B JSON result.

Uses the SAME OPENAI_API_KEY and OPENAI_MODEL as Member B live.
Does not modify the existing B file, A/C interfaces, Jira or the website.
"""
import argparse
import json
from pathlib import Path
from .adapter import forecast

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description="Member B optional schedule forecast")
    parser.add_argument("--b-output", type=Path,
                        default=ROOT / ".local/member_b_live_output.json")
    parser.add_argument("--library", type=Path,
                        default=ROOT / "data/evidence_library.json")
    parser.add_argument("--cutoff", help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--model", help="Override configured OPENAI_MODEL")
    parser.add_argument("--activity-id", help="Activity ID to delay in scenario")
    parser.add_argument("--additional-days", type=int, help="Conditional calendar-day delay")
    parser.add_argument("--scenario-id", default="USER-ILLUSTRATIVE")
    parser.add_argument("--out", type=Path,
                        default=ROOT / ".local/member_b_schedule_output.json")
    args = parser.parse_args()
    if (args.activity_id is None) != (args.additional_days is None):
        parser.error("Provide --activity-id and --additional-days together")
    b = json.loads(args.b_output.read_text(encoding="utf-8"))
    scenario = None
    if args.activity_id is not None:
        scenario = {"scenario_id": args.scenario_id, "activity_id": args.activity_id,
                    "additional_days": args.additional_days}
    output = forecast(
        b,
        {"evidence_library_path": str(args.library),
         "planning": b.get("planning"), "risk": b.get("risk"),
         "cutoff": args.cutoff, "model": args.model},
        scenario=scenario)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps({"status": output["status"],
                      "forecast_finish": (output.get("forecast") or {}).get("forecast_finish"),
                      "api_calls": output["metrics"].get("api_calls"),
                      "file": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
