"""Member B What-if: the model proposes three-point ranges, code does the arithmetic.

Week 12 pattern, Reason -> Compute -> Check:
* Reason: the What-if role reads the evidence, the plan and the risk register and
  proposes, per affected element, an optimistic / most likely / pessimistic value
  with a reason and a cited evidence row for each.
* Compute: this module (not the model) computes PERT mean, sigma, the combined
  spread and a 10,000-draw PERT-beta Monte Carlo, and reads off P50 and P80.
* Check: every bound must cite a catalogued evidence row; a human reviews.

A probability or total the model states without this computation is never used.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

DRAWS = 10_000
COST, SCHEDULE = 'COST', 'SCHEDULE'
UNITS = {COST: 'SGD_THOUSANDS', SCHEDULE: 'WEEKS'}


def element_schema() -> dict:
    return {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'element_id': {'type': 'string'},
            'label': {'type': 'string'},
            'kind': {'type': 'string', 'enum': [COST, SCHEDULE]},
            'unit': {'type': 'string', 'enum': list(UNITS.values())},
            'optimistic': {'type': 'number'},
            'most_likely': {'type': 'number'},
            'pessimistic': {'type': 'number'},
            'reason_optimistic': {'type': 'string'},
            'reason_most_likely': {'type': 'string'},
            'reason_pessimistic': {'type': 'string'},
            'on_critical_path': {'type': 'boolean'},
            'source_ids': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['element_id', 'label', 'kind', 'unit', 'optimistic', 'most_likely',
                     'pessimistic', 'reason_optimistic', 'reason_most_likely',
                     'reason_pessimistic', 'on_critical_path', 'source_ids'],
    }


def proposal_schema() -> dict:
    scenario = {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'scenario_id': {'type': 'string'},
            'title': {'type': 'string'},
            'description': {'type': 'string'},
            'assumptions': {'type': 'array', 'items': {'type': 'string'}},
            'affected_wbs_ids': {'type': 'array', 'items': {'type': 'string'}},
            'affected_risk_ids': {'type': 'array', 'items': {'type': 'string'}},
            'elements': {'type': 'array', 'items': element_schema()},
            'unresolved': {'type': 'array', 'items': {'type': 'string'}},
            'source_ids': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['scenario_id', 'title', 'description', 'assumptions', 'affected_wbs_ids',
                     'affected_risk_ids', 'elements', 'unresolved', 'source_ids'],
    }
    return {'type': 'object', 'additionalProperties': False,
            'properties': {'scenarios': {'type': 'array', 'items': scenario}},
            'required': ['scenarios']}


INSTRUCTIONS = (
    ' Your role is WHAT-IF ANALYST. You did not write the plan and have no stake in it looking good. '
    'Propose up to three distinct what-if scenarios for this project, each tied to risks in the register. '
    'At least one scenario must carry BOTH a cost element and a schedule element. '
    'For every affected element give optimistic, most likely and pessimistic values '
    '(cost in S$ thousands, schedule in weeks), a reason for each bound, and the evidence IDs that '
    'justify the bounds. Use figures that appear in the evidence; where the evidence gives no figure, '
    'do not invent one: leave that element out and list it under unresolved. No round numbers without '
    'a reason. Mark on_critical_path true only for schedule elements that delay completion in series. '
    'Do NOT state totals, P50, P80, probabilities or likelihood words: code computes those. '
    'Where two sources disagree, record both in assumptions and do not pick one.'
)


def pert(o: float, m: float, p: float) -> tuple[float, float]:
    return (o + 4 * m + p) / 6, (p - o) / 6


def _seed(payload) -> int:
    # Deterministic per input, so re-running the same proposal gives the same P50/P80.
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return int(digest[:12], 16)


def simulate(elements: list[dict], *, draws: int = DRAWS, seed: int | None = None) -> dict | None:
    """Sum independent PERT-beta draws per element; return P50/P80 and PERT summary."""
    if not elements:
        return None
    rng = random.Random(_seed(elements) if seed is None else seed)
    totals = []
    for _ in range(draws):
        total = 0.0
        for e in elements:
            o, m, p = e['optimistic'], e['most_likely'], e['pessimistic']
            if o == p:
                total += o
            else:  # PERT-beta: consistent with the PERT mean and sigma shown beside it
                a = 1 + 4 * (m - o) / (p - o)
                b = 1 + 4 * (p - m) / (p - o)
                total += o + (p - o) * rng.betavariate(a, b)
        totals.append(total)
    totals.sort()
    means = [pert(e['optimistic'], e['most_likely'], e['pessimistic']) for e in elements]
    return {'draws': draws, 'method': 'PERT-beta Monte Carlo, independent elements, summed',
            'pert_mean_total': round(sum(m for m, _ in means), 2),
            'combined_sigma': round(math.sqrt(sum(s * s for _, s in means)), 2),
            'p50': round(totals[int(0.5 * draws) - 1], 2),
            'p80': round(totals[int(0.8 * draws) - 1], 2),
            'min': round(totals[0], 2), 'max': round(totals[-1], 2)}


def check_element(e: dict, catalog: dict, tag: str) -> None:
    """One three-point element: ordered numeric bounds, a reason per bound, cited rows."""
    if e['unit'] != UNITS[e['kind']]:
        raise ValueError(f'{tag}: unit must be {UNITS[e["kind"]]} for {e["kind"]}')
    o, m, p = e['optimistic'], e['most_likely'], e['pessimistic']
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (o, m, p)):
        raise ValueError(f'{tag}: three-point values must be numbers')
    if not 0 <= o <= m <= p:
        raise ValueError(f'{tag}: needs 0 <= optimistic <= most likely <= pessimistic')
    limit = 20_000 if e['kind'] == COST else 260
    if p > limit:
        raise ValueError(f'{tag}: pessimistic value {p} is outside a plausible range')
    bad = [x for x in e['source_ids'] if x not in catalog]
    if not e['source_ids'] or bad:
        raise ValueError(f'{tag}: every element must cite catalogued evidence IDs'
                         + (f' (unknown: {", ".join(map(str, bad[:5]))})' if bad else ' (none given)'))
    if not all(e[k].strip() for k in ('reason_optimistic', 'reason_most_likely', 'reason_pessimistic')):
        raise ValueError(f'{tag}: each bound needs a reason')


def validate_proposal(proposal: dict, catalog: dict, planning: dict, risk: dict) -> None:
    """Mechanical checks on the model's ranges; raises ValueError with a fixable message."""
    wbs = {w['wbs_id'] for w in planning['wbs_items']}
    risks = {r['risk_id'] for r in risk['risks']}
    scenarios = proposal['scenarios']
    if not scenarios:
        raise ValueError('What-if produced no scenarios')
    if len({s['scenario_id'] for s in scenarios}) != len(scenarios):
        raise ValueError('Duplicate what-if scenario IDs')
    both = False
    for s in scenarios:
        sid = s['scenario_id']
        if not set(s['affected_wbs_ids']) <= wbs:
            raise ValueError(f'{sid} links to WBS IDs that are not in the plan')
        if not set(s['affected_risk_ids']) <= risks:
            raise ValueError(f'{sid} links to risk IDs that are not in the register')
        if not s['affected_risk_ids']:
            raise ValueError(f'{sid} must be tied to at least one risk in the register')
        bad = [x for x in s['source_ids'] if x not in catalog]
        if bad:
            raise ValueError(f'{sid} cites nonexistent evidence ID(s) {", ".join(map(str, bad[:5]))}; '
                             'use only IDs from the evidence list')
        kinds = set()
        for e in s['elements']:
            check_element(e, catalog, f"{sid}/{e['element_id']}")
            kinds.add(e['kind'])
        both = both or kinds == {COST, SCHEDULE}
    if not both:
        raise ValueError('At least one what-if must carry both a cost and a schedule element '
                         '(Brief Module 4 minimum)')


