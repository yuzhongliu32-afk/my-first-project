# Member B Planning + Risk — repository module

This folder contains the deterministic, source-cited project baseline generator for **Harbourline Community Hub** (MA6094). It is not yet a free-tier LLM agent or a Sponsor-approved programme. `status=PARTIAL` represents a proposal awaiting review. 

- **Python entrypoint for A:** `from modules.member_b.adapter import run`; `run(request, context) -> B JSON contract`.
- **Local HTTP entrypoint:** `python -m modules.member_b.http_api --port 8765`, using `POST /v1/plan-risk`. This is optional and not a substitute for the A approval/governance layer.
- **Data setup:** `python -m modules.member_b.prepare_sources --brief "...pdf" --pack "...zip"` (creates **ignored** local `data/` files).
- **Pack demo:** `python -m modules.member_b.demo --pack --integrate`.
- **B request examples:** `examples/member_b_request.json` (brief only), `examples/member_b_pack_request.json` (Jan–Mar 2027 fictional classroom simulation).
- **Change review:** `modules.member_b.change.analyse_change(event, planning, risk)`. No automatic Jira edits or approvals.
- **Install B-specific dependency:** `python -m pip install -r modules/member_b/requirements.txt` (`pypdf`).

The `source_snapshot_id` is either `BRIEF-2026-10-10-ONLY` or `PACK-JAN-MAR-2027-V1`. The same snapshot must be provided to A, B and C; no source files or keys should be committed. See `docs/MEMBER_B_GITHUB_INTEGRATION.md` for repository merge, API shape, test commands and current limitations.
