# Harbourline Community Hub | MA6094
## Run the integrated system

Extract the entire ZIP. Python 3.11 or newer is required. The first launch
installs Python dependencies and needs internet access.

- **macOS**: Open `Start Harbourline.command`. If macOS blocks the shortcut,
  open Terminal in the extracted folder and run `bash "Start Harbourline.command"`.
- **Windows**: Open `Start Harbourline.cmd`.
- Choose **1** for rehearsal or **2** for the live team sandbox. Leave the
  terminal open. If a browser does not open, use the local address it prints.

The operator console runs only on your computer. You do not need a GitHub
account or a repository checkout.

## Rehearsal

Choose **1**. Use the included sample, scripted model responses and simulated
Jira to practise the entire workflow. The browser identifies this mode throughout.
Use the live mode for evidence of a real model run or real Jira writes.

## Live team sandbox

1. For a Data Pack run, put the official data pack in `inputs/Harbourline_Data_Pack.zip`. The
   course brief is already included as `inputs/Harbourline_Brief.pdf`.
2. If available, put verified availability dates and sponsor answers in
   `inputs/verified_source_metadata.json` and
   `inputs/sponsor_answers_registry.json`. Use the formats in
   [the runbook](docs/INTEGRATION_RUNBOOK.md). Undated evidence is excluded from
   time-bounded reporting.
3. Make a local copy of `.env.example` named `.env` next to this guide.
   Set `OPENAI_API_KEY`, `OPENAI_MODEL`, `JIRA_BASE_URL`, `JIRA_EMAIL`,
   `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` and `HARBOURLINE_APPROVERS`. The last
   field must contain the authorised reviewer's local OS username (check
   `whoami` on macOS or `echo %USERNAME%` in Windows Command Prompt).
   Keep tokens personal and out of shared files and recordings.
   Use the team's Jira sandbox and adjust issue-type mappings if needed.
4. Choose **2**. Check the reporting periods and evidence cutoff, then run
   planning, risk and reports. Open the handoff trace and the two report
   drafts to inspect evidence and Critic findings.
5. Click **Build Jira preview** to check the sandbox and list proposed actions.
   The preview performs reads. Have the authorised human review the exact
   payload and target, then approve or reject it. Execute the approved batch,
   inspect readback and download the audit JSON. Keep the sandbox open to
   show the resulting Jira issues.
6. **Analyse a change** is a what-if. It flags affected outputs and invalidates
   outstanding approvals. Use the [runbook](docs/INTEGRATION_RUNBOOK.md)
   for a source-linked course change event, optional semantic indexing or
   report release. Record the difference between a hypothesis and a sourced change.

Download results and the handoff before closing the console. The current
browser session shows its latest run. Run evidence and the audit database
remain under `.local/` for review through the CLI.
