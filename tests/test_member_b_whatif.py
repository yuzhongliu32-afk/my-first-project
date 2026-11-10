"""What-if arithmetic runs in code (Week 12: Reason -> Compute -> Check)."""
import copy
import unittest

from modules.member_b.agent import _check_model_bundles, _expand
from modules.member_b.whatif import compute, pert, simulate, validate_proposal
from tests.test_member_b_dynamic_ai import FakeLibrary, draft_plan, draft_risk, whatif_proposal
from modules.member_b.agent import _catalog


def el(o, m, p):
    return {'optimistic': o, 'most_likely': m, 'pessimistic': p}


class ArithmeticTests(unittest.TestCase):
    def test_pert_matches_week12_slide(self):
        mean, sigma = pert(25, 40, 60)
        self.assertAlmostEqual(mean, 40.83, places=2)
        self.assertAlmostEqual(sigma, 5.83, places=2)

    def test_monte_carlo_matches_worked_example(self):
        # Week 12 slide 26: three elements, P50 ~ S$59k, P80 ~ S$64k.
        out = simulate([el(25, 40, 60), el(8, 12, 20), el(3, 5, 8)])
        self.assertEqual(out['draws'], 10_000)
        self.assertAlmostEqual(out['p50'], 59, delta=1.5)
        self.assertAlmostEqual(out['p80'], 64, delta=1.5)
        self.assertAlmostEqual(out['combined_sigma'], 6.2, delta=0.1)

    def test_rerun_is_stable(self):
        a = simulate([el(350, 450, 600)])
        b = simulate([el(350, 450, 600)])
        self.assertEqual(a, b)

    def test_degenerate_range(self):
        out = simulate([el(4, 4, 4)])
        self.assertEqual((out['p50'], out['p80']), (4, 4))


class ProposalChecks(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog(FakeLibrary())
        self.plan, self.risk = draft_plan(), draft_risk()

    def check(self, proposal):
        validate_proposal(proposal, self.catalog, self.plan, self.risk)

    def test_valid_proposal_computes_contract_fields(self):
        p = whatif_proposal()
        self.check(p)
        records, details = compute(p)
        r = records[0]
        self.assertEqual(r['estimate_status'], 'QUANTIFIED_ASSUMPTION')
        self.assertEqual(r['cost_impact_sgd'], round(details[0]['cost_sgd_k']['p80'] * 1000))
        self.assertEqual(r['schedule_impact_days'], round(details[0]['schedule_weeks']['p80'] * 7))
        self.assertIn('Computed in code', r['calculation_basis'])
        self.assertTrue(any(a.startswith('UNRESOLVED:') for a in r['assumptions']))

    def test_requires_cost_and_schedule_in_one_scenario(self):
        p = whatif_proposal()
        p['scenarios'][0]['elements'] = p['scenarios'][0]['elements'][:1]
        with self.assertRaisesRegex(ValueError, 'both a cost and a schedule'):
            self.check(p)

    def test_bounds_must_be_ordered(self):
        p = whatif_proposal()
        p['scenarios'][0]['elements'][0]['optimistic'] = 900
        with self.assertRaisesRegex(ValueError, 'optimistic <= most likely'):
            self.check(p)

    def test_every_element_cites_evidence(self):
        p = whatif_proposal()
        p['scenarios'][0]['elements'][0]['source_ids'] = []
        with self.assertRaisesRegex(ValueError, 'cite catalogued'):
            self.check(p)

    def test_unknown_wbs_or_risk_rejected(self):
        p = whatif_proposal()
        p['scenarios'][0]['affected_risk_ids'] = ['R99']
        with self.assertRaisesRegex(ValueError, 'risk IDs'):
            self.check(p)

    def test_off_critical_path_asserts_no_shift(self):
        p = whatif_proposal()
        p['scenarios'][0]['elements'][1]['on_critical_path'] = False
        records, details = compute(p)
        self.assertIsNone(records[0]['schedule_impact_days'])
        self.assertIn('off the critical path', records[0]['calculation_basis'])


class PlanRules(unittest.TestCase):
    """Brief rules enforced in code, not left to the prompt."""
    def setUp(self):
        self.catalog = _catalog(FakeLibrary())
        records, _ = compute(whatif_proposal())
        self.risk = {**draft_risk(), 'scenarios': records}

    def run_check(self, plan):
        _check_model_bundles(_expand(plan, self.catalog), _expand(self.risk, self.catalog), self.catalog)

    def test_valid_plan_passes(self):
        self.run_check(draft_plan())

    def test_unanswered_sponsor_question_cannot_carry_answer(self):
        plan = draft_plan()
        plan['sponsor_questions'][0]['answer'] = 'Assume January 2027'
        with self.assertRaisesRegex(ValueError, 'keep answer null'):
            self.run_check(plan)

    def test_untraceable_wbs_must_be_flagged(self):
        plan = draft_plan()
        plan['wbs_items'][2]['scope_ids'] = []
        with self.assertRaisesRegex(ValueError, 'not traceable'):
            self.run_check(plan)
        plan['wbs_items'][2]['status'] = 'UNRESOLVED'
        self.run_check(plan)

    def test_answered_question_must_cite_sponsor_answer(self):
        plan = draft_plan()
        plan['sponsor_questions'][0].update(status='ANSWERED', answer='Start 4 Jan 2027',
                                            answer_source_ids=['E001'])  # E001 is the brief
        with self.assertRaisesRegex(ValueError, 'SPONSOR_ANSWER'):
            self.run_check(plan)

    def test_answered_question_with_sponsor_answer_passes(self):
        ref = dict(self.catalog['E001'], document_id='SPONSOR-ANSWERS-R1',
                   source_type='SPONSOR_ANSWER', quote='Site possession is Monday 4 January 2027.')
        self.catalog['E900'] = ref
        plan = draft_plan()
        plan['sponsor_questions'][0].update(status='ANSWERED', answer='Site possession 4 Jan 2027',
                                            answer_source_ids=['E900'])
        self.run_check(plan)

    def test_id_format_variants_fixed_but_invented_ids_rejected_with_location(self):
        from modules.member_b.agent import normalize_ids
        plan = draft_plan()
        plan['wbs_items'][2]['source_ids'] = ['e1', 'E01']
        normalize_ids(plan, self.catalog)
        self.assertEqual(plan['wbs_items'][2]['source_ids'], ['E001'])  # duplicates merged
        plan['wbs_items'][2]['source_ids'] = ['E001-E003', 'E2']
        normalize_ids(plan, self.catalog)
        self.assertEqual(plan['wbs_items'][2]['source_ids'], ['E001', 'E002', 'E003'])
        plan['wbs_items'][2]['source_ids'] = ['E003-E009']  # E005+ do not exist: left for the check
        normalize_ids(plan, self.catalog)
        self.assertEqual(plan['wbs_items'][2]['source_ids'], ['E003-E009'])
        plan['wbs_items'][2]['source_ids'] = ['E777']
        normalize_ids(plan, self.catalog)
        with self.assertRaisesRegex(ValueError, r'WBS 1\.1\.1 cited nonexistent evidence ID\(s\) E777'):
            _expand(plan, self.catalog)

    def test_whatif_needs_cost_and_schedule(self):
        self.risk['scenarios'][0]['cost_impact_sgd'] = None
        with self.assertRaisesRegex(ValueError, 'both schedule and cost'):
            self.run_check(copy.deepcopy(draft_plan()))


if __name__ == '__main__':
    unittest.main()
