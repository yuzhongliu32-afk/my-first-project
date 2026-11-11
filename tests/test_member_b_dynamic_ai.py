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


def whatif_proposal():
    el=lambda eid,kind,o,m,p,crit:{'element_id':eid,'label':eid,'kind':kind,
        'unit':'SGD_THOUSANDS' if kind=='COST' else 'WEEKS','optimistic':o,'most_likely':m,
        'pessimistic':p,'reason_optimistic':'low bound in E002','reason_most_likely':'E002',
        'reason_pessimistic':'high bound in E002','on_critical_path':crit,'source_ids':['E002']}
    return {'scenarios':[{'scenario_id':'SC01','title':'Lift delay','description':'Lift works slip',
        'assumptions':['Ranges from E002'],'affected_wbs_ids':['1.1.2'],'affected_risk_ids':['R01'],
        'elements':[el('C1','COST',350,450,600,False),el('W1','SCHEDULE',4,5,6,True)],
        'unresolved':['Roof strengthening cost'],'source_ids':['E002']}]}


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
        if name=='harbourline_b_whatif':return whatif_proposal()
        if name=='harbourline_b_critic':
            return {'verdict':self.critic,'notes':['Observation for the reviewer'],
                    'blocking_findings':[] if self.critic=='PASS' else
                        [{'item_id':'R01','problem':'Review required','evidence_ids':['E002']}]}
        raise ValueError(name)
    def metrics(self):return {'api_calls':len(self.calls),'input_tokens':30,'output_tokens':12,'estimated_cost_usd':None}

