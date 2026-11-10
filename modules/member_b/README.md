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

### Local test environment and workbench (Windows)

1. Build the evidence library once, including the Sponsor's formal answers:
   `python scripts/prepare_evidence.py --brief "<brief.pdf>" --pack "<Harbourline_Data_Pack.zip>" --sponsor-answers "<Capstone Sponsor Answers — Round 1.pdf>"`
   (SPONSOR_ANSWER evidence; a Sponsor question may be ANSWERED only by citing it.)
2. Double-click `start_member_b.bat` in the repository root. It creates `.venv`, installs
   `requirements-live.txt`, copies `.env.example` to a git-ignored `.env` if missing, starts the
   server and opens `http://127.0.0.1:8765/`. Do not double-click the HTML file itself.
3. **0 · Connect**: put `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env` (preferred, the team rule is
   backend-managed keys) or type them on the page (held in server memory only, never saved).
4. **1 · Generate with AI** (2–5 min) or **Offline preview (rules, no AI)** to test the page
   without a key. The preview is labelled as rules output everywhere it appears.
5. Tabs: **Plan** (scope statement, Sponsor questions, scope items, WBS L3 with dictionary,
   milestones with dependencies), **Risk register**, **What-if** (three scenarios compared, plus *Your own what-if*: edit any O/M/P and recompute P50/P80 in code),
   **Change impact** (Week 12 Template B note), **Schedule forecast**. Every row shows its source
   chips; hover one to read the quoted line. **Download B JSON** gives the A contract file.

### How B meets the brief (Module 1 + Module 4)

| Requirement | Where it is enforced |
|---|---|
| Scope statement, Sponsor questions | Planning role; code rejects a plan with no Sponsor questions |
| Unanswered Sponsor questions are not filled in | Code: an OPEN/DECLINED question with an answer fails; an ANSWERED one must cite SPONSOR_ANSWER evidence (Sponsor Answers Round 1) |
| WBS to Level 3 with dictionary, traceable to scope | Code: levels 1–3, parent levels, no cycles; a WBS without a scope line must be UNRESOLVED |
| Milestones with dependencies (relative time) | Code: predecessors exist, no cycles |
| Risk register: score, owner, trigger, linked WBS | Code: score = P × I, links exist, every risk cites evidence; unnamed owners stay null |
| What-if with schedule and cost, stated assumptions | What-if role proposes O/M/P per element with a cited reason per bound; **code** computes PERT and a 10,000-draw PERT-beta Monte Carlo (P50/P80). At least one scenario must carry both cost and schedule |
| Change impact | `change_note.py` (Week 12 Template B): affected elements, three-point re-estimate, P50/P80 in code, contingency before/after, funding only from cited sources else UNRESOLVED, one decision sentence (evasive wording rejected), UNRESOLVED list, conflicting sources shown side by side, stale WBS/milestones/risks/reports |
| Output in A's format | `validate(output, 'B')` against `schemas/Harbourline_B_Schema.json`; every SourceRef re-verified against the library |

Each attempt runs Planning → Risk → What-if → code checks → Critic; a failed check is fed back
as `MECHANICAL_CHECK_FAILED` (up to 3 attempts). The trace with each attempt's findings and the
what-if computation is saved to `.local/member_b_live_trace.json`. All outputs are proposals for
human review: no approvals, no Jira writes.

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
