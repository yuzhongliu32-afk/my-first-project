# Integrated backend runbook

## Team entry points and ownership

A: `harbourline.pipeline.run_project(common, library_path, cutoff=..., ...)`.
B: `modules.member_b.adapter.run(request, context)` plus optional live refinement.
C: `modules.member_c.adapter.run(request, context)`; handles MEMORY_QUERY and
GENERATE_REPORTS through the new stateless service. Existing standalone C scripts
remain as historical implementation, but are not the integrated execution path.

A verifies B's named source mode against exact evidence, then maps it to a
content-addressed snapshot. C accepts that same snapshot. Every text/date metadata
change changes the snapshot. The backend owns approvals, runtime metrics and Jira
results; model JSON cannot submit those records through B/C contracts.

## Source setup

```bash
python scripts/prepare_evidence.py \
  --brief "/path/to/MA6094 Capstone Brief.pdf" \
  --pack "/path/to/Harbourline_Data_Pack.zip" \
  --metadata "/path/to/verified_source_metadata.json"
```

Omit --pack when it has not been supplied. Additional formal sponsor answers can
be imported with repeated --additional-registry paths. Registry records contain
`document_id`, `version`, `source_type`, `page`, `lines` and optionally `line_pages`.
Source type must be BRIEF, DATA_PACK or SPONSOR_ANSWER. Do not convert AI-generated
answers into sponsor evidence.

Metadata is keyed by the exact document ID. Use `available_from: YYYY-MM-DD` only
when established by a source or supplied by a human reviewer. Unknown dates remain
null and are excluded from time-bounded reporting. For meeting minutes, use
`dated_segments: [{line_start, line_end, available_from}]`; a quoted span must stay
inside one meeting segment. Do not guess meeting issue dates from event dates.
The brief is explicitly treated as static background, never period progress.

B's current Pack reconciler uses the full Jan–Mar course baseline. If a report
cut-off predates B's supporting records, integration blocks rather than leaking
later facts into an earlier report. Prepare an appropriate as-of baseline for
such a run. Source files remain ignored under data/.

`examples/test_source_registry.json` contains the fictional brief excerpt used in
local tests. It is identified as test input; actual library preparation re-reads
the supplied PDF. It is not the full Data Pack or sponsor answers.

## Live OpenAI calls

```bash
python -m pip install -r requirements-live.txt
export OPENAI_API_KEY="<set locally>"
export OPENAI_MODEL="<model ID available to your account>"
python -m harbourline.operations run \
  --start 2027-03-01 --end 2027-03-31 --cutoff 2027-04-06 \
  --weekly-start 2027-03-25 --weekly-end 2027-03-31 \
  --monthly-start 2027-03-01 --monthly-end 2027-03-31
```

Without --scripted-test, C uses the actual Responses API. There is no automatic
replacement of failed model calls by fake successful responses. Add --plan-mode
live for B's model refinement; default rules mode is clearly identified. SDK
retries are disabled so call attempts can be counted. Response token usage is
measured; estimated cost stays null unless you configure verified per-million
input/output prices. Configure OPENAI_EMBEDDING_USD_PER_MILLION separately for semantic retrieval.
When that rate is missing, mixed text/embedding cost remains null. Text-model
rates are never applied to embedding usage.

Optional semantic index (calls the embedding API):

```bash
python scripts/build_semantic_index.py --model "<embedding model ID>"
python -m harbourline.operations run --start 2027-03-01 --end 2027-03-31 \
  --cutoff 2027-04-06 --semantic-index data/semantic_index.json
```

Without that flag the service uses lexical retrieval; it never calls it semantic.
The optional index is tied to the verified source snapshot and can be rebuilt on
any teammate's computer. No hard-coded user filesystem path is required.

## Jira preview, human approval and readback

Configure JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN and JIRA_PROJECT_KEY locally.
Base URL must be credential-free HTTPS. Set issue type names matching the actual
project: JIRA_TYPE_LEVEL1, JIRA_TYPE_LEVEL2, JIRA_TYPE_LEVEL3, JIRA_TYPE_MILESTONE.
Defaults are Epic, Task, Sub-task and Task. Missing types block the preview.

Configure HARBOURLINE_APPROVERS with the authorised **local OS account names**.
This is a trusted local CLI, not authentication for a public website. Do not put
these keys or approvals in the public demo. A named human must actually review the
preview; the agent must not invoke the live approval command on their behalf.

```bash
python -m harbourline.operations jira-preview RUN-ID --out .local/jira_preview.json
# Human opens the JSON and reviews exact fields, parents, dates and dependencies.
python -m harbourline.operations approve BATCH-ID --confirm-hash EXACT-REVIEW-HASH
python -m harbourline.operations jira-apply BATCH-ID
python -m harbourline.operations audit --out .local/audit_export.json
python -m harbourline.operations show RUN-ID --out .local/full_with_governance.json
```

Approval binds the run version, source snapshot, target Jira site/project and
complete payload hash; default expiry is 30 minutes. Unknown dates stay unset.
Parent-first writes, stable labels and persisted external-key mappings prevent
normal repeated creation. Search duplicates, altered remote fields and readback
mismatches block execution. Do not blindly retry an uncertain create: a failed or
interrupted batch requires human reconciliation and a new preview/approval.

Every write attempt is logged before the network call. Readback is required for
success. There are no delete, archive, transition or Done operations. Dependencies
use the Jira Blocks issue-link type, which must exist in the target project.
The approved local batch stores the full payload absent from the original schema.

## Change handling

```bash
python -m harbourline.operations change RUN-ID path/to/change_event.json
```

Example hypothetical event:

```json
{"event_id":"WHATIF-001","change_type":"LIFT_DELAY","description":"Hypothetical supplier delay for testing","hypothetical":true}
```

Actual events need verified source_refs and authority review; a hypothesis is not
an approved baseline. The method expands downstream work/milestone/risk effects,
marks plan, risk and both report artifacts stale, and invalidates pending or
approved batches. Unknown change types conservatively stale outputs for review.
Regenerate with a new source snapshot/run and seek fresh approval. Old evidence,
reports and decisions remain in history.

Report release is a local JSON export only: report-preview, human approve, then
report-export. Fresh reports and latest Critic PASS are required. No email or
external grant submission is sent. Scripted/unverified runs cannot be released.
