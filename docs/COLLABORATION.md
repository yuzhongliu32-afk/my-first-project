# Shared repository workflow

The repository should be private. Members need their own GitHub account and an
accepted collaborator invitation before viewing or uploading. Member usernames
are not yet supplied; no invitation is represented as sent.

1. Clone the repository and create a branch: member-b/planning or member-c/reporting.
2. Follow docs/TEAM_HANDOFF.md; upload code, dependency list, call example and an
   actual redacted module output. Keep real source material in agreed private storage.
3. Run the local tests and submit a pull request for A's integration review.
4. Avoid direct concurrent edits to shared schemas; discuss changes first.

A checks output compatibility and runs the automatic handoff before merging.
The repository does not yet enforce protected branches or require PR reviews.
No GitHub Actions workflow is included initially; run the documented local checks.

Secrets: copy .env.example locally or set environment variables. .env and runtime
data are ignored. If a key is committed, revoke it with the provider; removing the
latest file alone does not remove it from Git history. Never send keys in group chat.
