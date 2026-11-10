"""Local-operator governance store. Never expose this CLI store as an anonymous API."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import getpass
import json
import os
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4
from .sources import digest
from .contracts import validate


def now():return datetime.now(timezone.utc).isoformat()


class GateError(ValueError):pass


class GovernanceStore:
    def __init__(self,path,*,approvers=None,actor_provider=getpass.getuser):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.actor_provider=actor_provider
        self._mutex=threading.RLock();self._depth=0
        self._lockfile=open(str(self.path)+'.lock','a+b')
        self.approvers=set(approvers if approvers is not None else filter(None,os.getenv('HARBOURLINE_APPROVERS','').split(',')))
        self.db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        os.chmod(self.path,0o600)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS artifacts(run_id TEXT PRIMARY KEY,snapshot TEXT NOT NULL,version TEXT NOT NULL,data TEXT NOT NULL,stale INTEGER NOT NULL DEFAULT 0,mode TEXT NOT NULL DEFAULT 'UNVERIFIED');
        CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,snapshot TEXT NOT NULL,artifact_version TEXT NOT NULL,kind TEXT NOT NULL,target TEXT NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,state TEXT NOT NULL,approval TEXT,expires TEXT);
        CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,previous_hash TEXT NOT NULL,entry_hash TEXT NOT NULL);
        ''')
        if 'mode' not in [r['name'] for r in self.db.execute('PRAGMA table_info(artifacts)')]:
            self.db.execute("ALTER TABLE artifacts ADD COLUMN mode TEXT NOT NULL DEFAULT 'UNVERIFIED'")

    @contextmanager
    def guard(self):
        # All stores/processes honour this local execution lock; no network API
        # accepts raw governance JSON. Crash leaves EXECUTING for manual recovery.
        with self._mutex:
            outer=self._depth==0
            if outer:
                if os.name=='nt':
                    import msvcrt
                    self._lockfile.seek(0);self._lockfile.write(b'0');self._lockfile.flush();self._lockfile.seek(0)
                    msvcrt.locking(self._lockfile.fileno(),msvcrt.LK_LOCK,1)
                else:
                    import fcntl
                    fcntl.flock(self._lockfile.fileno(),fcntl.LOCK_EX)
            self._depth+=1
            try:yield
            finally:
                self._depth-=1
                if outer:
                    if os.name=='nt':
                        import msvcrt
                        self._lockfile.seek(0);msvcrt.locking(self._lockfile.fileno(),msvcrt.LK_UNLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(self._lockfile.fileno(),fcntl.LOCK_UN)

    @contextmanager
    def transaction(self):
        with self.guard():
            self.db.execute('BEGIN IMMEDIATE')
            try:yield;self.db.execute('COMMIT')
            except BaseException:self.db.execute('ROLLBACK');raise

    def _audit(self,event,detail):
        prev=self.db.execute('SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        previous=prev[0] if prev else 'GENESIS'
        value={'time':now(),'actor':self.actor_provider(),'event':event,'detail':detail}
        encoded=json.dumps(value,sort_keys=True)
        self.db.execute('INSERT INTO audit(event,previous_hash,entry_hash) VALUES(?,?,?)',(encoded,previous,digest({'previous':previous,'event':value})))

    def audit(self):
        chain=[];previous='GENESIS'
        for row in self.db.execute('SELECT * FROM audit ORDER BY seq'):
            value=json.loads(row['event'])
            if row['previous_hash']!=previous or row['entry_hash']!=digest({'previous':previous,'event':value}):raise GateError('Audit hash chain mismatch')
            previous=row['entry_hash'];chain.append({**value,'entry_hash':previous})
        return chain

    def save(self,full,mode='UNVERIFIED'):
        validate(full,'Full',expected_producer='A');run_id=full['run_id'];version=digest(full)
        with self.transaction():
            old=self.db.execute('SELECT * FROM artifacts WHERE run_id=?',(run_id,)).fetchone()
            if old and old['version']==version:return version
            if old:
                self.db.execute("UPDATE batches SET state='INVALIDATED' WHERE run_id=? AND state IN ('PENDING','APPROVED')",(run_id,))
            self.db.execute('INSERT OR REPLACE INTO artifacts(run_id,snapshot,version,data,stale,mode) VALUES(?,?,?,?,0,?)',(run_id,full['source_snapshot_id'],version,json.dumps(full),mode))
            self._audit('ARTIFACT_SAVED',{'run_id':run_id,'version':version,'snapshot':full['source_snapshot_id']})
        return version

    def artifact(self,run_id):
        row=self.db.execute('SELECT * FROM artifacts WHERE run_id=?',(run_id,)).fetchone()
        if not row:raise GateError('Run artifact not found')
        return row,json.loads(row['data'])

    def propose(self,run_id,kind,target,payload):
        if kind not in ('JIRA_WRITE','REPORT_RELEASE','BASELINE_CHANGE'):raise GateError('Unsupported approval kind')
        with self.transaction():
            art,_=self.artifact(run_id)
            if art['stale']:raise GateError('Stale artifact requires regeneration')
            bid='BATCH-'+str(uuid4());sha=digest({'kind':kind,'target':target,'snapshot':art['snapshot'],'version':art['version'],'payload':payload})
            self.db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?,?,?,?,?,?)',(bid,run_id,art['snapshot'],art['version'],kind,target,json.dumps(payload),sha,'PENDING',None,None))
            self._audit('PROPOSAL_CREATED',{'batch_id':bid,'kind':kind,'hash':sha,'target':target})
        return self.batch(bid)

    def record_read(self,run_id,target,summary):
        """Log a verified read-only Jira readback (Brief: start read-only; the read path is logged)."""
        with self.transaction():
            self._audit('JIRA_READ_VERIFIED',{'run_id':run_id,'target':target,'summary':summary})

    def batch(self,bid):
        row=self.db.execute('SELECT * FROM batches WHERE id=?',(bid,)).fetchone()
        if not row:raise GateError('Batch not found')
        result=dict(row);result['payload']=json.loads(result['payload'])
        result['approval']=json.loads(result['approval']) if result['approval'] else None
        return result

    def approve(self,bid,*,confirmed_hash,decision='APPROVED',ttl_minutes=30):
        actor=self.actor_provider()
        if actor not in self.approvers:raise GateError('Local operator is not in HARBOURLINE_APPROVERS')
        if decision not in ('APPROVED','REJECTED'):raise GateError('Invalid human decision')
        with self.transaction():
            b=self.batch(bid);art,_=self.artifact(b['run_id'])
            if b['state']!='PENDING' or art['stale'] or b['artifact_version']!=art['version']:raise GateError('Proposal changed or is no longer pending')
            if confirmed_hash!=b['hash']:raise GateError('Confirm the exact reviewed proposal hash')
            approval={'approval_id':'APP-'+str(uuid4()),'approval_type':b['kind'],'subject_id':bid,'subject_version':b['hash'],
                      'requested_by':'A_BACKEND','approver_id':actor,'decision':decision,'decided_at':now(),
                      'source_snapshot_id':b['snapshot'],'notes':('SIMULATED TEST CHECKPOINT; not a real human approval. ' if b['target'].startswith('simulated://') else 'Local OS operator checkpoint; no sponsor approval is implied. ')}
            expires=(datetime.now(timezone.utc)+timedelta(minutes=ttl_minutes)).isoformat()
            self.db.execute('UPDATE batches SET state=?,approval=?,expires=? WHERE id=?',(decision,json.dumps(approval),expires,bid))
            self._audit('HUMAN_'+decision,{'batch_id':bid,'approval_id':approval['approval_id'],'hash':b['hash']})
        return approval

    def _check(self,b,target):
        art,_=self.artifact(b['run_id'])
        expected=digest({'kind':b['kind'],'target':b['target'],'snapshot':b['snapshot'],'version':b['artifact_version'],'payload':b['payload']})
        if expected!=b['hash']:raise GateError('Proposal payload was altered')
        if b['state']!='APPROVED' or not b['approval'] or b['approval']['subject_version']!=b['hash']:raise GateError('Human approval required')
        if b['expires']<now():raise GateError('Approval expired')
        if b['target']!=target:raise GateError('Execution target differs from reviewed target')
        if art['stale'] or art['version']!=b['artifact_version'] or art['snapshot']!=b['snapshot']:raise GateError('Artifact changed or became stale')

    def execute(self,bid,target,executor):
        with self.guard():
            try:
                with self.transaction():
                    b=self.batch(bid)
                    if b['target']!=target:raise GateError('Execution target differs from reviewed target')
                    if b['state']=='VERIFIED':return b
                    self._check(b,target)
                    self.db.execute("UPDATE batches SET state='EXECUTING' WHERE id=?",(bid,))
                    self._audit('EXECUTION_STARTED',{'batch_id':bid,'hash':b['hash']})
            except GateError:
                with self.transaction():self._audit('EXECUTION_BLOCKED',{'batch_id':bid})
                raise
            def committed_audit(event,detail):
                with self.transaction():self._audit(event,{'batch_id':bid,**detail})
            try:
                outcome=executor(deepcopy(b['payload']),committed_audit)
                with self.transaction():
                    self.db.execute("UPDATE batches SET state='VERIFIED' WHERE id=?",(bid,))
                    self._audit('EXECUTION_VERIFIED',{'batch_id':bid,'result':outcome})
            except Exception as exc:
                with self.transaction():
                    self.db.execute("UPDATE batches SET state='FAILED_REVIEW_REQUIRED' WHERE id=?",(bid,))
                    self._audit('EXECUTION_FAILED',{'batch_id':bid,'error_type':type(exc).__name__,'retry':'New review required; reconcile uncertain remote writes first.'})
                raise
            return self.batch(bid)

    def export(self,run_id):
        _,full=self.artifact(run_id);full=deepcopy(full)
        events=self.audit();rows=self.db.execute('SELECT id FROM batches WHERE run_id=? ORDER BY rowid',(run_id,)).fetchall()
        actions=[];approvals=[];entries=[]
        for row in rows:
            b=self.batch(row['id'])
            if b['approval']:
                approval=deepcopy(b['approval'])
                approval['notes']+=' Current execution state: '+b['state']+'; target: '+b['target']
                approvals.append(approval)
            related=[e for e in events if e['detail'].get('batch_id')==b['id']]
            if b['kind']=='JIRA_WRITE':
                for i,a in enumerate(b['payload'].get('actions',[]),1):
                    local_id='JIRA-'+str(i)
                    proof=next((e['detail'] for e in reversed(related) if e['event']=='JIRA_READBACK_VERIFIED' and e['detail'].get('action_id')==local_id),None)
                    attempted=any(e['event']=='JIRA_WRITE_ATTEMPT' and e['detail'].get('action_id')==local_id for e in related)
                    issue_key=(proof or {}).get('issue_key') or a.get('issue_key')
                    action={'action_id':b['id']+':'+local_id,'external_key':a.get('external_key',a.get('predecessor','')+'>'+a.get('successor','')),
                        'wbs_id':a.get('wbs_id'),'milestone_id':a.get('milestone_id'),'issue_key':issue_key,
                        'issue_type':a.get('fields',{}).get('issuetype',{}).get('id'),'summary':a.get('fields',{}).get('summary'),
                        'parent_issue_key':a.get('fields',{}).get('parent',{}).get('key'),'parent_external_key':a.get('parent_external_key'),
                        'action':'UPDATE' if a['action']=='LINK' else a['action'],
                        'execution_status':'EXECUTED' if proof else ('FAILED' if attempted else ('PENDING_APPROVAL' if b['state']=='PENDING' else 'SKIPPED')),
                        'approval_id':b['approval']['approval_id'] if b['approval'] else None,
                        'readback_verified':bool(proof),'readback_hash':proof.get('hash') if proof else None,
                        'labels':a.get('fields',{}).get('labels',[]),'error_message':None if proof or not attempted else 'Execution/readback incomplete; reconcile before a fresh approval.'}
                    if action['parent_external_key'] and not action['parent_issue_key']:
                        action['parent_issue_key']=next((x['issue_key'] for x in actions if x['external_key']==action['parent_external_key']),None)
                    actions.append(action)
            for i,e in enumerate(related):
                if e['event'] not in ('JIRA_READBACK_VERIFIED','EXECUTION_FAILED','EXECUTION_BLOCKED','EXECUTION_VERIFIED'):continue
                # Generic batch success is separately auditable; individual Jira proof comes from readback.
                if b['kind']=='JIRA_WRITE' and e['event']=='EXECUTION_VERIFIED':continue
                action_type='JIRA_UPDATE' if b['kind']=='JIRA_WRITE' else b['kind']
                entries.append({'audit_id':b['id']+':AUDIT:'+str(i),'action_id':b['id']+':'+e['detail'].get('action_id','BATCH'),
                    'action_type':action_type,'approval_id':b['approval']['approval_id'] if b['approval'] else None,
                    'actor_id':e['actor'],'occurred_at':e['time'],
                    'outcome':'SUCCESS' if e['event'] in ('JIRA_READBACK_VERIFIED','EXECUTION_VERIFIED') else ('BLOCKED' if e['event']=='EXECUTION_BLOCKED' else 'FAILED'),
                    'before_hash':None,'after_hash':e['detail'].get('hash'),'details':e['event']+'; '+b['target']})
        full['governance']['approvals']=approvals;full['governance']['audit_entries']=entries
        full['integration']['jira_actions']=actions
        project_keys={b['target'].split('#')[-1] for b in (self.batch(r['id']) for r in rows) if b['kind']=='JIRA_WRITE'}
        full['integration']['jira_project_key']=next(iter(project_keys)) if len(project_keys)==1 else None
        validate(full,'Full',expected_producer='A');return full

    def record_change(self,run_id,event):
        from modules.member_b.change import analyse_change
        with self.transaction():
            row,full=self.artifact(run_id)
            if not event.get('event_id') or not event.get('change_type'):raise GateError('Change event ID and type required')
            result=analyse_change(event,full['planning'],full['risk'])
            affected=set(result['stale_wbs_ids'])
            # Propagate to downstream WBS and milestones, then linked risk records.
            again=True
            while again:
                again=False
                for w in full['planning']['wbs_items']:
                    if w['wbs_id'] not in affected and (set(w['predecessor_wbs_ids'])&affected):affected.add(w['wbs_id']);again=True
            mids=set(result['stale_milestone_ids'])
            for m in full['planning']['milestones']:
                if set(m['related_wbs_ids'])&affected:mids.add(m['milestone_id'])
            again=True
            while again:
                again=False
                for m in full['planning']['milestones']:
                    if m['milestone_id'] not in mids and set(m['predecessor_milestone_ids'])&mids:mids.add(m['milestone_id']);again=True
            rids=set(result['stale_risk_ids'])
            for r in full['risk']['risks']:
                if set(r['related_wbs_ids'])&affected or set(r['related_milestone_ids'])&mids:rids.add(r['risk_id'])
            next_snapshot=event.get('new_source_snapshot_id') or full['source_snapshot_id']
            full['change']['events'].append({'change_id':event['event_id'],'description':event.get('description','Change review requested; not an approved baseline change.'),
                'source_refs':event.get('source_refs',[]),'status':'PROPOSED','approval_id':None,'affected_ids':sorted(affected|mids|rids)})
            stale=[('PLAN','PLAN'),('RISK_REGISTER','RISK_REGISTER')]
            for report in full['reporting']['reports']:
                report['is_stale']=True;report['status']='BLOCKED';stale.append((report['report_id'],'WEEKLY_REPORT' if report['report_type']=='WEEKLY_COMMITTEE' else 'MONTHLY_REPORT'))
            for review in full['reporting']['critic_reviews']:review['ready_for_human_review']=False
            for aid,kind in stale:
                full['change']['stale_artifacts'].append({'artifact_id':aid,'artifact_type':kind,'previous_snapshot_id':full['source_snapshot_id'],
                    'current_snapshot_id':next_snapshot,'reason':f"Change {event['event_id']} requires revalidation",'suggested_action':'Regenerate, review critic findings, then request fresh human approval.'})
            full['change']['human_actions']=result['human_actions'];full['status']='BLOCKED'
            validate(full,'Full',expected_producer='A')
            self.db.execute('UPDATE artifacts SET version=?,data=?,stale=1 WHERE run_id=?',(digest(full),json.dumps(full),run_id))
            self.db.execute("UPDATE batches SET state='INVALIDATED' WHERE run_id=? AND state IN ('PENDING','APPROVED')",(run_id,))
            self._audit('CHANGE_INVALIDATED_OUTPUTS',{'run_id':run_id,'event_id':event['event_id'],'wbs':sorted(affected),'milestones':sorted(mids),'risks':sorted(rids),'hypothetical':event.get('hypothetical',True)})
        return result
