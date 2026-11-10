"""Member B workbench page and its live endpoints, with model doubles (no OpenAI calls)."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from modules.member_b.http_api import MemberBHTTPHandler
from tests.test_member_b_dynamic_ai import FakeLibrary, MockGateway, draft_plan, draft_risk
from tests.test_member_b_change_note import good_note

ROOT = Path(__file__).resolve().parents[1]


class ImpactGateway(MockGateway):
    """Adds the change-impact role to the B mock gateway."""
    def ask(self, name, shape, instructions, payload):
        if name == 'harbourline_b_change_impact':
            self.calls.append((name, payload))
            e = payload['event']
            return {'event_id': e['event_id'], 'change_type': e['change_type'],
                    'status': 'REVIEW_REQUIRED',
                    'stale_wbs_ids': [payload['planning']['wbs_items'][0]['wbs_id']],
                    'stale_milestone_ids': [], 'stale_risk_ids': [payload['risk']['risks'][0]['risk_id']],
                    'stale_reports': ['MONTHLY_GRANT'],
                    'human_actions': ['Confirm the ruling with the grant body'], 'approved': False}
        if name == 'harbourline_b_change_note':
            self.calls.append((name, payload))
            return good_note()
        return super().ask(name, shape, instructions, payload)


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        library = tmp / 'evidence_library.json'
        library.write_text('{}', encoding='utf-8')  # existence only; FakeLibrary is injected
        request = json.loads((ROOT / 'examples/member_b_request.json').read_text(encoding='utf-8'))
        (tmp / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        cls.gateways = []

        def gateway_factory(model):
            g = ImpactGateway()
            cls.gateways.append(g)
            return g

        cls.Handler = type('TestHandler', (MemberBHTTPHandler,), {
            'saved_output_path': tmp / '.local/member_b_live_output.json',
            'library_path': library, 'request_path': tmp / 'request.json',
            'gateway_factory': staticmethod(gateway_factory),
            'library_factory': staticmethod(lambda path: FakeLibrary()),
            'snapshot_dir': tmp / 'snapshot'})
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), cls.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)
        cls.tmp.cleanup()

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-placeholder-0000000000',
                                               'OPENAI_MODEL': 'model-x'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        c.request(method, path, body=None if body is None else json.dumps(body), headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        ctype = r.getheader('Content-Type', '')
        return r.status, (json.loads(raw) if 'json' in ctype else raw.decode('utf-8'))

    def test_root_serves_page_with_inputs(self):
        status, page = self.call('GET', '/')
        self.assertEqual(status, 200)
        for marker in ('id="api-key"', 'id="generate"', 'id="offline"', 'id="write-note"', '/v1/change-note',
                       '/v1/b-output', 'data-tab="whatif"'):
            self.assertIn(marker, page)

    def test_status_never_returns_key(self):
        status, body = self.call('GET', '/v1/status')
        self.assertEqual(status, 200)
        self.assertTrue(body['api_key_configured'])
        self.assertNotIn('sk-test-placeholder', json.dumps(body))
        self.assertTrue(any(e['event_id'] == 'CE-01' for e in body['example_change_events']))

    def test_configure_sets_memory_only(self):
        status, body = self.call('POST', '/v1/configure',
                                 {'api_key': 'sk-another-placeholder-123456', 'model': 'model-y'})
        self.assertEqual(status, 200)
        self.assertEqual(os.environ['OPENAI_MODEL'], 'model-y')
        self.assertNotIn('sk-another', json.dumps(body))
        status, _ = self.call('POST', '/v1/configure', {'api_key': 'short'})
        self.assertEqual(status, 400)

    def test_page_can_save_key_to_local_env(self):
        env = Path(self.tmp.name) / '.env'
        env.write_text('# local\nOPENAI_API_KEY=\nJIRA_EMAIL=\n', encoding='utf-8')
        old = (self.Handler.env_file_path, self.Handler._env_mtime)
        self.Handler.env_file_path = env
        try:
            status, body = self.call('POST', '/v1/configure', {
                'api_key': ' "sk-pasted-placeholder-1234567" ', 'model': 'model-z', 'save_to_env': True})
            self.assertEqual(status, 200, body)
            self.assertTrue(body['saved_to_env'])
            self.assertNotIn('sk-pasted', json.dumps(body))
            text = env.read_text(encoding='utf-8')
            self.assertIn('OPENAI_API_KEY=sk-pasted-placeholder-1234567', text)  # quotes/spaces stripped
            self.assertIn('OPENAI_MODEL=model-z', text)
            self.assertIn('JIRA_EMAIL=', text)
        finally:
            self.Handler.env_file_path, self.Handler._env_mtime = old

    def test_access_code_gates_ai_and_never_needs_key_on_page(self):
        with mock.patch.dict(os.environ, {'MEMBER_B_ACCESS_CODE': 'demo-pass-2026'}):
            status, s = self.call('GET', '/v1/status')
            self.assertTrue(s['access_code_required'])
            self.assertNotIn('demo-pass', json.dumps(s))
            status, body = self.call('POST', '/v1/generate-baseline', {})
            self.assertEqual(status, 403)
            status, _ = self.call('POST', '/v1/unlock', {}, headers={'X-Access-Code': 'wrong'})
            self.assertEqual(status, 403)
            status, _ = self.call('POST', '/v1/unlock', {}, headers={'X-Access-Code': 'demo-pass-2026'})
            self.assertEqual(status, 200)
            status, body = self.call('POST', '/v1/generate-baseline', {},
                                     headers={'X-Access-Code': 'demo-pass-2026'})
            self.assertEqual(status, 200, body)
            status, _ = self.call('POST', '/v1/generate-offline', {})  # free actions need no code
            self.assertEqual(status, 200)

    def test_ai_run_limit(self):
        self.Handler._runs_used = 0
        try:
            with mock.patch.dict(os.environ, {'MEMBER_B_AI_RUN_LIMIT': '1'}):
                self.assertEqual(self.call('POST', '/v1/generate-baseline', {})[0], 200)
                status, body = self.call('POST', '/v1/generate-baseline', {})
                self.assertEqual(status, 429)
                self.assertEqual(self.call('GET', '/v1/status')[1]['ai_runs_remaining'], 0)
        finally:
            self.Handler._runs_used = 0

    def test_presentation_snapshot_replays_without_api(self):
        self.assertEqual(self.call('POST', '/v1/generate-baseline', {})[0], 200)
        self.assertEqual(self.call('POST', '/v1/change-note', {'change_event': {
            'event_id': 'CE-02', 'change_type': 'OPERATOR_WITHDRAWAL',
            'description': 'Sole operator respondent withdrew.'}})[0], 200)
        status, meta = self.call('POST', '/v1/snapshot-save', {})
        self.assertEqual(status, 200, meta)
        self.assertIn('CE-02', meta['change_notes'])
        self.assertNotIn('sk-', json.dumps(meta))
        calls_before = len(self.gateways)
        del os.environ['OPENAI_API_KEY']  # replay must not need the key
        status, got = self.call('GET', '/v1/b-output?source=snapshot')
        self.assertEqual(status, 200)
        self.assertIn('no API call', got['mode_note'])
        self.assertEqual(got['output']['run_id'], meta['run_id'])
        self.assertIn('CE-02', got['change_notes'])
        status, notes = self.call('GET', '/v1/change-notes?source=snapshot')
        self.assertEqual(notes['notes'][0]['event']['event_id'], 'CE-02')
        self.assertEqual(len(self.gateways), calls_before)  # no model gateway was created
        snap_files = {p.name for p in Path(self.Handler.snapshot_dir).rglob('*.json')}
        self.assertEqual(snap_files, {'b_output.json', 'trace.json', 'meta.json', 'CE-02.json'})

    def test_snapshot_needs_a_real_ai_run(self):
        live = Path(self.Handler.saved_output_path)
        if live.exists():
            live.unlink()
        status, body = self.call('POST', '/v1/snapshot-save', {})
        self.assertEqual(status, 422)

    def test_cross_origin_post_is_refused(self):
        status, body = self.call('POST', '/v1/configure', {'model': 'evil'},
                                 headers={'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)
        self.assertEqual(os.environ['OPENAI_MODEL'], 'model-x')

    def test_missing_key_is_reported(self):
        del os.environ['OPENAI_API_KEY']
        status, body = self.call('POST', '/v1/generate-baseline', {})
        self.assertEqual(status, 503)
        self.assertEqual(body['missing'], ['OPENAI_API_KEY'])

    def test_generate_then_ai_change_impact(self):
        status, body = self.call('POST', '/v1/generate-baseline', {})
        self.assertEqual(status, 200, body)
        self.assertTrue(Path(self.Handler.saved_output_path).is_file())
        self.assertGreater(body['wbs_items'], 0)
        status, out = self.call('POST', '/v1/change-impact-live', {'change_event': {
            'event_id': 'CE-01', 'change_type': 'GRANT_ELIGIBILITY_RULING',
            'description': 'Asbestos removal ruled not grant-eligible.', 'hypothetical': False}})
        self.assertEqual(status, 200, out)
        rid = out['ai']['stale_risk_ids'][0]
        self.assertFalse(out['approved'])
        self.assertIn(rid, out['labels']['risks'])

    def test_invented_ids_from_model_are_rejected(self):
        self.call('POST', '/v1/generate-baseline', {})
        original = ImpactGateway.ask

        def invent(gw, name, shape, instructions, payload):
            out = original(gw, name, shape, instructions, payload)
            if name == 'harbourline_b_change_impact':
                out['stale_wbs_ids'] = ['9.9.9']
            return out
        with mock.patch.object(ImpactGateway, 'ask', invent):
            status, body = self.call('POST', '/v1/change-impact-live', {'change_event': {
                'event_id': 'T', 'change_type': 'OTHER', 'description': 'x'}})
        self.assertEqual(status, 400)
        self.assertIn('invented', body['message'])
        self.assertEqual(self.gateways[-1].calls[-1][0], 'harbourline_b_change_impact')

    def test_live_output_with_whatif_trace_and_change_note(self):
        status, body = self.call('POST', '/v1/generate-baseline', {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body['scenarios'], 1)
        status, got = self.call('GET', '/v1/b-output?source=live')
        self.assertEqual(status, 200)
        detail = got['trace']['whatif'][0]
        self.assertEqual(detail['cost_sgd_k']['draws'], 10_000)
        self.assertIn('source_refs', detail['elements'][0])
        status, note = self.call('POST', '/v1/change-note', {'change_event': {
            'event_id': 'CE-01', 'change_type': 'GRANT_ELIGIBILITY_RULING',
            'description': 'Asbestos removal ruled not grant-eligible.'}})
        self.assertEqual(status, 200, note)
        self.assertTrue(note['result']['computed_in_code'])
        self.assertFalse(note['approved'])
        self.assertTrue(Path(self.Handler.saved_output_path).with_name('member_b_change_note_CE-01.json').is_file())

    def test_user_whatif_recompute_in_code(self):
        del os.environ['OPENAI_API_KEY']  # no AI involved
        status, out = self.call('POST', '/v1/whatif-recompute', {'elements': [
            {'label': 'A', 'kind': 'COST', 'optimistic': 25, 'most_likely': 40, 'pessimistic': 60},
            {'label': 'B', 'kind': 'COST', 'optimistic': 8, 'most_likely': 12, 'pessimistic': 20},
            {'label': 'C', 'kind': 'COST', 'optimistic': 3, 'most_likely': 5, 'pessimistic': 8},
            {'label': 'D', 'kind': 'SCHEDULE', 'optimistic': 4, 'most_likely': 5, 'pessimistic': 6,
             'on_critical_path': True}]})
        self.assertEqual(status, 200, out)
        self.assertEqual(out['status'], 'USER_ASSUMPTION')
        self.assertAlmostEqual(out['cost_sgd_k']['p80'], 64, delta=1.5)
        self.assertEqual(out['schedule_weeks']['draws'], 10_000)
        status, _ = self.call('POST', '/v1/whatif-recompute', {'elements': [
            {'kind': 'COST', 'optimistic': 9, 'most_likely': 5, 'pessimistic': 8}]})
        self.assertEqual(status, 400)

    def test_offline_preview_needs_no_key(self):
        del os.environ['OPENAI_API_KEY']
        status, body = self.call('POST', '/v1/generate-offline', {})
        self.assertEqual(status, 200, body)
        self.assertEqual(body['source'], 'rules')
        status, got = self.call('GET', '/v1/b-output?source=rules')
        self.assertEqual(status, 200)
        self.assertIn('NOT the AI agent', got['mode_note'])

    def test_change_impact_live_requires_description(self):
        status, body = self.call('POST', '/v1/change-impact-live',
                                 {'change_event': {'event_id': 'X', 'change_type': 'OTHER'}})
        self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