class DynamicAgentTests(unittest.TestCase):
    def test_generates_without_rules_seed_and_validates(self):
        g=MockGateway()
        out=generate(request(),FakeLibrary(),g)
        self.assertEqual([x[0] for x in g.calls],['harbourline_b_planning','harbourline_b_risk','harbourline_b_whatif','harbourline_b_critic'])
        self.assertEqual(len(out['planning']['wbs_items']),4)
        self.assertEqual(out['risk']['risks'][0]['score'],12)
        self.assertEqual(out['metrics']['api_calls'],4)
        self.assertEqual(out['status'],'PARTIAL')
        self.assertNotIn('preliminary_plan',str(g.calls))
        validate(out,'B',expected_producer='B')
    def test_invalid_citation_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'nonexistent evidence'):
            generate(request(),FakeLibrary(),MockGateway(wrong_citation=True))
    def test_inconsistent_risk_score_blocked(self):
        with self.assertRaisesRegex(ValueError,'score must equal'):
            generate(request(),FakeLibrary(),MockGateway(wrong_score=True))
    def test_critic_finding_revises_only_the_named_role(self):
        class WhatIfFinding(MockGateway):
            def ask(self,name,shape,instructions,payload):
                if name=='harbourline_b_critic':
                    self.calls.append((name,payload))
                    first=sum(1 for n,_ in self.calls if n=='harbourline_b_critic')==1
                    return {'verdict':'REVISE' if first else 'PASS','notes':[],
                            'blocking_findings':[{'item_id':'SC01','problem':'Most likely value unsupported',
                                                  'evidence_ids':['E002']}] if first else []}
                return super().ask(name,shape,instructions,payload)
        g=WhatIfFinding()
        out=generate(request(),FakeLibrary(),g,max_rounds=2)
        names=[n for n,_ in g.calls]
        self.assertEqual(names,['harbourline_b_planning','harbourline_b_risk','harbourline_b_whatif',
                                'harbourline_b_critic','harbourline_b_whatif','harbourline_b_critic'])
        second_whatif=g.calls[4][1]
        self.assertIn('CRITIC: SC01',' '.join(second_whatif['prior_findings']))
        self.assertIsNotNone(second_whatif['previous_attempt'])  # revise, not rewrite
        self.assertEqual(out['status'],'PARTIAL')
    def test_critic_notes_do_not_block_but_are_kept(self):
        class NotesOnly(MockGateway):
            def ask(self,name,shape,instructions,payload):
                if name=='harbourline_b_critic':
                    self.calls.append((name,payload))
                    return {'verdict':'REVISE','blocking_findings':[],
                            'notes':['M05 is overdue; flag for the reviewer']}
                return super().ask(name,shape,instructions,payload)
        trace={}
        out=generate(request(),FakeLibrary(),NotesOnly(),trace=trace)
        self.assertEqual(out['status'],'PARTIAL')
        self.assertEqual(trace['critic_notes'],['M05 is overdue; flag for the reviewer'])
    def test_critic_blocking_finding_starts_new_round(self):
        g=MockGateway(critic='REVISE')
        with self.assertRaisesRegex(ValueError,'R01: Review required'):
            generate(request(),FakeLibrary(),g,max_rounds=2)
        self.assertEqual(sum(1 for n,_ in g.calls if n=='harbourline_b_critic'),2)
    def test_critic_complaint_about_open_question_is_a_note(self):
        from modules.member_b.agent import _triage_critique
        plan={'wbs_items':[{'wbs_id':'1.2','status':'PROPOSED'}],'milestones':[],'scope_items':[],
              'sponsor_questions':[{'question_id':'Q01','status':'OPEN'},{'question_id':'Q02','status':'ANSWERED'}]}
        c={'verdict':'REVISE','notes':[],'blocking_findings':[
            {'item_id':'Q01','problem':'still open with no answer','evidence_ids':[]},
            {'item_id':'Q02','problem':'answer cites the brief, not the Sponsor','evidence_ids':['E1']},
            {'item_id':'WBS 1.2','problem':'budget not in evidence','evidence_ids':['E2']},
            {'item_id':'X99','problem':'unknown item','evidence_ids':[]}]}
        t=_triage_critique(c,plan,{'risks':[],'scenarios':[]})
        self.assertEqual([b['item_id'] for b in t['blocking_findings']],['Q02','WBS 1.2'])
        self.assertEqual(len(t['notes']),2)
    def test_proposed_owner_complaint_is_a_note_but_unlabelled_owner_blocks(self):
        from modules.member_b.agent import _triage_critique, _route
        plan={'wbs_items':[],'milestones':[],'scope_items':[],'sponsor_questions':[]}
        risk={'risks':[{'risk_id':'R01','owner':'Proposed: Council PM'},{'risk_id':'R02','owner':'KHB'}],'scenarios':[]}
        c={'verdict':'REVISE','notes':[],'blocking_findings':[
            {'item_id':'R01','problem':'assigns Council PM as owner without evidence','evidence_ids':[]},
            {'item_id':'R02','problem':'assigns KHB as owner without evidence','evidence_ids':[]}]}
        t=_triage_critique(c,plan,risk)
        self.assertEqual([b['item_id'] for b in t['blocking_findings']],['R02'])
        self.assertEqual(_route('W02'),{'whatif'})
    def test_invented_day_is_removed_but_sourced_date_kept(self):
        from modules.member_b.agent import _unsupported_dates
        cat={'E1':{'quote':'Enrolment is intended to begin in July 2028.'},
             'E2':{'quote':'Site possession is Monday 4 January 2027.'}}
        p={'milestones':[{'milestone_id':'M12','calendar_date':'2028-07-01','relative_timing':'Month 18','source_ids':['E1']},
                         {'milestone_id':'M02','calendar_date':'2027-01-04','relative_timing':'Start','source_ids':['E2']}]}
        self.assertEqual(_unsupported_dates(p,cat),['M12'])
        self.assertIsNone(p['milestones'][0]['calendar_date'])
        self.assertIn('July 2028',p['milestones'][0]['relative_timing'])
        self.assertEqual(p['milestones'][1]['calendar_date'],'2027-01-04')
    def test_unsourced_owner_is_labelled_proposed_by_code(self):
        from modules.member_b.agent import _label_unsourced_owners
        cat={'E1':{'quote':'Owner: Project Manager.'},'E2':{'quote':'Asbestos confirmed.'}}
        r={'risks':[{'risk_id':'R01','owner':'KHB','source_ids':['E2']},
                    {'risk_id':'R02','owner':'Project Manager','source_ids':['E1']}]}
        self.assertEqual(_label_unsourced_owners(r,cat),['R01'])
        self.assertEqual([x['owner'] for x in r['risks']],['Proposed: KHB','Project Manager'])
    def test_critic_escalation_blocked(self):
        with self.assertRaisesRegex(ValueError,'did not PASS'):
            generate(request(),FakeLibrary(),MockGateway(critic='ESCALATE'))
    def test_mechanical_failure_is_fed_back_and_corrected(self):
        class FixesOnSecondTry(MockGateway):
            def ask(self,name,shape,instructions,payload):
                attempt=sum(1 for n,_ in self.calls if n=='harbourline_b_risk')
                self.wrong_citation = name=='harbourline_b_risk' and attempt==0
                return super().ask(name,shape,instructions,payload)
        g=FixesOnSecondTry()
        out=generate(request(),FakeLibrary(),g,max_rounds=2)
        names=[x[0] for x in g.calls]
        # Only the Risk role failed its code check, so only Risk is asked again, with the finding;
        # the accepted Planning output is not regenerated.
        self.assertEqual(names,['harbourline_b_planning','harbourline_b_risk','harbourline_b_risk',
                                'harbourline_b_whatif','harbourline_b_critic'])
        second_risk_payload=g.calls[2][1]
        self.assertIn('MECHANICAL_CHECK_FAILED',' '.join(second_risk_payload['prior_findings']))
        self.assertIsNotNone(second_risk_payload['previous_attempt'])
        self.assertEqual(out['status'],'PARTIAL')
    def test_untraceable_wbs_is_flagged_not_rejected(self):
        class NoScope(MockGateway):
            def ask(self,name,shape,instructions,payload):
                out=super().ask(name,shape,instructions,payload)
                if name=='harbourline_b_planning':out['planning']['wbs_items'][3]['scope_ids']=[]
                return out
        trace={}
        out=generate(request(),FakeLibrary(),NoScope(),trace=trace)
        w=[x for x in out['planning']['wbs_items'] if x['wbs_id']=='1.1.2'][0]
        self.assertEqual(w['status'],'UNRESOLVED')
        self.assertEqual(trace['auto_flags'][0]['wbs_ids'],['1.1.2'])
    def test_missing_evidence_blocks(self):
        lib=FakeLibrary();lib.documents=[]
        with self.assertRaisesRegex(ValueError,'library is empty'):
            generate(request(),lib,MockGateway())

