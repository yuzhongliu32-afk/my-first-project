"""Explicit, opt-in loading of a local .env file for Member B command-line runs.

The team starter deliberately does not load .env automatically. A B command
loads one only when the user passes --env-file. Values are never printed or
written anywhere; variables already set in the environment are not overridden.
"""
import os
from pathlib import Path

ALLOWED = ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_MAX_OUTPUT_TOKENS",
           "OPENAI_INPUT_USD_PER_MILLION", "OPENAI_OUTPUT_USD_PER_MILLION")


def load_env_file(path) -> list[str]:
    """Load the allowed OpenAI settings from a local file; return the names set."""
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError(f"Env file not found: {file}")
    loaded = []
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        name, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name in ALLOWED and value and not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded
