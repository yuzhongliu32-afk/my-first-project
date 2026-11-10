# Member B — Dynamic Planning & Risk AI Agent

## What changed

`agent.generate(request, evidence_library, gateway)` creates **Planning and Risk from the underlying source documents** using three model roles (Planning, Risk, independent Critic). It does not edit a pre-written WBS or Risk Register. The generated output conforms to the original team's `Harbourline_B_Schema.json` and uses source references resolved by code, not model-invented references.

- `agent.py`: source catalog → OpenAI Planning → OpenAI Risk → OpenAI Critic → strict validation.
- `live_demo.py`: run B alone, **real OpenAI** (requires your API project key + model).
- `adapter.py`: original `run(request, context)` interface. `context.mode='live'` calls model; default `rules` remains the explicitly labelled offline fallback.
- `planning_risk.py`, `data_pack.py`, `prepare_sources.py`: deterministic, source-based offline path and source preparation.
- `change.py`: conservative offline mapping of known change types.
- `change_live.py`: separate OpenAI-generated impact assessment for novel changes; it returns advisory stale IDs and human actions, not an approved baseline. A must explicitly wire it into its change flow. Automatic regeneration still requires A's orchestration.
- `http_api.py`: localhost `POST /v1/plan-risk` with optional `mode:'live'`. Not suitable as a public unauthenticated API.
- `requirements.txt`: package dependency.

## Install and prepare authoritative sources

From repository root:

```bash
python -m pip install -r requirements-live.txt
python scripts/prepare_evidence.py --brief "/local/path/MA6094 Capstone Brief.pdf" --pack "/local/path/Harbourline_Data_Pack.zip" --metadata "/local/path/verified_source_metadata.json"
```

The `verified_source_metadata.json` file must contain **human-verified** evidence availability dates. Unverified dates must not be invented. The 2027 timeline in the course pack is a fictional simulation.

## Run B AI on your own (does not require A to invoke it)

Set `OPENAI_API_KEY` in your local environment, not in GitHub. Example:

```bash
export OPENAI_API_KEY="<your project API key>"
python -m modules.member_b.live_demo --model "<valid OpenAI model ID>" --cutoff 2027-04-06
```

Output: `.local/member_b_live_output.json`. Check `metrics.api_calls`, token metrics, structure and citations. No real AI success is claimed unless an actual provider request succeeds.

### Using your own key from a local .env (Windows or macOS)

1. Copy `.env.example` to `.env` in the repository root. `.env` is already in `.gitignore`; never commit it.
2. Fill in only `OPENAI_API_KEY=` and `OPENAI_MODEL=` (a model ID your key can use).
3. Build the evidence library once (brief + zipped data pack):
   `python scripts/prepare_evidence.py --brief "<brief.pdf>" --pack "<Harbourline_Data_Pack.zip>"`
4. Run B on its own: `python -m modules.member_b.live_demo --env-file .env`

`--env-file` loads only the OpenAI settings, never overrides variables already set, and prints
the variable names it loaded, never their values. Without `--cutoff`, all catalogued lines are
eligible; with `--cutoff`, lines without verified availability dates are excluded, so supply
`--metadata` to `prepare_evidence.py` first or very little evidence remains.

### Agent loop

Each attempt runs Planning → Risk → mechanical checks → independent Critic. If the mechanical
checks fail (unknown citation ID, broken WBS parent, score ≠ P × I, dependency cycle), the
failure is fed back to Planning and Risk as `MECHANICAL_CHECK_FAILED` on the next attempt and
that attempt's Critic call is skipped. A Critic `REVISE` is fed back the same way; `ESCALATE`
stops. Nothing is returned unless both the code checks and the Critic pass. Attempts are capped
by `max_review_rounds` (at most 3, each up to 3 calls).

## Run A → B → C using OpenAI B mode

Keep A's existing integration as-is; A calls `refine()` when `--plan-mode live`. In this version, `refine()` regenerates Planning and Risk **from the evidence library**, without giving the deterministic B draft to the model.

```bash
python -m harbourline.operations run --start 2027-03-01 --end 2027-03-31 --cutoff 2027-04-06 --plan-mode live
```

Do **not** use `--scripted-test` as proof of live API calls. A's `ModelGateway` reads `OPENAI_MODEL` and `OPENAI_API_KEY` from the trusted backend environment.

## Limits and academic disclosure

- This is a **real model-calling implementation**, but code verification/mock testing does not demonstrate successful live OpenAI or Jira calls.
- Critic is a model review and mechanical checks; factual correctness still needs human evaluation and sponsor decisions.
- A's Change Handling marks stale artifacts and calls for regeneration; the Stretch target of automatic refresh without a person rerunning remains separate.
- Some OpenAI API models and usage are billable; verify a truly free route to meet the course requirement.
- The baseline is `PARTIAL` until human/Sponsor confirmation.
