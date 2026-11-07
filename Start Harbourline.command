#!/bin/bash
set -eu
cd "$(dirname "$0")"
export PYTHONUTF8=1
printf '1. Rehearsal (no API keys)\n2. Live team sandbox\n'
read -r -p 'Choose 1 or 2 [1]: ' choice
case "${choice:-1}" in
    1) requirements=requirements.txt; set -- ;;
    2) requirements=requirements-live.txt; set -- --live ;;
    *) echo 'Choose 1 or 2.'; exit 1 ;;
esac
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo 'Install Python 3.11 or newer, then reopen this launcher.'
    exit 1
fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import jsonschema, pypdf' ||
   { [ "$requirements" = requirements-live.txt ] && ! .venv/bin/python -c 'import openai, dotenv'; }; then
    .venv/bin/python -m pip install -r "$requirements"
fi
exec .venv/bin/python -m harbourline.console "$@"
