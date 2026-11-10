"""Run optional schedule supplement against an existing Member B JSON result.

Uses the SAME OPENAI_API_KEY and OPENAI_MODEL as Member B live.
Does not modify the existing B file, A/C interfaces, Jira or the website.
"""
import argparse
import json
from pathlib import Path
from .adapter import forecast
from .env_file import load_env_file

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description="Member B optional schedule forecast")
    parser.add_argument("--b-output", type=Path,
                        default=ROOT / ".local/member_b_live_output.json")
    parser.add_argument("--library", type=Path,
                        default=ROOT / "data/evidence_library.json")
    parser.add_argument("--cutoff", help="Evidence as-of date YYYY-MM-DD")
    parser.add_argument("--model", help="Override configured OPENAI_MODEL")
    parser.add_argument("--env-file", type=Path, help="Local .env with OPENAI_API_KEY/OPENAI_MODEL; never commit it")
    parser.add_argument("--activity-id", help="Activity ID to delay in scenario")
    parser.add_argument("--additional-days", type=int, help="Conditional calendar-day delay")
    parser.add_argument("--scenario-id", default="USER-ILLUSTRATIVE")
    parser.add_argument("--change-event", type=Path,
                        help="JSON change event from form or manually saved event")
    parser.add_argument("--out", type=Path,
                        default=ROOT / ".local/member_b_schedule_output.json")
    args = parser.parse_args()
    if args.env_file:
        print(json.dumps({"env_file_loaded": load_env_file(args.env_file)}))  # names only
    if args.change_event is not None and (args.activity_id is not None or args.additional_days is not None):
        parser.error("Use --change-event OR --activity-id / --additional-days")
    if (args.activity_id is None) != (args.additional_days is None):
        parser.error("Provide --activity-id and --additional-days together")
    b = json.loads(args.b_output.read_text(encoding="utf-8"))
    scenario = None
    if args.activity_id is not None:
        scenario = {"scenario_id": args.scenario_id, "activity_id": args.activity_id,
                    "additional_days": args.additional_days}
    event = json.loads(args.change_event.read_text(encoding="utf-8")) if args.change_event else None
    output = forecast(
        b,
        {"evidence_library_path": str(args.library),
         "planning": b.get("planning"), "risk": b.get("risk"),
         "cutoff": args.cutoff, "model": args.model},
        scenario=scenario, change_event=event)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps({"status": output["status"],
                      "forecast_finish": (output.get("forecast") or {}).get("forecast_finish"),
                      "api_calls": output["metrics"].get("api_calls"),
                      "file": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
