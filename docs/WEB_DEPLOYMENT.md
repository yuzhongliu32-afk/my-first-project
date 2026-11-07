# Harbourline live web workspace

The Python web workspace calls the A/B/C integration. The same workspace
provides evidence search, run results, human approval, sandbox readback and
audit export. Configure one instance with one worker and a persistent workspace.

## Set up on a Python host

1. Install `requirements-web.txt` or build with the supplied Dockerfile.
2. Set `HARBOURLINE_WORKSPACE` to a persistent directory writable by the service.
   Create an `inputs` folder in that directory. Place the instructor's PDF at
   `inputs/Harbourline_Brief.pdf`. Add the official pack as
   `inputs/Harbourline_Data_Pack.zip` and `inputs/verified_source_metadata.json`
   from the delivery bundle. Copy both alongside the brief into the host’s
   persistent inputs folder. The workspace identifies Brief-only coverage if
   the official pack is absent.
3. Set the model and team Jira sandbox environment variables described in
   [the integration runbook](INTEGRATION_RUNBOOK.md). Store them in the host's
   secret settings. The app never asks a visitor for Jira or model credentials.
4. Set a random session key in `HARBOURLINE_WEB_SESSION_KEY` and a JSON object
   in `HARBOURLINE_WEB_USERS`. Use a different randomly generated access key
   for every named person. Share the key directly with that person and put only
   its SHA-256 digest in the account configuration. For example, generate one
   key/digest pair locally:

   ```bash
   python -c 'import hashlib,secrets; key=secrets.token_urlsafe(32); print(key); print(hashlib.sha256(key.encode()).hexdigest())'
   ```

   The mapping has the form
   `{"reviewer-name":{"role":"runner","key_sha256":"<64 lowercase hex characters>"}}`.
   A `viewer` reads and downloads outputs, a `runner` can also run the real
   workflow and an `approver` handles the team's Jira checkpoint and changes.
5. Start the service behind HTTPS. For a native Python runtime, run:

   ```bash
   gunicorn --workers 1 --threads 4 --bind "0.0.0.0:${PORT:-8000}" 'harbourline.web:create_app()'
   ```

   The public URL shows a project overview. The evaluator opens the workspace
   using their named access details. The health endpoint is `/healthz`.

## Acceptance run

- Run with the real provider and inspect the actual reports, Critic decisions,
  evidence links and the B-to-C handoff. Confirm the configured provider and
  hosting arrangement meet the course's free-route requirements.
- Start with a Jira preview to verify the read path. Have the designated human
  review and approve the batch, execute it and verify the resulting Jira issues.
  Download the audit trail and rerun to check duplicate handling.
- When the instructor's change is available, add its verified source lines
  to the evidence registry, prepare a current run and provide
  `inputs/week12_change.json` with an `event_id`, `change_type`, `description`
  and exact `source_refs`. The named approver can then review its impact. Use
  the separate what-if form for hypothetical changes.
- After a failed or interrupted write, reconcile the Jira sandbox and audit
  trail before opening a new batch. A batch pending approval can be rejected.
  An approved, interrupted or failed batch that must be abandoned requires
  operator reconciliation using the stored audit and preview.

A service health check confirms the server is reachable. Live model, Jira,
course-data coverage and the free route are separately verified by the acceptance run.


## Official Jan–Mar 2027 evidence bundle

The delivery bundle includes the provided Data Pack ZIP byte-for-byte. Evidence
availability uses the printed contractor report dates (5 Feb, 5 Mar and 6 Apr),
the grant letter issue date (19 Jan), and each of the six EDC meeting dates.
For the four other sources, 6 Apr is the assumed availability of the combined
course snapshot, based on its latest dated report. It is not the issue date of
the individual files. These files are excluded from earlier as-of views.

The Data Pack contains no standalone Week 12 change record or posted sponsor
answers. Existing EDC decisions and contractor events are cited as pack
evidence. They do not establish the separate Week 12 scenario.

The official pack was checked end to end with the scripted test model:
20 WBS items, 17 milestones, 17 risks, two report drafts and four Critic reviews.
The automatic handoff was verified. Test results are not live provider or Jira
evidence.
