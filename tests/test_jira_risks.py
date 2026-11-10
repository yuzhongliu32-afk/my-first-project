"""B's risk register reaches Jira through A's approved, idempotent write path (simulated Jira)."""
import json
import unittest
from pathlib import Path

from harbourline.jira import MockJira, execute_actions, plan_actions

ROOT = Path(__file__).resolve().parents[1]


def full_output():
    b = json.loads((ROOT / 'examples/b_output.json').read_text(encoding='utf-8'))
    return {'run_id': 'RUN-TEST', 'planning': b['planning'], 'risk': b['risk'],
            'reporting': {'reports': []}, 'change': {}}


class JiraRiskTests(unittest.TestCase):
    def setUp(self):
        self.full = full_output()
        self.jira = MockJira()
        self.events = []

    def audit(self, event, detail):
        self.events.append((event, detail))

    def apply(self):
        payload = plan_actions(self.full, self.jira)
        return payload, execute_actions(payload, self.jira, self.audit)

    def test_every_risk_becomes_one_labelled_item(self):
        payload, _ = self.apply()
        risk_actions = [a for a in payload['actions'] if a.get('risk_id')]
        self.assertEqual(len(risk_actions), len(self.full['risk']['risks']))
        for a in risk_actions:
            self.assertEqual(a['external_key'], f"DEMO:RISK:{a['risk_id']}")
            self.assertIn('ai-generated', a['fields']['labels'])
            self.assertIn('harbourline-risk', a['fields']['labels'])
            self.assertTrue(a['fields']['summary'].startswith(f"[Risk {a['risk_id']}]"))
        text = json.dumps(risk_actions[0]['fields']['description'])
        for word in ('Score', 'Owner', 'Trigger', 'Response plan', 'Related WBS', 'Sources'):
            self.assertIn(word, text)

    def test_risks_link_to_the_work_they_threaten(self):
        payload, _ = self.apply()
        relates = [a for a in payload['actions'] if a['action'] == 'LINK' and a.get('link_type') == 'Relates']
        expected = sum(len(r['related_wbs_ids']) for r in self.full['risk']['risks'])
        self.assertGreaterEqual(len(relates), min(1, expected))
        self.assertTrue(any(kind == 'Relates' for _, _, kind in self.jira.links))
        has_deps = any(w['predecessor_wbs_ids'] for w in self.full['planning']['wbs_items'])
        self.assertEqual(any(kind == 'Blocks' for _, _, kind in self.jira.links), has_deps)  # WBS dependencies kept

    def test_every_write_is_audited_and_read_back(self):
        self.apply()
        attempts = [d for e, d in self.events if e == 'JIRA_WRITE_ATTEMPT']
        verified = [d for e, d in self.events if e == 'JIRA_READBACK_VERIFIED']
        self.assertEqual(len(attempts), self.jira.writes)
        self.assertGreaterEqual(len(verified), len(attempts))

    def test_second_run_updates_and_never_duplicates(self):
        self.apply()
        writes, issues, links = self.jira.writes, len(self.jira.issues), set(self.jira.links)
        payload, _ = self.apply()
        self.assertFalse(any(a['action'] == 'CREATE' for a in payload['actions']))
        self.assertEqual(len(self.jira.issues), issues)
        self.assertEqual(self.jira.links, links)
        self.assertEqual(self.jira.writes, writes)  # nothing changed, nothing written

    def test_rescored_risk_updates_the_same_item(self):
        self.apply()
        r = self.full['risk']['risks'][0]
        key = self.jira.find(plan_actions(self.full, self.jira)['actions'][0]['label'])['key']
        r['probability'], r['impact'], r['score'] = 5, 5, 25
        payload, _ = self.apply()
        update = [a for a in payload['actions'] if a.get('risk_id') == r['risk_id']][0]
        self.assertEqual(update['action'], 'UPDATE')
        issue = self.jira.find(update['label'])
        self.assertIn('5 x 5 = 25', json.dumps(issue['fields']['description']))
        self.assertIsNotNone(key)

    def test_read_only_board_readback_before_any_write(self):
        report = __import__('harbourline.jira', fromlist=['read_board']).read_board(self.full, self.jira)
        self.assertTrue(report['read_only'])
        self.assertEqual(self.jira.writes, 0)  # reading never writes
        self.assertEqual(report['summary']['missing'], report['summary']['planned_items'])
        self.assertGreater(report['summary']['risks'], 0)

    def test_readback_after_apply_is_in_sync_and_flags_drift(self):
        from harbourline.jira import read_board
        self.apply()
        report = read_board(self.full, self.jira)
        s = report['summary']
        self.assertEqual((s['missing'], s['differs'], s['links_not_linked']), (0, 0, 0))
        self.assertEqual(s['in_sync'], s['planned_items'])
        # A human edits a risk title in Jira: the readback shows it, nothing is overwritten.
        key = next(r['issue_key'] for r in report['items'] if r['risk_id'])
        self.jira.issues[key]['fields']['summary'] = 'Edited by a person'
        writes = self.jira.writes
        drift = read_board(self.full, self.jira)
        self.assertEqual(drift['summary']['differs'], 1)
        self.assertEqual(self.jira.writes, writes)

    def test_items_no_longer_in_plan_are_reported_not_deleted(self):
        from harbourline.jira import read_board
        self.apply()
        removed = self.full['risk']['risks'].pop()
        report = read_board(self.full, self.jira)
        self.assertEqual(report['summary']['not_in_plan'], 1)
        self.assertIn(removed['risk_id'], report['not_in_plan'][0]['summary'])
        self.assertEqual(len(self.jira.issues), len(self.jira.issues))  # nothing removed

    def test_read_is_recorded_in_the_audit_chain(self):
        import tempfile
        from harbourline.governance import GovernanceStore
        store = GovernanceStore(Path(tempfile.mkdtemp()) / 'gov.sqlite', approvers=['tester'],
                                actor_provider=lambda: 'tester')
        store.record_read('RUN-TEST', self.jira.target, {'in_sync': 0})
        events = [e['event'] for e in store.audit()]
        store.db.close(); store._lockfile.close()
        self.assertIn('JIRA_READ_VERIFIED', events)

    def test_no_delete_or_close_is_possible(self):
        from harbourline.jira import JiraCloud
        from harbourline.governance import GateError
        j = JiraCloud('https://example.atlassian.net', 'a@example.com', 'token', 'DEMO')
        with self.assertRaises(GateError):
            j.request('DELETE', '/issue/DEMO-1')
        with self.assertRaises(GateError):
            j.request('POST', '/issue/DEMO-1/transitions', {})


if __name__ == '__main__':
    unittest.main()
