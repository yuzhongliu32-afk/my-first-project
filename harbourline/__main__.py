import argparse
import importlib
import json
from pathlib import Path
from .contracts import check_schemas, validate, ContractError
from .integration import run_handoff


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check-schemas")
    v = sub.add_parser("validate")
    v.add_argument("role", choices=["Common", "A", "B", "C", "Full"])
    v.add_argument("path", type=Path)
    run = sub.add_parser("demo")
    run.add_argument("--out", type=Path, default=Path(".local/demo"))
    run.add_argument("--b", default="modules.member_b.adapter:run")
    run.add_argument("--c", default="modules.member_c.adapter:run")
    args = p.parse_args()
    try:
        if args.command == "check-schemas":
            check_schemas()
            print("PASS: all five contracts meet Draft 2020-12 meta-schema")
        elif args.command == "validate":
            validate(json.loads(args.path.read_text(encoding='utf-8')), args.role)
            print("PASS: structural and implemented cross-field checks; source verification is separate")
        else:
            def load(spec):
                module, function = spec.split(":")
                return getattr(importlib.import_module(module), function)
            common = json.loads(Path("examples/request.json").read_text(encoding='utf-8'))
            source = json.loads(Path("examples/source_registry.json").read_text(encoding='utf-8'))
            docs = {(x["document_id"], x["version"]): x["lines"] for x in source}
            result, trace = run_handoff(common, load(args.b), load(args.c), docs)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "full_output.json").write_text(json.dumps(result, indent=2) + "\n")
            (args.out / "handoff_trace.json").write_text(json.dumps(trace, indent=2) + "\n")
            print("PASS: automatic B -> A -> C -> A fixture handoff; no LLM/Jira calls")
            print(f"Outputs: {args.out}")
    except (ContractError, ValueError) as e:
        p.exit(1, str(e) + "\n")


if __name__ == "__main__":
    main()
