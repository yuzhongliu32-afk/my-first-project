# Member B replacement and team integration guide

Target branch: `integration/abc-20261106` (create a NEW branch from it first).

1. Download the complete B ZIP, unzip locally. The `modules/member_b/` folder is **the full replacement**; it is not intended to overwrite A/C.
2. Create `member-b-dynamic-ai` from `integration/abc-20261106`.
3. Upload only the `modules/member_b/` folder and `tests/test_member_b_dynamic_ai.py` to their respective repository paths. Keep all A and C files unchanged.
4. Open PR targeting `integration/abc-20261106`. Do NOT merge or deploy until A checks compatibility and both live and scripted runs have evidence.
5. Use GitHub `Files changed` to verify that only Member B and the new test file changed.

IMPORTANT: The old GitHub runbook is still valid for source preparation, governance and Jira. Live B now uses verified evidence directly and performs independent Planning/Risk/Critic calls via `harbourline.llm.ModelGateway` and the official B JSON schema. It does not grant Jira approvals.

No API keys or student data pack files should be uploaded to GitHub. Configure `OPENAI_API_KEY`, `OPENAI_MODEL`, Jira credentials and verified evidence metadata privately in the backend.

Expected independent local tests (using mocked model) are in `tests/test_member_b_dynamic_ai.py`. These are not evidence of a successful real OpenAI API call. For that, run `live_demo` with a valid project key and attach redacted output metrics and verified citations.
