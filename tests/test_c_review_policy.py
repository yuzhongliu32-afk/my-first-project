"""Offline policy/flow regressions, not claims about a live model's error-detection rate."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from harbourline.llm import ModelGateway
from harbourline.pipeline import run_project
from harbourline.simulation import ScriptedModel
from harbourline.sources import build_library
from modules.member_c.review_policy import C_REVIEW_POLICY_VERSION, DISCLOSURE_RULES
from modules.member_c.service import (critic_instructions, directed_evidence,
                                     generate_reports, progress_table_evidence, with_context)

ROOT = Path(__file__).resolve().parents[1]
PROGRESS_LINES = [
    '2. Progress', 'Measure', 'Planned (cumulative)', 'Actual (cumulative)', 'Variance',
    'Overall physical progress', '6.0%', '3.5%', '-2.5%',
    'Design (D&B) completion', '35%', '26%', '-9%',
    'Submittals approved', '19', '10', '-9', '3. Key issues', 'Removal sequence unconfirmed.',
]


class RecordingGateway(ModelGateway):
    def __init__(self, script):
        super().__init__(responder=script)
        self.instructions = []

    def ask(self, name, schema, instructions, payload):
        self.instructions.append((name, instructions, deepcopy(payload)))
        return super().ask(name, schema, instructions, payload)


class GapScript(ScriptedModel):
    def __init__(self, finding=None, verdict='PASS'):
        super().__init__()
        self.finding, self.verdict = finding, verdict

    def __call__(self, name, payload):
        if name == 'harbourline_report_draft':
            result = super().__call__(name, payload)
            result['sections'][0]['text'] += (
                ' Actual expenditure against eligible cost is unavailable at cutoff. '
                'The submitted claim amount is not certified or paid expenditure.')
            result['open_issues'] += ['Finance should supply actual expenditure and the eligible/ineligible allocation; follow-up date is not established.']
            return result
        if name == 'harbourline_critic_draft':
            self.calls.append((name, deepcopy(payload)))
            return {'verdict': self.verdict, 'findings': [deepcopy(self.finding)] if self.finding else []}
        return super().__call__(name, payload)


def finding(category='MISSING_INFORMATION', severity='MINOR', description='Finance follow-up remains open.'):
    return {'category': category, 'severity': severity, 'section_id': 'SEC-01',
            'description': description, 'required_fix': 'Keep the supported disclosure and request confirmation.',
            'evidence_ids': []}


class CReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        records = json.loads((ROOT / 'examples/test_source_registry.json').read_text())
        records.append({'document_id': 'MARCH-TABLE', 'version': '1', 'source_type': 'DATA_PACK',
                        'page': 1, 'lines': PROGRESS_LINES})
        self.lib = build_library(records, self.root / 'library.json',
                                 metadata={'MARCH-TABLE': {'available_from': '2027-04-06'}})
        self.request = json.loads((ROOT / 'examples/request.json').read_text())
        self.request.update(source_snapshot_id=self.lib.snapshot, run_id='TEST-C-POLICY')
        self.request['request'].update(requested_report_type='MONTHLY_GRANT', max_review_rounds=1,
                                      reporting_period={'start_date': '2027-03-01', 'end_date': '2027-03-31'})
        registry = self.root / 'registry.json'
        registry.write_text(json.dumps(records))
        full, _ = run_project(self.request, self.lib.path, cutoff='2027-04-06',
                              b_context={'source_registry_path': str(registry)},
                              c_gateway=ModelGateway(responder=ScriptedModel()))
        self.context = {'planning': full['planning'], 'risk': full['risk'],
                        'as_of_date': '2027-04-06', 'b_source_evidence': []}

    def generate(self, script):
        gateway = RecordingGateway(script)
        _, output = generate_reports(self.request, self.context, self.lib, gateway)
        return output, gateway

    def test_handled_gap_and_minor_followup_do_not_force_revision(self):
        output, gateway = self.generate(GapScript(finding(), 'PASS'))
        self.assertEqual(output['reports'][0]['status'], 'READY_FOR_HUMAN_REVIEW')
        review = output['critic_reviews'][0]
        self.assertEqual(review['verdict'], 'PASS')
        self.assertEqual(review['findings'][0]['severity'], 'MINOR')
        self.assertIn(C_REVIEW_POLICY_VERSION, review['reviewer_notes'])
        self.assertIn('not formal grant completeness', review['reviewer_notes'])
        self.assertFalse(any(name == 'harbourline_revision' for name, _, _ in gateway.instructions))
        self.assertEqual(gateway.metrics()['api_calls'], 0)

    def test_production_critic_receives_calibrated_policy_and_full_report(self):
        _, gateway = self.generate(GapScript())
        _, instructions, payload = next(x for x in gateway.instructions if x[0] == 'harbourline_critic_draft')
        self.assertEqual(instructions, critic_instructions('MONTHLY_GRANT'))
        self.assertIn('HANDLED SOURCE GAP', instructions)
        self.assertIn('REPORT OMISSION', instructions)
        self.assertIn('Counts of approved submittals are counts', instructions)
        self.assertIn('percentage points', instructions)
        self.assertIn('top five risks', instructions)
        self.assertEqual(payload['c_review_policy_version'], C_REVIEW_POLICY_VERSION)
        self.assertTrue(any('Finance' in issue for issue in payload['report']['open_issues']))
        self.assertIn(DISCLOSURE_RULES, next(x[1] for x in gateway.instructions if x[0] == 'harbourline_report_draft'))

    def test_revision_gets_same_disclosure_rules_and_verified_evidence(self):
        self.request['request']['max_review_rounds'] = 2
        output, gateway = self.generate(ScriptedModel(revise_first=True))
        _, instructions, payload = next(x for x in gateway.instructions if x[0] == 'harbourline_revision')
        self.assertIn(DISCLOSURE_RULES, instructions)
        self.assertTrue(payload['verified_evidence'])
        self.assertEqual(output['reports'][0]['revision'], 2)

    def test_five_material_faults_remain_blocking_even_with_finance_disclosure(self):
        faults = [
            ('UNSUPPORTED_CLAIM', 'Invented S$99 million sponsor-approved budget.'),
            ('UNSUPPORTED_CLAIM', 'Claim date changed from 19 March to 19 February.'),
            ('SOURCE_CONFLICT', 'Seabreeze history asserted as a Harbourline event.'),
            ('MISSING_INFORMATION', 'Required tranche topic removed without disclosure.'),
            ('UNSUPPORTED_CLAIM', 'Conditional B what-if represented as actual completion delay.'),
        ]
        for category, description in faults:
            with self.subTest(description=description):
                output, _ = self.generate(GapScript(finding(category, 'MAJOR', description), 'REVISE'))
                self.assertEqual(output['reports'][0]['status'], 'BLOCKED')
                review = output['critic_reviews'][0]
                self.assertEqual(review['verdict'], 'ESCALATE')
                self.assertEqual(review['findings'][0]['severity'], 'MAJOR')
                self.assertEqual(review['findings'][0]['description'], description)

    def test_material_missing_information_is_not_blanket_downgraded(self):
        output, _ = self.generate(GapScript(finding(severity='BLOCKER', description='Known required figure falsely described as unavailable.'), 'ESCALATE'))
        self.assertEqual(output['critic_reviews'][0]['findings'][0]['severity'], 'BLOCKER')
        self.assertEqual(output['reports'][0]['status'], 'BLOCKED')

    def test_explicit_escalation_is_not_silently_rewritten_to_pass(self):
        output, _ = self.generate(GapScript(finding(), 'ESCALATE'))
        self.assertEqual(output['critic_reviews'][0]['verdict'], 'ESCALATE')

    def test_fabricated_evidence_id_still_fails_validation(self):
        class BadCitation(GapScript):
            def __call__(self, name, payload):
                out = super().__call__(name, payload)
                if name == 'harbourline_report_draft': out['sections'][0]['evidence_ids'] = ['INVENTED']
                return out
        with self.assertRaisesRegex(ValueError, 'invented an evidence ID'):
            self.generate(BadCitation())

    def test_progress_table_keeps_percentage_rows_and_submittal_count_label(self):
        before = self.lib.path.read_bytes()
        refs = progress_table_evidence(self.lib, '2027-04-06')
        ref = next(r for r in refs if r['document_id'] == 'MARCH-TABLE')
        self.assertEqual(ref['line_start'], 2)
        self.assertEqual(ref['line_end'], 17)
        self.assertIn('Overall physical progress\n6.0%\n3.5%\n-2.5%', ref['quote'])
        self.assertIn('Submittals approved\n19\n10\n-9', ref['quote'])
        self.lib.verify(ref, '2027-04-06')
        self.assertEqual(before, self.lib.path.read_bytes())
        widened = with_context(directed_evidence(self.lib, '2027-04-06'), self.lib, '2027-04-06')
        self.assertTrue(any('Submittals approved\n19\n10\n-9' in r['quote'] for r in widened))

    def test_future_table_not_passed_to_review(self):
        self.assertEqual(progress_table_evidence(self.lib, '2027-04-05'), [])

    def test_unknown_date_table_not_passed_to_review(self):
        lib = build_library([{'document_id': 'UNKNOWN', 'version': '1', 'source_type': 'DATA_PACK',
                              'page': 1, 'lines': PROGRESS_LINES}], self.root / 'unknown.json')
        self.assertEqual(progress_table_evidence(lib, '2027-04-06'), [])

    def test_cross_page_table_not_relabelled_as_one_page(self):
        record = {'document_id': 'PAGES', 'version': '1', 'source_type': 'DATA_PACK', 'lines': PROGRESS_LINES,
                  'line_pages': [1] * 10 + [2] * (len(PROGRESS_LINES) - 10)}
        lib = build_library([record], self.root / 'pages.json', metadata={'PAGES': {'available_from': '2027-04-06'}})
        self.assertEqual(progress_table_evidence(lib, '2027-04-06'), [])

    def test_table_quote_tampering_still_rejected(self):
        ref = progress_table_evidence(self.lib, '2027-04-06')[0]
        ref['quote'] = ref['quote'].replace('Submittals approved', 'Physical progress percent')
        with self.assertRaisesRegex(ValueError, 'does not match source'):
            self.lib.verify(ref, '2027-04-06')


if __name__ == '__main__':
    unittest.main()
