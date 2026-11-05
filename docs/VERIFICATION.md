> Historical starter document. For the integrated branch, use [INTEGRATION_RUNBOOK.md](INTEGRATION_RUNBOOK.md) and [INTEGRATION_VERIFICATION.md](INTEGRATION_VERIFICATION.md).

# Preparation verification

Date: 2026-11-03 (Asia/Singapore).
Environment: Python 3.12, jsonschema 4.26.0, temporary isolated virtual environment.

Executed successfully:

```text
python scripts/audit_schemas.py
PASS: five meta-schemas, four original hashes, shared definitions and local references

python -m unittest discover -s tests -v
Ran 34 tests
OK

python -m harbourline demo
PASS: automatic B -> A -> C -> A fixture handoff; no LLM/Jira calls
```

The handoff writes fresh runtime trace IDs, timestamps and hashes locally.
Ignored outputs are not committed. Examples are test fixtures, not actual AI
outputs. Real team modules, source service, AI usage and Jira were not exercised.
