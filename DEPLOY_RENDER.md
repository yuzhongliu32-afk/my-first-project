# Running the Harbourline site

## On this computer

```
.venv\Scripts\python.exe -m harbourline.site_server --env-file .env --library data/evidence_library.json
```

Open http://127.0.0.1:8080/. Jira writes are done locally only, behind a human approval:
`harbourline.operations jira-preview` → `approve_jira.bat` (type APPROVE) → `jira-apply` → `jira-read`.

## On Render (public link)

Web Service from the public repository, branch `full-system`.

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements-live.txt` |
| Start command | `python -m harbourline.site_server --host 0.0.0.0 --library /etc/secrets/evidence_library.json --sources /etc/secrets/brief_source_registry.json --db /tmp/governance.sqlite --runs /tmp/site_runs` |
| Instance type | Free |

Environment variables (Render dashboard, never in the repository):

| Name | Purpose |
|---|---|
| `PYTHON_VERSION` | `3.12.7` |
| `OPENAI_API_KEY` | key for live runs |
| `OPENAI_MODEL` | e.g. `gpt-6-luna` |
| `OPENAI_REASONING_EFFORT` | e.g. `low` |
| `OPENAI_MAX_OUTPUT_TOKENS` | e.g. `32000` |
| `OPENAI_TIMEOUT_SECONDS` | e.g. `180` |
| `MEMBER_B_ACCESS_CODE` | presentation access code for the run buttons |
| `SITE_MAX_RUNS` | cap on OpenAI runs per server start, e.g. `5` |
| `HARBOURLINE_DATA_PACK_DIR` | `/etc/secrets/pack_sources.json` |

Secret files (course material, kept out of the repository): `evidence_library.json`,
`brief_source_registry.json` (built by `scripts/prepare_evidence.py`) and `pack_sources.json`
(built by `scripts/export_pack_bundle.py`; B reads the Data Pack from it). `/api/status` → `checks` shows each loads.

The cloud copy does not hold Jira credentials. It shows the verified run and Jira read-back
published in `web/site/data/recorded/` (exported with `scripts/publish_recorded_run.py`).
Render's free tier sleeps when idle; the first visit can take about a minute.
