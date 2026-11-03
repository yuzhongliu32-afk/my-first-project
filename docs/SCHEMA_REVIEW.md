# Schema review — 2026-11-03

Scope: the four JSON files supplied in the team chat. The original bytes are
preserved in schemas/; SHA-256 values are in schema_source_manifest.json.

## Verified results

- All four original files parse and pass JSON Schema Draft 2020-12 meta-validation.
- Every local $ref resolves. There are no external schema references to fetch.
- Shared definitions and root properties match the supplied Full contract.
- A derived C projection also passes meta-validation; its root consists of shared
  fields plus memory, reporting, metrics and errors. Pending C's confirmation.
- `python scripts/audit_schemas.py` checks identity and consistency again.
- 34 local automated contract/handoff tests passed at preparation time. These are
  software checks, not the assessed 20 business-case evaluation or AI quality metrics.
- Fixture automatic handoff ran successfully, with zero model/Jira calls.

## Findings and resolutions

| Finding | Treatment in this starter |
|---|---|
| Common is closed and rejects B/C-specific fields | Validate Common projection; independently validate module response. Do not naively allOf closed schemas. |
| C exchange file absent | Generate an explicitly derived C contract from Full; no changes to four originals. |
| Full contains all modules | A aggregates validated results; never ask one model to invent whole-system state. |
| Producer enum alone does not establish ownership | Boundary checks expected producer and rejects A-only properties in B/C; actual service authentication remains future work. |
| ID uniqueness, references and cycles are not in schemas | Backend checks WBS/scope/milestone/risk links and dependency cycles, plus report/fact/review references. |
| Dates are generic strings | Backend checks ISO calendar dates and period order. Calendar feasibility is not inferred. |
| Risk arithmetic and numeric bounds missing | Backend checks positive component ratings, null partial scores and multiplication. Upper rating scale still requires team confirmation. |
| Evidence refs allow null lines and arbitrary quotes | Backend requires line ranges and nonempty quotes. run_handoff verifies exact quote in supplied document version. Page mapping and claim support need separate checks. |
| Model can syntactically emit approvals/execution facts | Modules cannot submit A-owned fields. Trusted A state must be backend-generated. No actual auth, approval store or Jira writer is implemented here. |
| Runtime metrics have no minimums | Backend rejects negative values; unmeasured totals remain null. Elapsed handoff wall time is measured locally. |
| Report readiness and critic rounds can conflict | Check fresh snapshot, fact links, round limits, latest PASS for ready status, and blockers. PASS is never human approval. |
| JiraAction lacks full write payload, field dates and dependency operations | Preserve exact payload/hash in A backend store during Jira implementation; agree any contract extension before editing schemas. |
| Full has a source snapshot but no explicit plan/risk artifact revisions | Use A's artifact store for version history/hashes. Current starter does not implement that persistence. |

## What is not established

Schemas and tests do not prove factual accuracy, model tool-calling quality, free
quota, authentication, audit tamper resistance, real Jira writes/readback, semantic
critic quality, fairness or completed coursework. Actual team modules and source
materials were not included in the supplied folder. Do not treat fixture outputs
as those deliverables. Review original contracts as a team before freezing v1.
