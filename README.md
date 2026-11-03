# MA6094 Harbourline — Team Integration Starter

Member A's shared contract validation and Python integration scaffold for the team.
Original A/B/Common/Full schemas are preserved byte-for-byte. C's exchange schema
is derived from Full and explicitly pending C's confirmation.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m harbourline check-schemas
python -m unittest discover -s tests -v
python -m harbourline demo
```

Outputs are written to ignored `.local/demo/`: full_output.json and handoff_trace.json.
The demo really invokes B -> A validation -> C -> A aggregation automatically,
but uses **labelled fixtures**. It makes **zero AI/Jira calls** and is not evidence
that the assessed business workflows have been completed.

Validate a real module output with:

```bash
python -m harbourline validate B path/to/b_output.json
python -m harbourline validate C path/to/c_output.json
```

See [team handoff](docs/TEAM_HANDOFF.md) for function signatures and deliverables,
[schema review](docs/SCHEMA_REVIEW.md) for findings and scope,
and [collaboration](docs/COLLABORATION.md) for uploading code.

## Layout

- schemas/: four original contracts plus derived C projection.
- harbourline/: validation, aggregation, automatic fixture handoff, CLI.
- modules/member_b/ and modules/member_c/: replace fixture adapters with team code.
- examples/: integration fixtures only; not actual project evidence or model results.
- tests/: boundary, cross-field and automatic handoff checks.
- .env.example: empty placeholders only; no credentials or auto-loaded secrets.

## Current scope

Implemented: schema review tooling, additional boundary checks, immutable input
handoff, aggregation, fixtures and tests. Not implemented: real OpenAI agents,
C retrieval, Jira calls/readback, human authentication/approval storage, production
shared persistence or the full capstone system. The existing public preview is a
separate demo, not this Python backend. Do not describe them as fully integrated.

Do not put API keys or private source documents in the repository. Dependencies
are installed locally; the starter does not perform billable operations. Model
and free-path availability must be verified before final coursework claims.

AI assistance was used to prepare this scaffold; members must review and test
it with their actual implementations and disclose assistance as required.
