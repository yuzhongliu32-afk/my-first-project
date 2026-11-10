"""Human checkpoint for a Jira write: show the pending preview, then the person types APPROVE or REJECT.

The approval is recorded in the audit database under the local Windows user, who must be listed in
HARBOURLINE_APPROVERS. Nothing is written to Jira here; the write happens afterwards with jira-apply.
"""
import argparse
from collections import Counter
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harbourline.governance import GovernanceStore, GateError  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', type=Path, default=ROOT / '.local/governance_mine.sqlite')
    p.add_argument('--env-file', type=Path, default=ROOT / '.env')
    a = p.parse_args()
    load_dotenv(a.env_file, interpolate=False, override=False)
    store = GovernanceStore(a.db)
    try:
        pending = [r['id'] for r in store.db.execute(
            "SELECT id FROM batches WHERE state='PENDING' AND kind='JIRA_WRITE' ORDER BY rowid")]
        if not pending:
            print('No Jira write is waiting for approval.')
            return
        b = store.batch(pending[-1])
        acts = b['payload']['actions']
        kinds = Counter()
        for x in acts:
            if x['action'] == 'LINK':
                kinds['links (' + x.get('link_type', 'Blocks') + ')'] += 1
            elif x.get('risk_id'):
                kinds['risks'] += 1
            elif x.get('milestone_id'):
                kinds['milestones'] += 1
            else:
                kinds['work packages (WBS)'] += 1
        print('=' * 70)
        print('Jira write waiting for YOUR approval')
        print('Target :', b['target'])
        print('Run    :', b['run_id'])
        print('Batch  :', b['id'])
        print('Hash   :', b['hash'])
        print('-' * 70)
        for k, n in kinds.items():
            print(f'  {n:3d}  {k}')
        print('-' * 70)
        for x in acts:
            if x['action'] != 'LINK':
                ident = x.get('wbs_id') or x.get('milestone_id') or x.get('risk_id')
                print(f"  {x['action']:<6} {ident:<7} {x['fields']['summary'][:60]}")
        print('-' * 70)
        print('Every item is labelled ai-generated. Nothing is deleted or closed.')
        print('Full preview: .local\\jira_preview_mine.json')
        print('=' * 70)
        answer = input('Type APPROVE to approve, REJECT to reject, or press Enter to cancel: ').strip().upper()
        if answer not in ('APPROVE', 'REJECT'):
            print('Cancelled. Nothing was recorded.')
            return
        decision = 'APPROVED' if answer == 'APPROVE' else 'REJECTED'
        approval = store.approve(b['id'], confirmed_hash=b['hash'], decision=decision)
        print(f"\n{decision} by {approval['approver_id']} at {approval['decided_at']}")
        print('Recorded in the audit log. Tell Claude so the write and read-back can run (approval valid 30 minutes).')
    except GateError as exc:
        print('Not approved:', exc)
    finally:
        store.db.close()
        store._lockfile.close()


if __name__ == '__main__':
    main()
