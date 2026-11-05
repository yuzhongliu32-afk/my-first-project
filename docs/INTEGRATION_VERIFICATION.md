# Integration verification — 2026-11-06 (Asia/Singapore)

Inputs: main f94263a78121a8e98a3866459a38be99abe7d229;
B 826336f8bc1bb80f7a3de527a00c91f2a1b5e69f;
C 98df55dc9f58aa35c4758b2da78404fec75e021c.

Implemented and tested locally:

- B's actual rules code -> A validation/source checks -> C writer/critic/revision
  service -> Full schema aggregation; same exact evidence snapshot throughout.
- Separate report periods; both report audiences; revision then second critique;
  escalation at the configured cap; invalid citations block.
- Portable PDF source preparation with physical-page references; unknown/future
  source exclusion; content tampering and snapshot mismatch block.
- Optional live B refinement, injected model boundary and actual usage accounting.
- Jira hierarchy, dates, dependency links, approved writes and field/link readback
  using an explicitly in-memory simulated Jira service.
- No approval, wrong actor/hash/target, expiry, stale version, altered payload,
  external edits, readback failure, replay prevention and repeated preview handling.
- Change propagation, stale report flags, approval invalidation and governance
  contract export; audit chain detects an altered stored event.
- All four original schemas remain byte-identical and shared definitions match.

Observed environment: Python 3.12; jsonschema 4.26.0; pypdf 6.21.4;
OpenAI SDK 3.46.0 installed for import compatibility. No API keys were present.
The full unittest suite passed 71 checks, including B's four localhost HTTP tests.
The model responses were scripted or mocked; Jira was simulated. These checks are
not live-service verification and do not replace the assessed 20 business cases.

A scripted CLI integration run produced two reports, a Full JSON and a handoff
trace under ignored .local/. It remained PARTIAL because plans and reports are
proposals requiring review; no sponsor approval was asserted.

NOT EXECUTED: live OpenAI response/embedding requests, live Jira writes/readback,
full Data Pack run, formal sponsor-answer reconciliation, free-path verification,
public website/backend deployment, full coursework evaluation/fairness deliverables.
The local brief was available; the full Pack and live credentials were not.

The local store trusts the OS operator and filesystem. It does not provide public
multi-user identity or externally anchored tamper-proof logging. Do not expose it
as an anonymous web approval service. The public Sites preview remains separate.

API implementation references:
- https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses
- https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
