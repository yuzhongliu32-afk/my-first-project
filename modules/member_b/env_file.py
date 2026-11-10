"""Explicit, opt-in loading of a local .env file for Member B command-line runs.

The team starter deliberately does not load .env automatically. A B command
loads one only when the user passes --env-file. Values are never printed or
written anywhere else; by default variables already set in the environment are
not overridden.

Set the key without a text editor (paste it; the screen is cleared afterwards):
    python -m modules.member_b.env_file set   [--env .env]
Check whether a key is present (exit code 0 = yes, 1 = no):
    python -m modules.member_b.env_file check [--env .env]
"""
import argparse

import os
import sys
from pathlib import Path

ALLOWED = ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_MAX_OUTPUT_TOKENS",
           "OPENAI_INPUT_USD_PER_MILLION", "OPENAI_OUTPUT_USD_PER_MILLION",
           "MEMBER_B_ACCESS_CODE", "MEMBER_B_AI_RUN_LIMIT", "OPENAI_TIMEOUT_SECONDS", "OPENAI_REASONING_EFFORT",
           "MEMBER_C_ACCESS_CODE", "OPENAI_API_KEY_C",
           "JIRA_BASE_URL", "JIRA_PROJECT_KEY")  # Jira location only; the token stays out of the web server


def read_env_file(path) -> dict:
    """Return the allowed OpenAI settings that have a value in the file."""
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError(f"Env file not found: {file}")
    values = {}
    # utf-8-sig: Windows Notepad may save a byte-order mark at the start of the file.
    for raw in file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        name, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name in ALLOWED and value:
            values[name] = value
    return values


def load_env_file(path, *, override: bool = False) -> list[str]:
    """Load the allowed OpenAI settings from a local file; return the names set."""
    loaded = []
    for name, value in read_env_file(path).items():
        if override or not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def set_values(path, values: dict) -> None:
    """Write NAME=value lines into the file, replacing existing lines, keeping all others."""
    file = Path(path)
    lines = file.read_text(encoding="utf-8-sig").splitlines() if file.is_file() else []
    pending = dict(values)
    for i, raw in enumerate(lines):
        name = raw.split("=", 1)[0].strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if name in pending and "=" in raw:
            lines[i] = f"{name}={pending.pop(name)}"
    lines.extend(f"{k}={v}" for k, v in pending.items())
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cli():
    parser = argparse.ArgumentParser(description="Set or check the local OpenAI settings in .env")
    parser.add_argument("command", choices=["set", "check"])
    parser.add_argument("--env", type=Path, default=Path(__file__).resolve().parents[2] / ".env")
    args = parser.parse_args()
    if args.command == "check":
        present = args.env.is_file() and "OPENAI_API_KEY" in read_env_file(args.env)
        sys.exit(0 if present else 1)
    if not args.env.is_file():
        example = args.env.with_name(".env.example")
        args.env.write_text(example.read_text(encoding="utf-8") if example.is_file() else "", encoding="utf-8")
    current = read_env_file(args.env)
    print("Paste your OpenAI API key (Ctrl+V or right-click), then press Enter.")
    print("Press Enter without typing to keep the current key. The screen is cleared afterwards.")
    key = input("OPENAI_API_KEY: ").strip().strip("\"'")
    os.system("cls" if os.name == "nt" else "clear")  # do not leave the key on screen
    if not key and "OPENAI_API_KEY" in current:
        print("Kept the existing key.")
    elif not key.startswith("sk-") or len(key) < 20 or any(c.isspace() for c in key):
        print("That does not look like an OpenAI API key (it should start with sk-). Nothing was saved.")
        sys.exit(1)
    default_model = current.get("OPENAI_MODEL", "gpt-4.1-mini")
    model = input(f"OPENAI_MODEL [{default_model}]: ").strip() or default_model
    values = {"OPENAI_MODEL": model}
    if key:
        values["OPENAI_API_KEY"] = key
    print()
    print("Optional presentation mode: set an access code so presenters type the code, never the key.")
    code = input("MEMBER_B_ACCESS_CODE (Enter = keep current / none): ").strip()
    if code:
        values["MEMBER_B_ACCESS_CODE"] = code
    limit = input("MEMBER_B_AI_RUN_LIMIT, max AI runs per server start (Enter = keep current / no limit): ").strip()
    if limit:
        if not limit.isdigit():
            print("The run limit must be a whole number. Nothing was saved.")
            sys.exit(1)
        values["MEMBER_B_AI_RUN_LIMIT"] = limit
    os.system("cls" if os.name == "nt" else "clear")
    set_values(args.env, values)
    print(f"Saved to {args.env}: " + ", ".join(sorted(values)) + " (values not shown).")
    print("This file is git-ignored and is never uploaded.")


if __name__ == "__main__":
    _cli()