def compute(proposal: dict) -> tuple[list[dict], list[dict]]:
    """Return (contract WhatIf records with short evidence IDs, detailed analysis for display)."""
    records, details = [], []
    for s in proposal['scenarios']:
        cost_el = [e for e in s['elements'] if e['kind'] == COST]
        sched_el = [e for e in s['elements'] if e['kind'] == SCHEDULE]
        serial = [e for e in sched_el if e['on_critical_path']]
        cost = simulate(cost_el)
        sched = simulate(serial)
        rows = []
        for e in s['elements']:
            mean, sigma = pert(e['optimistic'], e['most_likely'], e['pessimistic'])
            rows.append({**e, 'pert_mean': round(mean, 2), 'sigma': round(sigma, 2)})
        basis = [f'Computed in code, not stated by the model: {DRAWS:,} PERT-beta draws per element.']
        if cost:
            basis.append(f"Cost S$k: P50 {cost['p50']}, P80 {cost['p80']} "
                         f"(PERT mean {cost['pert_mean_total']}, combined sigma {cost['combined_sigma']}).")
        if sched:
            basis.append(f"Schedule weeks (serial critical-path elements summed): P50 {sched['p50']}, "
                         f"P80 {sched['p80']} (PERT mean {sched['pert_mean_total']}).")
        if sched_el and not serial:
            basis.append('Schedule elements are off the critical path, so no completion shift is asserted.')
        basis.append('Contract fields carry the P80 values (budget to P80, plan to P50).')
        three_point = [f"{e['label']} ({e['kind'].lower()}, {e['unit']}): O {e['optimistic']} / "
                       f"M {e['most_likely']} / P {e['pessimistic']} — O: {e['reason_optimistic']}; "
                       f"M: {e['reason_most_likely']}; P: {e['reason_pessimistic']}" for e in s['elements']]
        sources = list(dict.fromkeys(s['source_ids'] + [x for e in s['elements'] for x in e['source_ids']]))
        quantified = bool(cost or sched)
        records.append({
            'scenario_id': s['scenario_id'],
            'description': f"{s['title']}: {s['description']}",
            'assumptions': s['assumptions'] + three_point
                           + [f'UNRESOLVED: {u}' for u in s['unresolved']],
            'baseline_id': None,
            'schedule_impact_days': round(sched['p80'] * 7) if sched else None,
            'cost_impact_sgd': round(cost['p80'] * 1000) if cost else None,
            'calculation_basis': ' '.join(basis),
            'affected_wbs_ids': s['affected_wbs_ids'],
            'affected_risk_ids': s['affected_risk_ids'],
            'source_ids': sources,
            'estimate_status': 'QUANTIFIED_ASSUMPTION' if quantified else 'UNRESOLVED',
        })
        details.append({'scenario_id': s['scenario_id'], 'title': s['title'],
                        'description': s['description'], 'assumptions': s['assumptions'],
                        'unresolved': s['unresolved'], 'affected_wbs_ids': s['affected_wbs_ids'],
                        'affected_risk_ids': s['affected_risk_ids'], 'elements': rows,
                        'cost_sgd_k': cost, 'schedule_weeks': sched})
    return records, details


def run_whatif(gateway, rules: str, payload: dict, catalog: dict, planning: dict, risk: dict,
               findings: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Ask the What-if role for ranges, check them, compute P50/P80 in code."""
    proposal = gateway.ask('harbourline_b_whatif', proposal_schema(), rules + INSTRUCTIONS,
                           {**payload, 'planning': planning, 'risk': risk,
                            'prior_findings': findings or []})
    from .agent import normalize_ids
    normalize_ids(proposal, catalog)
    validate_proposal(proposal, catalog, planning, risk)
    return compute(proposal)
