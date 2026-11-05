from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from harbourline.sources import build_library,EvidenceLibrary,digest
from harbourline.llm import ModelGateway
from harbourline.simulation import ScriptedModel
from harbourline.governance import GovernanceStore,GateError
from harbourline.jira import MockJira,plan_actions,execute_actions
from harbourline.contracts import validate
from harbourline.pipeline import run_project
from modules.member_c.service import generate_reports

ROOT=Path(__file__).resolve().parents[1]

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        # Use actual locally extracted brief for module integration tests if prepared.
        self.records=json.loads((ROOT/'examples/test_source_registry.json').read_text())
        self.lib=build_library(self.records,self.root/'library.json')
        self.request=json.loads((ROOT/'examples/request.json').read_text())
        self.request.update(source_snapshot_id=self.lib.snapshot,run_id='TEST-RUN')
        self.request['request']['reporting_period']={'start_date':'2027-03-01','end_date':'2027-03-31'}
        registry=self.root/'registry.json';registry.write_text(json.dumps(self.records))
        self.context={'source_registry_path':str(registry)}
    def pipeline(self,**kwargs):
        self.script=ScriptedModel(revise_first=True)
        return run_project(self.request,self.lib.path,cutoff='2027-04-06',b_context=self.context,c_gateway=ModelGateway(responder=self.script),**kwargs)
    def store(self,full):
        s=GovernanceStore(self.root/'store.sqlite',approvers={'test-reviewer'},actor_provider=lambda:'test-reviewer');s.save(full)
        self.addCleanup(s.db.close);self.addCleanup(s._lockfile.close)
        return s
    def proposal(self):
        full,_=self.pipeline();store=self.store(full);jira=MockJira();payload=plan_actions(full,jira)
        batch=store.propose(full['run_id'],'JIRA_WRITE',jira.target,payload)
        return full,store,jira,batch
    def approve(self,s,b):s.approve(b['id'],confirmed_hash=b['hash'])
    def test_actual_b_to_c_both_reports_and_revision(self):
        full,trace=self.pipeline();validate(full,'Full')
        self.assertEqual(len(full['reporting']['reports']),2)
        self.assertEqual([r['revision'] for r in full['reporting']['reports']],[2,2])
        self.assertEqual(len(full['reporting']['critic_reviews']),4)
        self.assertTrue(full['integration']['handoff_completed'])
        self.assertTrue(any(x['event']=='AUTOMATIC_B_TO_C_HANDOFF' for x in trace))
        writers=[p for name,p in self.script.calls if name=='harbourline_report_draft']
        self.assertEqual(len(writers),2);self.assertGreater(len(writers[0]['b_context']['planning']['wbs_items']),3)
    def test_c_no_key_import_and_missing_config_blocks(self):
        from modules.member_c.adapter import run
        r={**self.request,'producer':'A','recipient':'C','operation':'GENERATE_REPORTS'}
        out=run(r,{'source_snapshot_id':self.lib.snapshot,'evidence_library':str(self.lib.path),'as_of_date':'2027-04-06','planning':{},'risk':{}})
        self.assertEqual(out['status'],'BLOCKED');self.assertEqual(out['metrics']['api_calls'],0)
    def test_snapshot_tamper_blocks(self):
        raw=json.loads(self.lib.path.read_text());raw['documents'][0]['lines'][0]+='changed';self.lib.path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):EvidenceLibrary(self.lib.path)
    def test_request_snapshot_mismatch(self):
        self.request['source_snapshot_id']='OTHER'
        with self.assertRaises(ValueError):self.pipeline()
    def test_live_planning_path_can_be_injected_for_tests(self):
        script=ScriptedModel();full,_=self.pipeline(plan_mode='live',b_gateway=ModelGateway(responder=script))
        self.assertTrue(any(n=='harbourline_planning_risk' for n,p in script.calls));self.assertEqual(full['producer'],'A')
    def test_max_rounds_escalate(self):
        lib=self.lib;full,_=self.pipeline()
        ctx={'planning':full['planning'],'risk':full['risk'],'as_of_date':'2027-04-06','b_source_evidence':[]}
        _,reports=generate_reports(self.request,ctx,lib,ModelGateway(responder=ScriptedModel(always_revise=True)))
        self.assertTrue(all(r['status']=='BLOCKED' for r in reports['reports']))
        self.assertEqual(len(reports['critic_reviews']),4)
    def test_unknown_date_excluded(self):
        record={'document_id':'UNDATED','version':'1','source_type':'DATA_PACK','page':None,'lines':['budget unknown source']}
        lib=build_library(self.records+[record],self.root/'dated.json')
        self.assertNotIn('UNDATED',[r['document_id'] for r in lib.search('budget','2027-04-06')])
    def test_future_excluded(self):
        record={'document_id':'FUTURE','version':'1','source_type':'DATA_PACK','page':None,'lines':['budget future']}
        lib=build_library(self.records+[record],self.root/'dated.json',metadata={'FUTURE':{'available_from':'2027-05-01'}})
        self.assertNotIn('FUTURE',[r['document_id'] for r in lib.search('budget','2027-04-06')])
    def test_citation_page_tamper(self):
        ref=self.lib.search('budget')[0];ref['page']=999
        with self.assertRaises(ValueError):self.lib.verify(ref)
    def test_no_approval_no_jira_write(self):
        full,s,j,b=self.proposal()
        with self.assertRaises(GateError):s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
        self.assertEqual(j.writes,0)
    def test_wrong_operator(self):
        _,s,j,b=self.proposal();s.approvers=set()
        with self.assertRaises(GateError):self.approve(s,b)
    def test_wrong_review_hash(self):
        _,s,j,b=self.proposal()
        with self.assertRaises(GateError):s.approve(b['id'],confirmed_hash='wrong')
    def test_approved_jira_parent_dependency_readback(self):
        full,s,j,b=self.proposal();self.approve(s,b)
        result=s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
        self.assertEqual(result['state'],'VERIFIED');self.assertTrue(j.links)
        for issue in j.issues.values():
            if issue['fields']['issuetype']['id']=='10002':self.assertIn('parent',issue['fields'])
        self.assertTrue(any(x['event']=='JIRA_READBACK_VERIFIED' for x in s.audit()))
    def test_same_batch_idempotent(self):
        _,s,j,b=self.proposal();self.approve(s,b);s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a));writes=j.writes
        s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a));self.assertEqual(j.writes,writes)
    def test_new_preview_uses_existing_work(self):
        full,s,j,b=self.proposal();self.approve(s,b);s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a));writes=j.writes
        payload=plan_actions(full,j);self.assertFalse(any(x['action']=='CREATE' for x in payload['actions']))
        b2=s.propose(full['run_id'],'JIRA_WRITE',j.target,payload);self.approve(s,b2);s.execute(b2['id'],j.target,lambda p,a:execute_actions(p,j,a));self.assertEqual(j.writes,writes)
    def test_remote_change_since_preview_blocks(self):
        full,s,j,b=self.proposal();self.approve(s,b);s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
        b2=s.propose(full['run_id'],'JIRA_WRITE',j.target,plan_actions(full,j));self.approve(s,b2)
        next(iter(j.issues.values()))['fields']['summary']='Human edit';writes=j.writes
        with self.assertRaises(GateError):s.execute(b2['id'],j.target,lambda p,a:execute_actions(p,j,a))
        self.assertEqual(j.writes,writes)
    def test_readback_failure_logged_and_no_auto_retry(self):
        _,s,j,b=self.proposal();self.approve(s,b);j.corrupt=True
        with self.assertRaises(GateError):s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
        self.assertEqual(s.batch(b['id'])['state'],'FAILED_REVIEW_REQUIRED');writes=j.writes
        events=[x['event'] for x in s.audit()];self.assertIn('JIRA_WRITE_ATTEMPT',events);self.assertIn('EXECUTION_FAILED',events)
        with self.assertRaises(GateError):s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
        self.assertEqual(j.writes,writes)
    def test_changed_target_blocks(self):
        _,s,j,b=self.proposal();self.approve(s,b)
        with self.assertRaises(GateError):s.execute(b['id'],'other-site',lambda p,a:execute_actions(p,j,a))
    def test_expired_approval(self):
        _,s,j,b=self.proposal();s.approve(b['id'],confirmed_hash=b['hash'],ttl_minutes=-1)
        with self.assertRaises(GateError):s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
    def test_payload_tamper_blocks(self):
        _,s,j,b=self.proposal();self.approve(s,b)
        s.db.execute('UPDATE batches SET payload=? WHERE id=?',(json.dumps({'actions':[]}),b['id']))
        with self.assertRaises(GateError):s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
    def test_change_invalidates_both_reports_and_approval(self):
        full,s,j,b=self.proposal();self.approve(s,b)
        s.record_change(full['run_id'],{'event_id':'TEST-CHANGE','change_type':'LIFT_DELAY','hypothetical':True})
        row,state=s.artifact(full['run_id']);self.assertTrue(row['stale']);self.assertTrue(all(r['is_stale'] for r in state['reporting']['reports']))
        self.assertEqual(s.batch(b['id'])['state'],'INVALIDATED')
        with self.assertRaises(GateError):s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
        self.assertEqual(j.writes,0)
    def test_unknown_change_conservatively_stales(self):
        full,s,j,b=self.proposal();s.record_change(full['run_id'],{'event_id':'UNKNOWN','change_type':'NEW_TYPE'})
        self.assertTrue(s.artifact(full['run_id'])[0]['stale'])
    def test_governance_contract_export(self):
        full,s,j,b=self.proposal();self.approve(s,b);s.execute(b['id'],j.target,lambda p,a:execute_actions(p,j,a))
        exported=s.export(full['run_id']);validate(exported,'Full')
        self.assertEqual(len(exported['governance']['approvals']),1)
        self.assertTrue(exported['governance']['audit_entries'])
        self.assertTrue(all(a['readback_verified'] for a in exported['integration']['jira_actions']))
    def test_separate_weekly_and_monthly_periods(self):
        full,_=self.pipeline(reporting_periods={'WEEKLY_COMMITTEE':{'start_date':'2027-03-25','end_date':'2027-03-31'}})
        self.assertEqual(full['reporting']['reports'][0]['reporting_period']['start_date'],'2027-03-25')
        self.assertEqual(full['reporting']['reports'][1]['reporting_period']['start_date'],'2027-03-01')
    def test_corrupt_model_citation_is_blocked(self):
        from modules.member_c.adapter import run
        def corrupt(name,payload):
            return {'answer_status':'SUPPORTED','answer':'invented','citation_ids':['NO-SUCH-ID'],'facts':[],'conflicts':[],'open_questions':[]}
        request={**self.request,'producer':'A','recipient':'C','operation':'MEMORY_QUERY'}
        request['request']['question']='budget'
        out=run(request,{'source_snapshot_id':self.lib.snapshot,'evidence_library':str(self.lib.path),'model_gateway':ModelGateway(responder=corrupt)})
        self.assertEqual(out['status'],'BLOCKED')
    def test_real_gateway_measures_usage_without_network(self):
        import os
        from unittest.mock import patch
        from types import SimpleNamespace
        gateway=ModelGateway(model='test-model')
        class Responses:
            def create(self,**kwargs):
                self.kwargs=kwargs
                return SimpleNamespace(status='completed',output_text='{"ok":true}',usage=SimpleNamespace(input_tokens=12,output_tokens=4))
        responses=Responses();gateway._client=SimpleNamespace(responses=responses)
        shape={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'not-a-real-key'},clear=False):
            self.assertEqual(gateway.ask('test',shape,'instruction',{}),{'ok':True})
        self.assertEqual(gateway.metrics()['api_calls'],1);self.assertEqual(gateway.metrics()['input_tokens'],12)
        self.assertIsNone(gateway.metrics()['estimated_cost_usd']);self.assertFalse(responses.kwargs['store'])
    def test_semantic_index_source_mismatch(self):
        path=self.root/'semantic.json';path.write_text(json.dumps({'source_snapshot_id':'WRONG','model':'test','chunks':[]}))
        self.lib.semantic_path=path
        with self.assertRaises(ValueError):self.lib.search('budget',gateway=ModelGateway(responder=ScriptedModel()))
    def test_semantic_retrieval_uses_verified_snapshot(self):
        ref=self.lib.search('budget')[0]
        path=self.root/'semantic.json';path.write_text(json.dumps({'source_snapshot_id':self.lib.snapshot,'model':'test','chunks':[{'source':ref,'vector':[1.0,0.0]}]}))
        self.lib.semantic_path=path
        class Gateway:
            def embeddings(self,texts,model):return [[1.0,0.0]]
        self.assertEqual(self.lib.search('budget',gateway=Gateway())[0],ref)
    def test_b_unknown_date_context_blocks_c(self):
        from modules.member_c.adapter import run
        full,_=self.pipeline()
        records=self.records+[{'document_id':'UNDATED','version':'1','source_type':'DATA_PACK','page':None,'lines':['budget unknown']}]
        lib=build_library(records,self.root/'extra.json')
        request={**self.request,'recipient':'C','operation':'GENERATE_REPORTS','source_snapshot_id':lib.snapshot}
        ref=lib.ref(lib.documents[-1],1,1)
        # Locate the deliberately undated record irrespective of sort order.
        ref=lib.ref(next(d for d in lib.documents if d['document_id']=='UNDATED'),1,1)
        out=run(request,{'source_snapshot_id':lib.snapshot,'evidence_library':str(lib.path),'as_of_date':'2027-04-06',
              'planning':full['planning'],'risk':full['risk'],'b_source_evidence':[ref],'model_gateway':ModelGateway(responder=ScriptedModel())})
        self.assertEqual(out['status'],'BLOCKED')
    def test_failed_model_call_does_not_claim_known_tokens(self):
        import os
        from unittest.mock import patch
        from types import SimpleNamespace
        gateway=ModelGateway(model='test-model')
        class Responses:
            def create(self,**kwargs):raise RuntimeError('simulated timeout')
        gateway._client=SimpleNamespace(responses=Responses())
        with patch.dict(os.environ,{'OPENAI_API_KEY':'not-a-real-key'},clear=False):
            with self.assertRaises(RuntimeError):gateway.ask('test',{'type':'object'},'instruction',{})
        self.assertEqual(gateway.metrics()['api_calls'],1);self.assertIsNone(gateway.metrics()['input_tokens'])
    def test_store_records_scripted_mode(self):
        full,_=self.pipeline();s=self.store(full);full['run_id']='SCRIPTED-OTHER';s.save(full,mode='SCRIPTED_TEST')
        self.assertEqual(s.artifact(full['run_id'])[0]['mode'],'SCRIPTED_TEST')
    def test_changed_artifact_invalidates_approval(self):
        full,s,j,b=self.proposal();self.approve(s,b);full['request']['instructions']+=' updated';s.save(full)
        self.assertEqual(s.batch(b['id'])['state'],'INVALIDATED')
    def test_audit_tamper_detected(self):
        full,s,j,b=self.proposal();s.db.execute("UPDATE audit SET event='{}' WHERE seq=1")
        with self.assertRaises(GateError):s.audit()

if __name__=='__main__':unittest.main()
