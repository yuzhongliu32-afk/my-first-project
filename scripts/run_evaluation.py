"""Evaluation cases that need the model (Deliverable 3): planted faults for the C critic (C01-C05),
memory questions (M01-M03) and the Week 12 change notes (W01-W02), all against the verified run.

The critic is called exactly as modules/member_c/service.py calls it (same prompt, schema and payload
shape), on the report that passed in the verified run. A control round on the unmodified report is run
first, so a catch is only counted when the control passed.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from harbourline.llm import ModelGateway  # noqa: E402
from harbourline.sources import EvidenceLibrary, digest  # noqa: E402
from modules.member_c.service import BASE, CRITIC_SCHEMA, memory_query, REPORT_REQUIREMENTS  # noqa: E402

FAULTS = {
    'C01': ('Unsupported budget claim', 'Expenditure', 'append',
            ' The sponsor approved a S$99 million final budget for the Hub in March 2027.'),
    'C02': ('Wrong date', 'Tranche', 'replace', ('submitted on 19 March', 'submitted on 19 February')),
    'C03': ('Seabreeze history stated as Harbourline fact', 'Progress', 'append',
            ' Harbourline has already had a grant tranche delayed by four months because an operator agreement was not signed.'),
    'C04': ('Required grant item removed', 'Tranche', 'delete', None),
    'C05': ('B what-if stated as an actual outcome', 'Progress', 'append',
            ' Asbestos removal will delay practical completion by exactly 6 weeks.'),
}
QUESTIONS = {
    'M01': 'When was the NRF Tranche 1 claim submitted?',
    'M02': 'What is the confirmed appointment date for the active ageing centre operator?',
    'M03': 'Was a grant tranche delayed because of a missing operator agreement?',
}


def critic_payload(full, report, library):
    refs = {}
    for s in report['sections']:
        for r in s['citations']:
            refs[digest(r)] = r
    lookup = {f'E{i + 1}': r for i, r in enumerate(refs.values())}
    evidence = {k: {f: r[f] for f in ('document_id', 'page', 'line_start', 'line_end', 'quote')} for k, r in lookup.items()}
    plan, risk = full['planning'], full['risk']
    b_context = {
        'planning': {'scope_statement': plan['scope_statement'],
                     'wbs_items': [{k: w[k] for k in ('wbs_id', 'title', 'status')} for w in plan['wbs_items']],
                     'milestones': [{k: m.get(k) for k in ('milestone_id', 'title', 'relative_timing', 'calendar_date', 'status')} for m in plan['milestones']],
                     'sponsor_questions': [{k: q[k] for k in ('question', 'status')} for q in plan['sponsor_questions']]},
        'risk': {'risks': [{k: r[k] for k in ('risk_id', 'title', 'score', 'owner', 'status')} for r in risk['risks']],
                 'scenarios': [{k: x.get(k) for k in ('scenario_id', 'description', 'schedule_impact_days', 'cost_impact_sgd',
                                                      'calculation_basis', 'estimate_status')} for x in risk['scenarios']]}}
    mem = full['memory']
    return {'report_type': report['report_type'], 'audience': report['audience'], 'period': report['reporting_period'],
            'cutoff': '2027-04-06', 'verified_evidence': evidence,
            'memory': {'facts': [{'statement': f['statement'], 'status': f['status']} for f in mem.get('fact_records', [])],
                       'conflicts': [{k: c[k] for k in ('topic', 'claim_a', 'claim_b')} for c in mem.get('conflicts', [])],
                       'open_questions': mem.get('open_questions', [])},
            'b_context': b_context,
            'proposal_notice': 'B plans, scores and what-if estimates are proposals; do not present them as actual progress.',
            'report': report}


def critique(gateway, full, report, library):
    instructions = (BASE + ' You are an independent critic. Check claims against evidence, audience, dates, source conflicts and '
                    'misrepresentation of B proposals. Return findings, never approve or rewrite.')
    out = gateway.ask('harbourline_critic_draft', CRITIC_SCHEMA, instructions, critic_payload(full, report, library))
    blocking = [f for f in out['findings'] if f['severity'] in ('BLOCKER', 'MAJOR')]
    return {'verdict': out['verdict'], 'blocking': len(blocking),
            'findings': [{k: f[k] for k in ('severity', 'category', 'section_id', 'description')} for f in out['findings']]}


def plant(report, fault):
    _, where, how, text = fault
    r = deepcopy(report)
    idx = next(i for i, s in enumerate(r['sections']) if where.lower() in s['heading'].lower())
    if how == 'append':
        r['sections'][idx]['text'] += text
    elif how == 'replace':
        old, new = text
        assert old in r['sections'][idx]['text'], f'{old!r} not in section'
        r['sections'][idx]['text'] = r['sections'][idx]['text'].replace(old, new)
    elif how == 'delete':
        del r['sections'][idx]
    return r, r['sections'][idx]['section_id'] if how != 'delete' else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('record', type=Path)
    p.add_argument('--library', type=Path, default=ROOT / 'data/evidence_library.json')
    p.add_argument('--out', type=Path, default=ROOT / '.local/eval/model_cases.json')
    p.add_argument('--only', nargs='*')
    a = p.parse_args()
    load_dotenv(ROOT / '.env', interpolate=False, override=False)
    record = json.loads(a.record.read_text(encoding='utf-8'))
    full = record['full']
    report = full['reporting']['reports'][0]
    library = EvidenceLibrary(a.library)
    results = json.loads(a.out.read_text(encoding='utf-8')) if a.out.exists() else {}
    want = set(a.only or ['CONTROL', *FAULTS, *QUESTIONS, 'W01', 'W02'])

    def save():
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')

    if 'CONTROL' in want:
        g = ModelGateway(); t = time.monotonic()
        results['CONTROL'] = {**critique(g, full, report, library), 'metrics': g.metrics(), 'seconds': round(time.monotonic() - t, 1)}
        save(); print('CONTROL', results['CONTROL']['verdict'], results['CONTROL']['blocking'])
    for cid, fault in FAULTS.items():
        if cid not in want:
            continue
        planted, section = plant(report, fault)
        g = ModelGateway(); t = time.monotonic()
        res = critique(g, full, planted, library)
        results[cid] = {'fault': fault[0], 'planted_in': section, **res, 'metrics': g.metrics(),
                        'seconds': round(time.monotonic() - t, 1)}
        save(); print(cid, res['verdict'], res['blocking'])
    for qid, question in QUESTIONS.items():
        if qid not in want:
            continue
        g = ModelGateway(); t = time.monotonic()
        m = memory_query(question, library, g, '2027-04-06')
        results[qid] = {'question': question, 'answer_status': m['answer_status'], 'answer': m['answer'],
                        'citations': [f"{c['document_id']} L{c['line_start']}-{c['line_end']}" for c in m['citations']],
                        'open_questions': m['open_questions'], 'metrics': g.metrics(), 'seconds': round(time.monotonic() - t, 1)}
        save(); print(qid, m['answer_status'])
    for wid, event_id in (('W01', 'CE-01'), ('W02', 'CE-02')):
        if wid not in want:
            continue
        from modules.member_b.change_note import change_impact_note
        e = json.loads((ROOT / f'examples/change_events/{event_id}.json').read_text(encoding='utf-8'))
        event = {'event_id': e['event_id'], 'change_type': e['change_type'], 'description': e['description']}
        g = ModelGateway(); t = time.monotonic()
        try:
            note = change_impact_note(event, full['planning'], full['risk'], library, g)
            results[wid] = {'event': event_id, 'status': note.get('status'), 'funding_status': note.get('funding_status'),
                            'decision': (note.get('decision') or {}).get('sentence'),
                            'stale_wbs_ids': note.get('stale_wbs_ids'), 'stale_milestone_ids': note.get('stale_milestone_ids'),
                            'stale_risk_ids': note.get('stale_risk_ids'), 'stale_reports': note.get('stale_reports'),
                            'result': note.get('result'), 'unresolved': note.get('unresolved'),
                            'metrics': g.metrics(), 'seconds': round(time.monotonic() - t, 1), 'note': note}
        except Exception as exc:  # recorded as a failed case, not hidden
            results[wid] = {'event': event_id, 'error': f'{type(exc).__name__}: {str(exc)[:400]}',
                            'metrics': g.metrics(), 'seconds': round(time.monotonic() - t, 1)}
        save(); print(wid, results[wid].get('status') or results[wid].get('error'))


if __name__ == '__main__':
    main()
