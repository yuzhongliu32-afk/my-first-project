import unittest
from harbourline.site_server import apply_user_whatif, validate_input

BASE = {'report_type': 'MONTHLY_GRANT', 'start_date': '2027-03-01', 'end_date': '2027-03-31', 'as_of_date': '2027-04-06'}


def b(*scenarios):
    return {'risk': {'scenarios': [dict(s) for s in scenarios]}}


class SiteWhatIfInputs(unittest.TestCase):
    def test_inputs_are_validated_and_kept(self):
        p = validate_input({**BASE, 'delay_weeks': 8, 'extra_cost_sgd': 450000})
        self.assertEqual((p['delay_weeks'], p['extra_cost_sgd']), (8, 450000))
        self.assertEqual(validate_input(BASE)['delay_weeks'], 6)
        for bad in ({'delay_weeks': 60}, {'extra_cost_sgd': -1}, {'delay_weeks': '6'}):
            with self.assertRaises(ValueError):
                validate_input({**BASE, **bad})

    def test_asbestos_scenario_takes_user_numbers(self):
        out = b({'scenario_id': 'WF02', 'description': 'Lift works delayed', 'assumptions': []},
                {'scenario_id': 'WF01', 'description': 'Asbestos removal proceeds', 'assumptions': [],
                 'schedule_impact_days': 37, 'cost_impact_sgd': 518070})
        self.assertEqual(apply_user_whatif(out, 8, 450000), 'WF01')
        s = out['risk']['scenarios'][1]
        self.assertEqual((s['schedule_impact_days'], s['cost_impact_sgd']), (56, 450000))
        self.assertIn('8 weeks × 7 = 56', s['calculation_basis'])
        self.assertTrue(any('37 days' in a and 'S$518,070' in a for a in s['assumptions']))
        self.assertNotIn('schedule_impact_days', out['risk']['scenarios'][0])

    def test_rules_template_uses_sc01(self):
        out = b({'scenario_id': 'SC02', 'description': 'asbestos too', 'assumptions': []},
                {'scenario_id': 'SC01', 'description': 'x', 'assumptions': []})
        self.assertEqual(apply_user_whatif(out, 4, 350000), 'SC01')


if __name__ == '__main__':
    unittest.main()


class TeamAccessCodes(unittest.TestCase):
    def setUp(self):
        import os
        self.saved = {k: os.environ.get(k) for k in ('MEMBER_B_ACCESS_CODE', 'MEMBER_C_ACCESS_CODE', 'OPENAI_API_KEY', 'OPENAI_API_KEY_C')}
        os.environ.update(MEMBER_B_ACCESS_CODE='b-code', MEMBER_C_ACCESS_CODE='c-code-long', OPENAI_API_KEY='kb')
        os.environ.pop('OPENAI_API_KEY_C', None)

    def tearDown(self):
        import os
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def holder(self, typed):
        from harbourline import site_server
        handler = next(v for v in vars(site_server).values() if isinstance(v, type) and hasattr(v, 'access_holder'))
        fake = type('H', (), {'headers': {'X-Demo-Access': typed}})()
        return handler.access_holder(fake)

    def test_either_members_code_opens_the_single_box(self):
        self.assertEqual(self.holder('b-code'), 'B')
        self.assertEqual(self.holder('c-code-long'), 'C')
        self.assertIsNone(self.holder('wrong'))
        self.assertIsNone(self.holder(''))

    def test_c_key_falls_back_then_separates(self):
        import os
        from harbourline.llm import ModelGateway
        from harbourline.site_server import billing
        self.assertEqual(ModelGateway(key_env='OPENAI_API_KEY_C').key_env, 'OPENAI_API_KEY')
        self.assertEqual(billing()['C'], 'OPENAI_API_KEY')
        os.environ['OPENAI_API_KEY_C'] = 'kc'
        self.assertEqual(ModelGateway(key_env='OPENAI_API_KEY_C').key_env, 'OPENAI_API_KEY_C')
        self.assertEqual(billing(), {'B': 'OPENAI_API_KEY', 'C': 'OPENAI_API_KEY_C'})


class CloudDeployment(unittest.TestCase):
    def test_public_host_is_allowed_only_when_configured(self):
        import os
        from harbourline.site_server import allowed_hosts
        saved = os.environ.pop('RENDER_EXTERNAL_HOSTNAME', None)
        try:
            self.assertNotIn('demo.onrender.com', allowed_hosts())
            os.environ['RENDER_EXTERNAL_HOSTNAME'] = 'demo.onrender.com'
            self.assertIn('demo.onrender.com', allowed_hosts())
            self.assertIn('127.0.0.1', allowed_hosts())
        finally:
            os.environ.pop('RENDER_EXTERNAL_HOSTNAME', None)
            if saved: os.environ['RENDER_EXTERNAL_HOSTNAME'] = saved

    def test_published_records_hold_no_credentials(self):
        import re
        from harbourline.site_server import RECORDED
        for f in RECORDED.glob('*.json'):
            text = f.read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'sk-[A-Za-z0-9_-]{20,}|ATATT[A-Za-z0-9_=-]{20,}|@gmail\.com', text), f.name)


class PackBundle(unittest.TestCase):
    def test_bundle_round_trip_gives_the_same_sources(self):
        import tempfile
        from pathlib import Path
        from modules.member_b.data_pack import load_pack_sources, resolve_pack_dir
        root = Path(__file__).resolve().parents[1]
        folder = resolve_pack_dir(root, {})
        if not folder.is_dir():
            self.skipTest('Data Pack folder not present (course material is not in the repository)')
        import subprocess, sys
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'pack.json'
            subprocess.run([sys.executable, str(root / 'scripts/export_pack_bundle.py'), '--pack', str(folder), '--out', str(out)],
                           check=True, capture_output=True)
            a, b = load_pack_sources(folder), load_pack_sources(out)
            self.assertEqual(a.keys(), b.keys())
            for k in a:
                self.assertEqual((a[k]['lines'], a[k]['sha256'], a[k]['page']), (b[k]['lines'], b[k]['sha256'], b[k]['page']))


class TransientProviderErrors(unittest.TestCase):
    def _gateway(self, failures):
        import os
        from unittest import mock
        from harbourline.llm import ModelGateway
        os.environ.setdefault('OPENAI_MODEL', 'test-model'); os.environ.setdefault('OPENAI_API_KEY', 'test-key')
        g = ModelGateway()

        class Resp:
            status = 'completed'; output_text = '{"ok": true}'
            usage = type('U', (), {'input_tokens': 1, 'output_tokens': 1})()
        calls = {'n': 0}

        def create(**kw):
            calls['n'] += 1
            if calls['n'] <= len(failures):
                raise failures[calls['n'] - 1]
            return Resp()
        g._client = type('C', (), {'responses': type('R', (), {'create': staticmethod(create)})()})()
        return g, calls, mock

    def test_a_520_is_retried_then_succeeds(self):
        class InternalServerError(Exception):
            status_code = 520
        g, calls, mock = self._gateway([InternalServerError('520')])
        with mock.patch('harbourline.llm.sleep'):
            out = g.ask('t', {'type': 'object'}, 'x', {})
        self.assertEqual((out, calls['n']), ({'ok': True}, 2))

    def test_a_400_is_not_retried(self):
        class BadRequestError(Exception):
            status_code = 400
        g, calls, mock = self._gateway([BadRequestError('400')])
        with mock.patch('harbourline.llm.sleep'), self.assertRaises(BadRequestError):
            g.ask('t', {'type': 'object'}, 'x', {})
        self.assertEqual(calls['n'], 1)
