# Member B — GitHub merge & A/C interface guide

**Purpose:** Add Member B into the original MA6094 repository without replacing A or C. This archive contains only B-owned files and *new* docs/examples/tests. DO NOT upload the prior full-project ZIP on top of the live repository; Member C stated that the latest work uses HTTP, and the original student ZIP still contains an old C fixture.

## A/B integration (unchanged contract)
- Member A already calls `modules.member_b.adapter.run(request, context)` in `harbourline/integration.py`.
- B returns a `Harbourline_B_Schema.json`-compatible object with `planning` + `risk`, retains source_snapshot_id and IDs, and never writes Jira.
- A validates B and hands `context={"source_snapshot_id": ..., "planning": b["planning"], "risk": b["risk"]}` to the C entrypoint. **Only A** owns approval, Jira, audit, and stale report trigger.
- `status="PARTIAL"` denotes unapproved proposals, not integration failure.

## Optional B HTTP interface to match C's approach
- `python -m modules.member_b.http_api --port 8765`
- `GET http://127.0.0.1:8765/health`
- `POST http://127.0.0.1:8765/v1/plan-risk` takes `{"request": <A B-request>, "context": {"source_snapshot_id": "PACK-JAN-MAR-2027-V1"}}`, returns the **same B schema output**.
- `POST http://127.0.0.1:8765/v1/change-impact` takes `{ "event": {"event_id":"...","change_type":"ASBESTOS_CONFIRMED"}, "planning": b["planning"], "risk": b["risk"] }` and returns a human-review proposal. No automatic writes.
- The C HTTP service's URL/path and body schema **have not been inspected**, so no claim of live A→C HTTP compatibility is made. C needs `planning`, `risk`, and the same `source_snapshot_id`, sent through A. The B server only listens to localhost and is not remotely callable without deployment.

## GitHub upload without overwriting A/C
1. Open original GitHub repo and switch to/create `member-b/planning-risk` branch. Do not commit on `main` before A reviews.
2. Extract `member_b_github_upload.zip`, **upload its contents into the repository root** (NOT the ZIP itself, and NOT a nested `member_b_github_upload/` folder).
3. Existing `modules/member_b/adapter.py` must be replaced deliberately: it was the original B fixture placeholder. Preserve all other shared A/C files. No shared `README.md`, `.gitignore`, `requirements.txt`, `schemas/`, `harbourline/`, or `modules/member_c/` file is changed by this upload.
4. Commit to the B branch, and open a pull request to `main`. Ask A to review the integration and C to confirm its latest HTTP route/schema before enabling network handoff.
5. Never commit teaching material, API tokens, `data/Harbourline_Data_Pack/`, `data/brief_source_registry.json`, `.local/`, or `.env`. Existing `.gitignore` excludes these.

## Local install and test (Python 3.11+)
```bash
python -m pip install -r requirements.txt
python -m pip install -r modules/member_b/requirements.txt
python -m modules.member_b.prepare_sources --brief "path/to/MA6094 Capstone Brief.pdf" --pack "path/to/Harbourline_Data_Pack.zip"
python -m modules.member_b.demo --pack --integrate
python -m unittest discover -s tests -v
```
The `--integrate` demo uses whatever `modules/member_c/adapter.py` is in the local checkout; with the originally uploaded starter it uses an **old fixture**, not C's new HTTP service. Its result is only a contract/hand-off check.

## Local HTTP check
Terminal 1:
```bash
python -m modules.member_b.http_api --port 8765
```
Terminal 2:
```bash
python -m modules.member_b.http_client
```
Creates `.local/member_b_http_output.json`. Response contains `planning` + `risk` and source references. The Pack is a **course fiction with simulated Jan–Mar 2027 records**, not real current progress.

## API context handed from B to C
```json
{
  "source_snapshot_id": "PACK-JAN-MAR-2027-V1",
  "planning": "<value of B response['planning']>",
  "risk": "<value of B response['risk']>"
}
```
This is a field guide, not a literal payload. A generates the actual object and validates it before C receives it. Important fields: `planning.wbs_items[].wbs_id`, `planning.milestones[].predecessor_milestone_ids`, `risk.risks[].related_wbs_ids`, `risk.risks[].score` (can be null for confirmed incidents or invalid inherited entries), `risk.scenarios[]`, `source_evidence[]`.

## Limitations / blockers for final grading
- Current B baseline is **deterministic rules**, not a generative AI model/agent. No approved planning baseline or sponsor answers are included.
- Cannot claim production C HTTP call, Jira write/readback, Critic PASS, and human approvals until A/C live integration is wired and tested.
- C’s new HTTP request/response format must be inspected and adapted in **A's orchestration**; do not blindly change `modules/member_c/` based on screenshots.
- Use free tools where required; retain tests and runtime evidence, explicitly disclose AI assistance in the report.
