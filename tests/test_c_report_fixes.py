import json
from pathlib import Path
import tempfile
import unittest
from harbourline.sources import build_library
from harbourline.llm import ModelGateway
from harbourline.simulation import ScriptedModel
from harbourline.pipeline import run_project
from modules.member_c.service import directed_evidence, generate_reports, with_context

ROOT = Path(__file__).resolve().parents[1]


class MinorOnlyCritic(ScriptedModel):
    def __call__(self, name, payload):
        if name == 'harbourline_critic_draft':
            self.calls.append((name, payload))
            return {'verdict': 'REVISE', 'findings': [{'category': 'OTHER', 'severity': 'MINOR', 'section_id': 'SEC-01',
                    'description': 'Wording could be tighter', 'required_fix': 'Optional', 'evidence_ids': []}]}
        return super().__call__(name, payload)


class AddsEvidenceOnRevision(ScriptedModel):
    def __call__(self, name, payload):
        if name == 'harbourline_revision':
            self.calls.append((name, payload))
            ids = list(payload['verified_evidence'])
            return {'sections': [{'section_id': s['section_id'], 'text': 'Revised: ' + s['text'], 'evidence_ids': ids[-1:]}
                                 for s in payload['report']['sections']],
                    'open_issues': payload['report']['open_issues'], 'assumptions': payload['report']['assumptions']}
        return super().__call__(name, payload)


class CReportFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.records = json.loads((ROOT / 'examples/test_source_registry.json').read_text())
        undated = {'document_id': 'UNDATED', 'version': '1', 'source_type': 'DATA_PACK', 'page': None, 'lines': ['Standing attendees']}
        future = {'document_id': 'LATER', 'version': '1', 'source_type': 'DATA_PACK', 'page': None, 'lines': ['May minutes']}
        table = {'document_id': 'TABLE', 'version': '1', 'source_type': 'DATA_PACK', 'page': None, 'available_from': '2027-04-01',
                 'lines': ['Commercial', 'Payment claim 3 (cumulative)', '985,000', 'Submitted']}
        self.lib = build_library(self.records + [table, undated, future], root / 'library.json',
                                 metadata={'TABLE': {'available_from': '2027-04-01'}, 'LATER': {'available_from': '2027-05-01'}})
        self.request = json.loads((ROOT / 'examples/request.json').read_text())
        self.request.update(source_snapshot_id=self.lib.snapshot, run_id='TEST-RUN')
        self.request['request']['reporting_period'] = {'start_date': '2027-03-01', 'end_date': '2027-03-31'}
        registry = root / 'registry.json'; registry.write_text(json.dumps(self.records + [table]))
        self.full, _ = run_project(self.request, self.lib.path, cutoff='2027-04-06', b_context={'source_registry_path': str(registry)},
                                   c_gateway=ModelGateway(responder=ScriptedModel()))
        self.ctx = {'planning': self.full['planning'], 'risk': self.full['risk'], 'as_of_date': '2027-04-06', 'b_source_evidence': []}

    def test_table_value_on_next_line_is_retrieved(self):
        quotes = [r['quote'] for r in directed_evidence(self.lib, '2027-04-06')]
        self.assertTrue(any('Payment claim 3' in q and '985,000' in q for q in quotes))

    def test_context_keeps_table_labels(self):
        doc = next(d for d in self.lib.documents if d['document_id'] == 'TABLE')
        value = self.lib.ref(doc, 3, 3)
        widened = with_context([value], self.lib, '2027-04-06')
        self.assertEqual(len(widened), 1)
        self.assertIn('Payment claim 3', widened[0]['quote']); self.assertIn('985,000', widened[0]['quote'])
        self.lib.verify(widened[0], '2027-04-06')

    def test_minor_findings_do_not_block(self):
        _, out = generate_reports(self.request, self.ctx, self.lib, ModelGateway(responder=MinorOnlyCritic()))
        self.assertTrue(all(r['status'] == 'READY_FOR_HUMAN_REVIEW' for r in out['reports']))
        self.assertTrue(all(v['findings'] for v in out['critic_reviews']))

    def test_revision_can_add_verified_citations(self):
        script = AddsEvidenceOnRevision(revise_first=True)
        _, out = generate_reports(self.request, self.ctx, self.lib, ModelGateway(responder=script))
        rev = [p for n, p in script.calls if n == 'harbourline_revision'][0]
        added = rev['verified_evidence'][list(rev['verified_evidence'])[-1]]
        for report in out['reports']:
            self.assertTrue(any(c['quote'] == added['quote'] for c in report['sections'][0]['citations']))


if __name__ == '__main__':
    unittest.main()
