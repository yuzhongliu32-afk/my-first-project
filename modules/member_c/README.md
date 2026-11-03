
# Module C — Memory & Reporting

## Technology
Python 3.11+ / OpenAI Responses API

## Entry Point
modules.member_c.adapter.run(request, context)

## Implemented
- Memory/RAG with semantic retrieval
- Verified document and line citations
- SUPPORTED, PARTIAL, UNRESOLVED, NOT_FOUND
- Weekly Committee Report Writer
- Monthly Grant Report Writer
- Independent Critic Agent
- Two-round Writer-Critic review loop
- Evidence date filtering
- C JSON Schema validation

## Live Test
MEMORY_QUERY tested successfully:
- Status: SUCCESS
- Answer: S$18.5 million approved budget
- Verified citations: 2
- Errors: none

## Current Limitations
- Reporting integration is limited to a March 2027 test configuration.
- B Planning/Risk context is not yet integrated.
- The full review loop is not yet connected to adapter.run().
- Four source files have unverified availability dates.
- Evidence indexes currently use local development links.
- API call counts are provisional; token and cost
  metrics still require runtime instrumentation.
- A verified free-tier execution route is pending.

## Security
Set OPENAI_API_KEY in the backend environment.
Never commit .env files or API credentials.

## Schema
schemas/Harbourline_C_Schema.json

## Integration Status
MEMORY_QUERY: Live tested.
GENERATE_REPORTS: Partial integration.
B-to-C handoff: Pending.