if __name__=='__main__':unittest.main()


class DanglingRiskLinks(unittest.TestCase):
    def test_links_to_removed_plan_items_are_dropped(self):
        from modules.member_b.agent import _drop_dangling_links
        plan = {'wbs_items': [{'wbs_id': 'W01'}], 'milestones': [{'milestone_id': 'M01'}]}
        risk = {'risks': [{'risk_id': 'R03', 'related_wbs_ids': ['W01', 'W09'], 'related_milestone_ids': ['M07', 'M01']},
                          {'risk_id': 'R04', 'related_wbs_ids': ['W01'], 'related_milestone_ids': []}]}
        self.assertEqual(_drop_dangling_links(risk, plan), {'R03': ['W09', 'M07']})
        self.assertEqual(risk['risks'][0]['related_wbs_ids'], ['W01'])
        self.assertEqual(risk['risks'][0]['related_milestone_ids'], ['M01'])


class WhatIfRetry(unittest.TestCase):
    def test_failed_whatif_retry_sends_a_serialisable_previous_attempt(self):
        class BadFirstWhatIf(MockGateway):
            def ask(self, name, shape, instructions, payload):
                if name == 'harbourline_b_whatif' and not any(n == name for n, _ in self.calls):
                    self.calls.append((name, payload))
                    bad = whatif_proposal(); bad['scenarios'][0]['affected_wbs_ids'] = ['9.9.9']
                    return bad
                return super().ask(name, shape, instructions, payload)
        g = BadFirstWhatIf()
        generate(request(), FakeLibrary(), g)
        whatifs = [p for n, p in g.calls if n == 'harbourline_b_whatif']
        self.assertEqual(len(whatifs), 2)
        json.dumps(whatifs[1])  # must not contain exception objects
        self.assertTrue(whatifs[1]['prior_findings'])


class ContingencyUnits(unittest.TestCase):
    def test_contingency_must_match_a_cited_amount_in_whole_dollars(self):
        from modules.member_b.change_note import _sgd_amounts
        amounts = _sgd_amounts('the approved budget of S$18.5 million leaves about S$1.18 million; claim S$985,000')
        self.assertEqual(amounts, {18_500_000, 1_180_000, 985_000})
        near = lambda v: any(abs(v - a) <= 0.01 * a for a in amounts)
        self.assertTrue(not near(1180) and near(1180 * 1000))   # thousands slip: rejected by validate_note
        self.assertTrue(near(1_180_000))                         # whole dollars: accepted
