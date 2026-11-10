"""Local CLI for integrated runs, exact human checkpoints, Jira and change invalidation."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4
from .contracts import validate
from .sources import EvidenceLibrary,digest
from .pipeline import run_project
from .governance import GovernanceStore,GateError
from .jira import JiraCloud,MockJira,plan_actions,execute_actions,read_board
from .llm import ModelGateway
from .simulation import ScriptedModel


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def client(store):
    jira=JiraCloud.from_env()
    # Durable external-key mapping complements Jira's eventually consistent search.
    for event in store.audit():
        d=event['detail']
        if event['event']=='JIRA_WRITE_RETURNED' and d.get('target')==jira.target and d.get('label') and d.get('issue_key'):
            jira.known[d['label']]=d['issue_key']
    return jira


def main():
    p=argparse.ArgumentParser(description='Harbourline local integration controls; no anonymous approval endpoint')
    p.add_argument('--db',type=Path,default=Path('.local/governance.sqlite'))
    sub=p.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--library',type=Path,default=Path('data/evidence_library.json'))
    run.add_argument('--start',required=True);run.add_argument('--end',required=True);run.add_argument('--cutoff',required=True)
    run.add_argument('--weekly-start');run.add_argument('--weekly-end');run.add_argument('--monthly-start');run.add_argument('--monthly-end')
    run.add_argument('--report-type',choices=['WEEKLY_COMMITTEE','MONTHLY_GRANT','both'],default='both')
    run.add_argument('--plan-mode',choices=['rules','live'],default='rules');run.add_argument('--sources',type=Path,default=Path('data/brief_source_registry.json'))
    run.add_argument('--semantic-index',type=Path);run.add_argument('--pack-dir',type=Path);run.add_argument('--scripted-test',action='store_true')
    run.add_argument('--out',type=Path,default=Path('.local/integrated_run'))
    preview=sub.add_parser('jira-preview');preview.add_argument('run_id');preview.add_argument('--out',type=Path,default=Path('.local/jira_preview.json'))
    board=sub.add_parser('jira-read');board.add_argument('run_id');board.add_argument('--out',type=Path,default=Path('.local/jira_board.json'))
    approve=sub.add_parser('approve');approve.add_argument('batch_id');approve.add_argument('--confirm-hash',required=True)
    approve.add_argument('--decision',choices=['APPROVED','REJECTED'],default='APPROVED')
    apply=sub.add_parser('jira-apply');apply.add_argument('batch_id')
    change=sub.add_parser('change');change.add_argument('run_id');change.add_argument('event',type=Path)
    audit=sub.add_parser('audit');audit.add_argument('--out',type=Path,default=Path('.local/audit_export.json'))
    show=sub.add_parser('show');show.add_argument('run_id');show.add_argument('--out',type=Path,default=Path('.local/current_state.json'))
    release=sub.add_parser('report-preview');release.add_argument('run_id');release.add_argument('--directory',type=Path,required=True)
    export=sub.add_parser('report-export');export.add_argument('batch_id')
    a=p.parse_args();store=GovernanceStore(a.db)
    try:
        if a.command=='run':
            lib=EvidenceLibrary(a.library);base=json.loads((Path(__file__).resolve().parents[1]/'examples/request.json').read_text(encoding='utf-8'))
            base.update(message_id='REQUEST-'+str(uuid4()),run_id='RUN-'+str(uuid4()),source_snapshot_id=lib.snapshot)
            base['request'].update(instructions='Prepare source-grounded proposals and human-review report drafts.',
              reporting_period={'start_date':a.start,'end_date':a.end},requested_report_type=None if a.report_type=='both' else a.report_type)
            ctx={'source_registry_path':str(a.sources.resolve())}
            if a.pack_dir:ctx['data_pack_directory']=str(a.pack_dir.resolve())
            cg=ModelGateway(responder=ScriptedModel(revise_first=True)) if a.scripted_test else None
            bg=ModelGateway(responder=ScriptedModel()) if a.scripted_test else None
            periods={}
            for kind,first,last in [('WEEKLY_COMMITTEE',a.weekly_start,a.weekly_end),('MONTHLY_GRANT',a.monthly_start,a.monthly_end)]:
                if bool(first)!=bool(last):raise ValueError('Supply both start and end for an audience period')
                if first:periods[kind]={'start_date':first,'end_date':last}
            full,trace=run_project(base,a.library,cutoff=a.cutoff,plan_mode=a.plan_mode,b_context=ctx,c_gateway=cg,b_gateway=bg,semantic_index=a.semantic_index,reporting_periods=periods)
            store.save(full,mode='SCRIPTED_TEST' if a.scripted_test else 'LIVE_MODEL_REQUESTED');write(a.out/'full_output.json',full);write(a.out/'handoff_trace.json',trace)
            write(a.out/'run_metadata.json',{'mode':'SCRIPTED_TEST' if a.scripted_test else 'LIVE_MODEL_REQUESTED',
                 'planning_mode':a.plan_mode,'source_snapshot_id':lib.snapshot,'status':full['status'],
                 'note':'Scripted test is not live AI; actual stage status and metrics are in the output.'})
            print(json.dumps({'run_id':full['run_id'],'status':full['status'],'report_count':len(full['reporting']['reports']),'output':str(a.out)}))
        elif a.command=='jira-preview':
            row,full=store.artifact(a.run_id)
            if row['stale']:raise GateError('Run is stale')
            if row['mode']!='LIVE_MODEL_REQUESTED':raise GateError('Scripted/unverified runs cannot be sent to real Jira')
            jira=client(store);payload=plan_actions(full,jira)
            batch=store.propose(a.run_id,'JIRA_WRITE',jira.target,payload);write(a.out,batch)
            print(json.dumps({'batch_id':batch['id'],'review_hash':batch['hash'],'preview':str(a.out)}))
        elif a.command=='jira-read':
            # Read-only: compares the plan (WBS, milestones, risks, links) with the Jira board.
            row,full=store.artifact(a.run_id)
            jira=client(store);report=read_board(full,jira)
            store.record_read(a.run_id,jira.target,report['summary']);write(a.out,report)
            print(json.dumps({'read_only':True,**report['summary'],'output':str(a.out)}))
        elif a.command=='approve':
            print(json.dumps(store.approve(a.batch_id,confirmed_hash=a.confirm_hash,decision=a.decision)))
        elif a.command=='jira-apply':
            jira=client(store);result=store.execute(a.batch_id,jira.target,lambda payload,audit:execute_actions(payload,jira,audit))
            print(json.dumps({'batch_id':result['id'],'state':result['state'],'mode':'LIVE_JIRA'}))
        elif a.command=='change':print(json.dumps(store.record_change(a.run_id,json.loads(a.event.read_text(encoding='utf-8')))))
        elif a.command=='audit':write(a.out,store.audit());print(str(a.out))
        elif a.command=='show':
            row,full=store.artifact(a.run_id);write(a.out,{'run_mode':row['mode'],'stale':bool(row['stale']),'version':row['version'],'state':store.export(a.run_id)});print(str(a.out))
        elif a.command=='report-preview':
            row,full=store.artifact(a.run_id)
            reports=full['reporting']['reports']
            if row['mode']!='LIVE_MODEL_REQUESTED':raise GateError('Scripted/unverified reports cannot be released')
            if row['stale'] or not reports or any(r['is_stale'] or r['status']!='READY_FOR_HUMAN_REVIEW' for r in reports):raise GateError('Fresh reports and latest Critic PASS required')
            # Local export only. No emails or grant submissions are sent.
            destination=str(a.directory.resolve())
            payload={'reports':reports,'directory':destination}
            b=store.propose(a.run_id,'REPORT_RELEASE',destination,payload)
            print(json.dumps({'batch_id':b['id'],'review_hash':b['hash'],'destination':destination}))
        elif a.command=='report-export':
            b=store.batch(a.batch_id)
            if b['kind']!='REPORT_RELEASE':raise GateError('Expected report export proposal')
            def export(payload,audit):
                root=Path(payload['directory']);root.mkdir(parents=True,exist_ok=True)
                for i,r in enumerate(payload['reports']):
                    file=root/f'{i+1}_{r["report_type"]}.json';audit('REPORT_EXPORT_ATTEMPT',{'path':str(file),'hash':digest(r)})
                    write(file,r)
                    if digest(json.loads(file.read_text(encoding='utf-8')))!=digest(r):raise GateError('Report export readback mismatch')
                return {'local_files_verified':len(payload['reports']),'external_submission':False}
            print(json.dumps({'state':store.execute(a.batch_id,b['target'],export)['state']}))
    except (ValueError,KeyError,FileNotFoundError) as exc:p.exit(1,str(exc)+'\n')


if __name__=='__main__':main()
