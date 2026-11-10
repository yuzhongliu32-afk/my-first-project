"""Publish one verified local run with the page, so a cloud copy (which has no access to the local
audit database or to Jira) shows the same result, governance record and Jira read-back.

Writes web/site/data/recorded/<run id>.json and web/site/data/recorded/jira_readback.json.
Contains no credentials: only the run output, approvals, audit entries and read-back counts.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harbourline.governance import GovernanceStore  # noqa: E402

OUT = ROOT / 'web/site/data/recorded'
import re
SECRET_NAMES = ('OPENAI_API_KEY', 'OPENAI_API_KEY_C', 'JIRA_API_TOKEN', 'JIRA_EMAIL',
                'MEMBER_B_ACCESS_CODE', 'MEMBER_C_ACCESS_CODE')
SECRET_SHAPES = re.compile(r'sk-[A-Za-z0-9_-]{20,}|ATATT[A-Za-z0-9_=-]{20,}')


def secret_values():
    """The actual secret values in .env; the published files must not contain any of them."""
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / '.env', interpolate=False)
    return [v for k, v in values.items() if k in SECRET_NAMES and v]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('record', type=Path, help='.local/site_runs/api-....json')
    p.add_argument('--db', type=Path, default=ROOT / '.local/governance_mine.sqlite')
    a = p.parse_args()
    record = json.loads(a.record.read_text(encoding='utf-8'))
    run_id = record['full']['run_id']
    store = GovernanceStore(a.db)
    try:
        record['full']['governance'] = store.export(run_id)['governance']
        reads = [e for e in store.audit() if e['event'] == 'JIRA_READ_VERIFIED' and e['detail'].get('run_id') == run_id]
    finally:
        store.db.close(); store._lockfile.close()
    if not reads:
        raise SystemExit('No verified Jira read-back for this run; run jira-read first.')
    last = reads[-1]
    base, key = last['detail']['target'].split('#', 1)
    s = last['detail']['summary']
    record['notice'] = ('Recorded verified run, published with the page. Planning, risks and report were generated live '
                        'by OpenAI; the Jira write was approved by a person and read back. Replaying it makes no API call.')
    jira = {'url': f'{base}/jira/software/projects/{key}/boards', 'mode': 'recorded', 'run_id': run_id,
            'observed_count': s.get('observed_count'), 'readback_at': last['time'], 'readback_verified': True,
            'new_writes_on_replay': s.get('new_writes_on_replay'), 'duplicate_external_keys': s.get('duplicate_external_keys'),
            'summary': s,
            'notice': 'Recorded read-back from the team Jira sandbox (approved write, then read-only verification).'}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, value in ((record['id'] + '.json', record), ('jira_readback.json', jira)):
        text = json.dumps(value, ensure_ascii=False, indent=1)
        if any(v in text for v in secret_values()) or SECRET_SHAPES.search(text):
            raise SystemExit(f'Refusing to publish {name}: it contains a secret value')
        (OUT / name).write_text(text, encoding='utf-8')
        print('wrote', (OUT / name).relative_to(ROOT), f'{len(text) // 1024} KB')


if __name__ == '__main__':
    main()
