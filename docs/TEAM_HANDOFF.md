# Team handoff agreement — proposed for confirmation

Platform: Python 3.11+ functions in one backend. OpenAI API is the team's selected
provider per the supplied chat; no model or paid call is configured by this starter.
Each real module owns its model prompt and tool logic. Keep API credentials in
backend environment variables; never return them in JSON, logs or commits.

## B and C deliverables
Upload to modules/member_b/ or modules/member_c/ on a feature branch:
1. Adapter with `run(request: dict, context: dict) -> dict`.
2. Implementation and module requirements.txt (explain any version conflicts).
3. README with setup and a reproducible call example.
4. One **actual** output JSON, labelled with input snapshot and model configuration.
   Place appropriately redacted real outputs outside examples/fixtures until reviewed.
5. Known limitations, missing inputs and run metrics. Unknown metrics stay null.

Do not overwrite another member's directory or change shared contracts without
agreement. Fixture adapters currently return clearly labelled test fixtures, not
real AI output. They demonstrate plumbing only.

## Entry points
B: `modules.member_b.adapter:run`
- request: Common message, producer A, recipient B, operation PLAN_RISK.
- context: source_snapshot_id; add a versioned evidence service during integration.
- response: B schema, producer B, recipient A, operation PLAN_RISK.

C: `modules.member_c.adapter:run`
- request: Common message, producer A, recipient C, operation GENERATE_REPORTS.
- context: source_snapshot_id, validated planning and risk from B.
- response: C schema, producer C, recipient A, operation GENERATE_REPORTS or
  CRITIC_REVIEW. Return evidence records alongside reports.
- C can dispatch its internal memory/retrieval -> writer -> critic workflow.

Every module must echo run_id, project_id, source_snapshot_id and request exactly.
Give each output its own message_id. Return fresh dicts. The caller passes copies.
C's source retrieval service is to be wired in with C's implementation, not faked.

## Validation and aggregation
Common is closed (`additionalProperties: false`), so validate a projection of
shared fields, **not** the complete B/C response against Common. Do not combine
Common and Full using naive allOf. Each module is independently validated; A merges
validated B planning/risk and C memory/reporting into its trusted backend state.
Module response JSON cannot contain integration, change or governance fields.

Full is a persisted combined state, not a single giant LLM output. Schema checks
are followed by ID/dependency, risk arithmetic, dates and review-state checks.
Exact source-line checks require an explicit versioned source registry. Schema
validity alone does not establish factual correctness or source approval.

## Ownership and trust
A exclusively records approvals, Jira results, readback, audit entries and handoff
traces in the backend. `aggregate(a,b,c)` accepts `a` from that trusted backend;
it is not a public authorization boundary and must not accept arbitrary user/LLM A
JSON. Authentication and real human approval persistence are NOT implemented here.
Metrics must come from actual runtime observations, never model guesses.

The current Jira fields cannot describe complete descriptions, dates, dependencies
or before/after write payloads. Keep the exact proposed payload and content hash
in A's backend action store; expose its action_id/subject_version in this contract.
Any schema extension needs team agreement. There is no Jira execution in this starter.

## Decisions still needing team confirmation
- C projection derived from Full: confirm or provide C's preferred compatible schema.
- Shared model ID, cost budget and verified free alternative.
- Risk scale and freeze rules; existing schema does not specify maximum scale.
- Review round policy (starter accepts 1–5, fixture uses 2).
- Approver identities, repo collaborator accounts, evidence Drive location.
