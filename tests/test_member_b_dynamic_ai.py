"""Offline model doubles verify the live agent protocol, not a real OpenAI call."""
import copy
import json
import unittest
from modules.member_b.agent import generate,refine
from harbourline.contracts import validate

class FakeLibrary:
    def __init__(self):
        self.snapshot='SRC-TEST-ONLY'
        self.bundle={'b_source_mode':'BRIEF-2026-10-10-ONLY'}
        self.documents=[{'document_id':'DOC-1','version':'v1','source_type':'BRIEF',
                         'line_pages':[3,3,3,3], 'lines':[
                        'Scope. Upgrade the Hub for residents with a sports hall.',
                        'Install barrier-free lifts and upgrade mechanical systems.',
                        'The approved budget is S$18.5 million.',
                        'Opening dates are subject to Sponsor confirmation.']}]
    def eligible(self,doc,start,end,cutoff):return True
    def ref(self,doc,start,end):
        return {'document_id':doc['document_id'],'document_version':doc['version'],
                'source_type':doc['source_type'],'page':3,
                'line_start':start,'line_end':end,'chunk_id':f'{doc["document_id"]}:{start}-{end}',
                'quote':'\n'.join(doc['lines'][start-1:end])}
    def verify(self,ref,cutoff=None):
        d=self.documents[0]
        assert ref==self.ref(d,ref['line_start'],ref['line_end'])
        return True
    def line_registry(self):return {(self.documents[0]['document_id'],'v1'):self.documents[0]['lines']}


def request():
    return {'schema_version':'harbourline.v1','message_id':'REQUEST-1',
            'run_id':'B-AI-TEST-1','project_id':'HARBOURLINE-HUB',
            'producer':'A','recipient':'B','operation':'PLAN_RISK',
            'status':'SUCCESS','source_snapshot_id':'SRC-TEST-ONLY',
            'request':{'question':'Plan the Harbourline Hub','requested_report_type':None,
                       'reporting_period':{'start_date':None,'end_date':None},
                       'target_ids':[],'instructions':'Use only evidence',
                       'max_review_rounds':2}}


def draft_plan():
    return {'scope_statement':'PROPOSED: refurbish the community hub.',
      'sponsor_questions':[{'question_id':'Q01','question':'What is the approved start date?',
        'reason':'Date is missing','status':'OPEN','answer':None,'answer_source_ids':[]}],
      'scope_items':[{'scope_id':'S01','title':'Community hub renewal',
                      'description':'Upgrade access and services','status':'IN_SCOPE','source_ids':['E001']}],
      'wbs_items':[
        {'wbs_id':wid,'parent_wbs_id':parent,'title':title,'level':level,
         'dictionary':{'work_description':'Proposed work','deliverables':['evidence pack'],
          'acceptance_criteria':[],'exclusions':[],'assumptions':['No sponsor approval'],'owner':None},
         'scope_ids':['S01'],'predecessor_wbs_ids':[], 'source_ids':['E001'],'status':'PROPOSED'}
        for wid,parent,level,title in [('1',None,1,'Hub'),('1.1','1',2,'Facilities'),
                                      ('1.1.1','1.1',3,'Sports hall'),('1.1.2','1.1',3,'Lifts')]],
      'milestones':[{'milestone_id':'M01','title':'Proposed readiness review',
                     'relative_timing':'After works','calendar_date':None,
                     'predecessor_milestone_ids':[],'related_wbs_ids':['1.1.1'],
                     'source_ids':['E001'],'status':'PROPOSED'}]}


def draft_risk():
    return {'risks':[{'risk_id':'R01','title':'Lift delay','description':'Proposed risk',
                      'probability':3,'impact':4,'score':12,'owner':None,
                      'trigger':'Delivery after agreed window','response_plan':'Confirm timetable',
                      'related_wbs_ids':['1.1.2'],'related_milestone_ids':['M01'],
                      'source_ids':['E002'],'status':'OPEN'}],
       'scenarios':[{'scenario_id':'SC01','description':'Illustrative delay',
                     'assumptions':['Hypothetical 7 day delay and S$100/day, not in brief'],
                     'baseline_id':None,'schedule_impact_days':7,'cost_impact_sgd':700,
                     'calculation_basis':'7 × S$100/day (hypothetical)',
                     'affected_wbs_ids':['1.1.2'],'affected_risk_ids':['R01'],
                     'source_ids':['E002'],'estimate_status':'QUANTIFIED_ASSUMPTION'}]}


class MockGateway:
    mode='TEST_DOUBLE_NOT_OPENAI'
    def __init__(self,wrong_citation=False,wrong_score=False,critic='PASS'):
        self.calls=[];self.wrong_citation=wrong_citation
        self.wrong_score=wrong_score;self.critic=critic
    def ask(self,name,shape,instructions,payload):
        self.calls.append((name,payload))
        if name=='harbourline_b_planning':return {'planning':draft_plan()}
        if name=='harbourline_b_risk':
            r=draft_risk()
            if self.wrong_citation:r['risks'][0]['source_ids']=['E999']
            if self.wrong_score:r['risks'][0]['score']=11
            return {'risk':r}
        if name=='harbourline_b_critic':return {'verdict':self.critic,'findings':[] if self.critic=='PASS' else ['Review required']}
        raise ValueError(name)
    def metrics(self):return {'api_calls':len(self.calls),'input_tokens':30,'output_tokens':12,'estimated_cost_usd':None}

class DynamicAgentTests(unittest.TestCase):
    def test_generates_without_rules_seed_and_validates(self):
        g=MockGateway()
        out=generate(request(),FakeLibrary(),g)
        self.assertEqual([x[0] for x in g.calls],['harbourline_b_planning','harbourline_b_risk','harbourline_b_critic'])
        self.assertEqual(len(out['planning']['wbs_items']),4)
        self.assertEqual(out['risk']['risks'][0]['score'],12)
        self.assertEqual(out['metrics']['api_calls'],3)
        self.assertEqual(out['status'],'PARTIAL')
        self.assertNotIn('preliminary_plan',str(g.calls))
        validate(out,'B',expected_producer='B')
    def test_invalid_citation_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'nonexistent evidence'):
            generate(request(),FakeLibrary(),MockGateway(wrong_citation=True))
    def test_inconsistent_risk_score_blocked(self):
        with self.assertRaisesRegex(ValueError,'score must equal'):
            generate(request(),FakeLibrary(),MockGateway(wrong_score=True))
    def test_critic_escalation_blocked(self):
        with self.assertRaisesRegex(ValueError,'did not PASS'):
            generate(request(),FakeLibrary(),MockGateway(critic='ESCALATE'))
    def test_missing_evidence_blocks(self):
        lib=FakeLibrary();lib.documents=[]
        with self.assertRaisesRegex(ValueError,'library is empty'):
            generate(request(),lib,MockGateway())

if __name__=='__main__':unittest.main()
