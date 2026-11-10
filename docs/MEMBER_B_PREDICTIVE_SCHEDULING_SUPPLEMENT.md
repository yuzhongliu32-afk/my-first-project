# Member B — Predictive Scheduling Supplement (Optional Proposal)

**Status: proposal only. This file does not add a working feature or change the deployed demo.**

## Existing What-if capabilities — preserve as-is

- **SC01 — asbestos removal sensitivity:** six-week *user assumption* = 42 calendar days; S$600,000 incremental *user-assumed* cost. The impact on the actual whole-project finish date is **not proven**: zero recoverable float and one-to-one critical-path propagation are assumptions.
- **SC02 — lift closures:** contractor's conditional 6–8 week delay; upper-bound activity impact 8 × 7 = 56 calendar days. Cost **UNKNOWN** without reliable price evidence.
- **SC03 — childcare handover conflict:** project sources disagree on the handover date (contractual 30 June 2028 vs an unspecified August 2028 date). Exact day difference and cost **UNKNOWN**. Keep both dates and references; do not invent an August day.

These results remain illustrative, not approved variations or automatically revised baselines.

## Suggested separate enhancement: Predictive Scheduling

**Question:** Do the conditional activity delays actually delay final project completion or an external approval/grant trigger?

### Required evidence inputs
1. Verified start anchor, working-day/calendar-day rule and as-of date.
2. Activity IDs and Level 3 WBS link, durations, actual progress, and predecessor relationships, with file/row citations.
3. Contractor updates and milestone dates, including conflicting date values.
4. External deadlines from grant conditions (file 07), not just the internal programme finish.
5. Lessons learned (file 06) for possible outside-view adjustment.
6. Scenario assumption and its provenance: source fact, user hypothesis or unresolved.

Missing or conflicting prerequisites must yield **UNRESOLVED**, not a fabricated completion date.

### Analysis approach: REASON → COMPUTE → CHECK

1. **Reason:** build a transparent, source-cited date/dependency chain; identify the single driving assumption and conflicting rows.
2. **Compute:** deterministic critical-path and total-float calculation in code; calculate forecast finish, project finish shift and float to *each external trigger*. Do not equate an activity's 42/56-day delay with the whole project's delay unless dependencies and remaining float support it.
3. **Check:** verify referenced rows and dates, DAG/dependency integrity, calendar treatment and arithmetic; mark any unverified dates/costs as unknown; require human approval for baseline changes.

### Proposed UI/output
- Baseline date, as-of date and **forecast finish**, with whether the date is *stated*, *calculated* or *unresolved*.
- Critical path with activity IDs, predecessor IDs, durations and clickable source citations.
- One dominant assumption and confidence limitations.
- Scenario ID; activity delay vs calculated whole-project finish shift; recovered float and affected milestones.
- External trigger date, float in weeks, source citation and consequence.
- Date conflicts, unknown cost, missing dependencies, and suggested Sponsor/PM decisions.
- Status **PROPOSED / ILLUSTRATIVE / UNRESOLVED** until separately approved through Agent A governance.

### Optional numerical uncertainty (only after sourced inputs and working deterministic model)

- Three-point PERT mean = (O + 4M + P)/6; sigma ≈ (P − O)/6.
- P50 / P80 require a coded, reproducible simulation and explicit distribution assumptions; **never claim probabilities generated solely by a model's prose**.
- Cost changes should distinguish contingency (PM risk response) from management reserve (Sponsor approval).

### Suggested tests before implementation is called complete

1. Non-critical task slips within float: final completion does not change.
2. Critical task slips beyond available float: computed finish shifts appropriately.
3. Dependency cycle / missing predecessor: reject as UNRESOLVED.
4. Conflicting contractor and contract dates: preserve both with exact source rows.
5. No precise August handover day: SC03 exact day delta remains UNKNOWN.
6. SC01: 42-day conditional scenario does **not** assert 42-day final project delay.
7. SC02: 56-day conditional upper bound, cost UNKNOWN.
8. Missing grant trigger or supporting row: float to that trigger UNKNOWN.
9. Repeated runs with same input reproduce results.
10. No baseline, approved change, Jira task or C report is modified without Agent A's review-and-approval workflow.

## Team integration and demo note

Implement in a **new function/panel**, not by overwriting existing WBS, Risk Register or What-if. Keep the shared B schema stable until Member A and C agree to an extension. Validate the actual deployed site separately.

Demo (only **after** working feature verified): “Our current What-if cards show conditional activity-delay and cost sensitivities. This extension uses verified task dependencies and external deadlines to evaluate whether a delay actually moves project completion. Where evidence is incomplete, it reports unresolved rather than guessing.”

## Course framing

MA6094 Week 12 slides and Student Hands-on Guide discuss schedule forecasting, float to external triggers, evidence-linked date chains, three-point cost estimates, P50/P80 and the **REASON → COMPUTE → CHECK** method. Both explicitly note that the Week 12 hands-ons **are not an additional Capstone requirement**. This document is therefore an **optional enhancement**, not a new mandatory deliverable.
