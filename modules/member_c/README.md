# Member C — integrated memory and reporting

Original implementation: iriss-086, feature/member-c. Integration preserves the
structured schemas and connects them through `service.py` and `adapter.run`.

- No API client is instantiated at import time.
- A supplies a portable evidence library and the canonical snapshot.
- MEMORY_QUERY supports exact, page-aware citations and optional semantic retrieval.
- GENERATE_REPORTS consumes B's validated planning/risk context.
- Weekly/monthly reporting periods and evidence cut-off are configurable.
- Independent Critic and revision are connected with a bounded round limit.
- Real usage is captured by the shared ModelGateway, never fixed call counts.
- No writable shared data/report_weekly.json or data/report_monthly.json is used
  by the integrated path, avoiding cross-run report collisions.

See docs/INTEGRATION_RUNBOOK.md. Historical standalone scripts and the original
real_memory_output files are retained for provenance, not evidence that this new
integrated flow has run live. Lexical retrieval and scripted tests are explicitly
labelled. Live model access/free quota need actual account verification.
