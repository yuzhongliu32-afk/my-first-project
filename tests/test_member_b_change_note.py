"""Change impact note (Week 12 Template B): model proposes, code checks and computes."""
import copy
import unittest

from modules.member_b.change_note import change_impact_note
from tests.test_member_b_dynamic_ai import FakeLibrary, draft_plan, draft_risk

EVENT = {'event_id': 'CE-01', 'change_type': 'GRANT_ELIGIBILITY_RULING',
         'description': 'Asbestos removal ruled not grant-eligible. No programme change agreed.'}


def good_note():
    est = lambda eid, kind, o, m, p: {
        'element_id': eid, 'label': eid, 'kind': kind,
        'unit': 'SGD_THOUSANDS' if kind == 'COST' else 'WEEKS',
        'optimistic': o, 'most_likely': m, 'pessimistic': p,
        'reason_optimistic': 'low bound E003', 'reason_most_likely': 'E003',
        'reason_pessimistic': 'high bound E003', 'on_critical_path': kind == 'SCHEDULE',
        'source_ids': ['E003']}
    return {
        'affected_elements': [{'element_ref': 'R01', 'element_type': 'RISK',
                               'why_affected': 'Lift risk depends on asbestos works',
                               'b_wbs_ids': ['1.1.2'], 'b_milestone_ids': ['M01'],
                               'b_risk_ids': ['R01'], 'source_ids': ['E002']}],
        'estimates': [est('Removal', 'COST', 350, 450, 600)],
        'contingency': {'before_sgd': 1_180_000, 'basis': 'Budget less contract and fees',
                        'source_ids': ['E003']},
        'funding_status': 'NAMED_IN_SOURCES',
        'funding': [{'source_name': 'Council budget', 'what_it_covers': 'Ineligible works',
                     'source_ids': ['E003']}],
        'decision': {'who': 'Estate Development Committee', 'what': 'approve the variation from Council funds',
                     'amount_or_date': 'S$600k ceiling', 'deadline': 'April 2027 committee',
                     'sentence': 'The Committee approves up to S$600k from Council funds before the April 2027 meeting.'},
        'unresolved': [{'item': 'Roof strengthening cost', 'would_be_settled_by': 'Structural survey'}],
        'conflicts': [{'topic': 'Completion date', 'value_a': '31 Oct 2028', 'value_a_source_ids': ['E001'],
                       'value_b': '31 Dec 2028', 'value_b_source_ids': ['E004']}],
    }


class Gateway:
    def __init__(self, *notes):
        self.notes, self.calls = list(notes), []

    def ask(self, name, schema, instructions, payload):
        self.calls.append((name, payload))
        return copy.deepcopy(self.notes.pop(0))


class ChangeNoteTests(unittest.TestCase):
    def run_note(self, *notes):
        g = Gateway(*notes)
        return change_impact_note(EVENT, draft_plan(), draft_risk(), FakeLibrary(), g), g

    def test_note_computed_in_code(self):
        out, g = self.run_note(good_note())
        self.assertEqual(g.calls[0][0], 'harbourline_b_change_note')
        cost = out['result']['cost_sgd_k']
        self.assertEqual(cost['draws'], 10_000)
        self.assertTrue(350 <= cost['p50'] <= cost['p80'] <= 600)
        c = out['contingency']
        self.assertEqual(c['after_p80_sgd'], round(1_180_000 - cost['p80'] * 1000))
        self.assertEqual(c['gap_at_p80_sgd'], 0)
        self.assertEqual(out['stale_risk_ids'], ['R01'])
        self.assertFalse(out['approved'])
        self.assertEqual(out['conflicts'][0]['value_b_refs'][0]['line_start'], 4)

    def test_evasive_decision_is_sent_back(self):
        bad = good_note()
        bad['decision']['sentence'] = 'Monitor closely and engage stakeholders.'
        out, g = self.run_note(bad, good_note())
        self.assertEqual(len(g.calls), 2)
        self.assertIn('not a decision', ' '.join(g.calls[1][1]['prior_findings']))
        self.assertEqual(out['attempts'][0]['findings'][0][:23], 'MECHANICAL_CHECK_FAILED')

    def test_uncited_funding_source_rejected(self):
        bad = good_note()
        bad['funding'][0]['source_ids'] = []
        with self.assertRaisesRegex(ValueError, 'Funding source'):
            self.run_note(bad, copy.deepcopy(bad))

    def test_unresolved_funding_has_no_sources(self):
        note = good_note()
        note['funding_status'], note['funding'] = 'UNRESOLVED', []
        out, _ = self.run_note(note)
        self.assertEqual(out['funding_status'], 'UNRESOLVED')

    def test_unknown_contingency_stays_unknown(self):
        note = good_note()
        note['contingency'] = {'before_sgd': None, 'basis': 'Not stated in the files', 'source_ids': []}
        out, _ = self.run_note(note)
        self.assertIsNone(out['contingency']['after_p80_sgd'])

    def test_invented_plan_ids_rejected(self):
        bad = good_note()
        bad['affected_elements'][0]['b_wbs_ids'] = ['9.9']
        with self.assertRaisesRegex(ValueError, 'not in the B plan'):
            self.run_note(bad, copy.deepcopy(bad))

    def test_empty_unresolved_rejected(self):
        bad = good_note()
        bad['unresolved'] = []
        with self.assertRaisesRegex(ValueError, 'UNRESOLVED is empty'):
            self.run_note(bad, copy.deepcopy(bad))


if __name__ == '__main__':
    unittest.main()
