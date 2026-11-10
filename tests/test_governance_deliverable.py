"""Deliverable 4: fairness check and incident log are produced, audited and exported."""
import tempfile
import unittest
from pathlib import Path

from harbourline.fairness import fairness_check
from harbourline.governance import GateError, GovernanceStore

ROWS = ['response_id,date,time,channel,age_band,block,language,comment,rating_1to5']
for i in range(1, 31):
    ROWS.append(f'RC{i:03d},2027-02-01,10:00,{"online" if i % 3 else "paper"},'
                f'{"65+" if i % 5 == 0 else "25-34"},401,{"zh" if i == 7 else "en"},"comment {i}",{1 + i % 5}')
ROWS.append('RC001,2027-02-02,11:00,online,25-34,401,en,"duplicate id",3')


class FakeLibrary:
    snapshot = 'SRC-TEST'

    def __init__(self, with_consultation=True):
        self.documents = [{'document_id': 'PACK-CONSULTATION', 'version': 'v1', 'source_type': 'DATA_PACK',
                           'lines': ROWS}] if with_consultation else []

    def ref(self, doc, start, end):
        return {'document_id': doc['document_id'], 'document_version': doc['version'], 'source_type': 'DATA_PACK',
                'page': None, 'line_start': start, 'line_end': end,
                'chunk_id': f"{doc['document_id']}:{start}-{end}", 'quote': doc['lines'][start - 1]}


class FairnessTests(unittest.TestCase):
    def test_coverage_duplicates_and_small_groups(self):
        c = fairness_check(FakeLibrary())
        text = ' '.join(c['findings'])
        self.assertIn('Observed responses: 31', text)
        self.assertIn('Duplicate response IDs: 1 (RC001)', text)
        self.assertIn('zh not compared (n=1 < 10)', text)       # no mean for tiny groups
        self.assertIn('Low-coverage groups', text)
        self.assertEqual(c['groups_considered'], ['age_band', 'language', 'channel', 'block'])
        self.assertTrue(c['mitigation_actions'])
        self.assertIn('No demographic inference', c['method'])

    def test_absent_consultation_gives_no_check(self):
        self.assertIsNone(fairness_check(FakeLibrary(with_consultation=False)))


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.store = GovernanceStore(Path(tempfile.mkdtemp()) / 'gov.sqlite', approvers=['tester'],
                                     actor_provider=lambda: 'tester')

    def tearDown(self):
        self.store.db.close(); self.store._lockfile.close()

    def test_blocked_module_and_stopped_report_become_incidents(self):
        full = {'errors': [{'code': 'C_MODULE_BLOCKED', 'message': 'C blocked', 'recoverable': True}],
                'reporting': {'reports': [{'report_type': 'MONTHLY_GRANT', 'status': 'BLOCKED'}]}}
        found = self.store.incidents('RUN-1', full)
        ids = {i['incident_id'] for i in found}
        self.assertIn('INC-RUN-1-C_MODULE_BLOCKED', ids)
        self.assertIn('INC-RUN-1-MONTHLY_GRANT-STOPPED', ids)
        self.assertTrue(all(i['status'] == 'OPEN' and i['corrective_action'] is None for i in found))

    def test_human_resolution_is_audited(self):
        full = {'errors': [{'code': 'C_MODULE_BLOCKED', 'message': 'x', 'recoverable': True}], 'reporting': {'reports': []}}
        self.store.resolve_incident('INC-RUN-1-C_MODULE_BLOCKED', 'Added verified source dates; re-ran.')
        inc = self.store.incidents('RUN-1', full)[0]
        self.assertEqual(inc['status'], 'RESOLVED')
        self.assertIn('verified source dates', inc['corrective_action'])
        self.assertIn('INCIDENT_RESOLVED', [e['event'] for e in self.store.audit()])
        with self.assertRaises(GateError):
            self.store.resolve_incident('INC-X', '  ')


if __name__ == '__main__':
    unittest.main()
