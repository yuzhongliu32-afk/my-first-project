# C review calibration — 11 November 2026

Policy identifier: `c-review-v2-2026-11-11`. Render serves the Python workflow from
`full-system`; its active C entry point is `modules/member_c/service.py`.

The Critic distinguishes a handled source gap from a report error. When a required
item is genuinely unavailable, the report must name it in its body, retain related
known facts with citations, and name the missing input and confirming role in an
open issue. This alone does not warrant a MAJOR/BLOCKER finding. It may remain a
MINOR follow-up note. No figure, owner appointment, confirmation or deadline is invented.

A submitted cumulative contractor claim must remain a submitted claim. It does
not establish actual expenditure, certified/paid expenditure, grant eligibility,
or disbursement. Required information present in evidence but omitted or misstated
can still be a material finding. Invented amounts, wrong dates/citations, missing
report topics, Seabreeze/Harbourline confusion, stale facts and B scenarios stated
as actual outcomes remain review failures.

Progress retrieval now adds bounded, verified tables with their headers and row
names. It preserves the distinction between physical progress percentages, design
completion percentages and counts of approved submittals. No bare number is given
an inferred unit. Source versions, hashes, page boundaries and date eligibility
checks remain in force.

Production and `scripts/run_evaluation.py` call the same `critic_instructions`.
The legacy CLI Critic shares this policy and verdict resolver. The resolver does
not downgrade model findings or override explicit escalation: MAJOR/BLOCKER
findings still cause revision/escalation, and MINOR-only notes can pass.

PASS means `READY_FOR_HUMAN_REVIEW`. It is not a complete grant-filing certificate,
release permission, baseline approval or Jira-write approval. Review rounds and
existing stop conditions remain in force. Historical reports/reviews are not
rewritten; new generation uses the new policy. `/api/status` exposes only the
policy identifier so the deployed version can be checked without a model call.

Offline tests cover labelled-table retrieval, cut-offs, page and quote checks,
policy propagation, transparent-gap handling and preservation of material findings.
Scripted C01–C05 finding tests verify gating, not live model fault-detection accuracy.
Real model calibration has not been rerun as part of this change.
