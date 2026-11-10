"""Explicit scripted model doubles for integration tests. Never passed off as AI."""
from copy import deepcopy


class ScriptedModel:
    def __init__(self,revise_first=False,always_revise=False):
        self.calls=[];self.revise_first=revise_first;self.always_revise=always_revise;self.review_counts={}
    def __call__(self,name,payload):
        self.calls.append((name,deepcopy(payload)))
        if name=='harbourline_memory_draft':
            eid=next(iter(payload['evidence']));ref=payload['evidence'][eid]
            return {'answer_status':'SUPPORTED','answer':'SCRIPTED TEST: '+ref['quote'],'citation_ids':[eid],
                    'facts':[{'statement':ref['quote'],'status':'SUPPORTED','citation_ids':[eid]}],
                    'conflicts':[],'open_questions':[]}
        if name=='harbourline_report_draft':
            eid=next(iter(payload['verified_evidence']))
            return {'sections':[{'heading':'SCRIPTED INTEGRATION TEST — not a model report',
              'text':'Test evidence: '+payload['verified_evidence'][eid]['quote'],'evidence_ids':[eid]}],
              'open_issues':['This is a scripted test. No real model critique or human approval is established.'],
              'assumptions':['B context received '+str(len(payload['b_context']['planning']['wbs_items']))+' proposed WBS items.']}
        if name=='harbourline_critic_draft':
            kind=payload['report_type'];n=self.review_counts.get(kind,0)+1;self.review_counts[kind]=n
            revise=self.always_revise or (self.revise_first and n==1)
            return {'verdict':'REVISE' if revise else 'PASS','findings':([{'category':'FORMAT_ERROR','severity':'MINOR',
              'section_id':'SEC-01','description':'SCRIPTED finding for revision-loop test','required_fix':'Qualify test text.','evidence_ids':[]}] if revise else [])}
        if name=='harbourline_revision':
            return {'sections':[{'section_id':s['section_id'],'text':'Revised scripted test: '+s['text']} for s in payload['report']['sections']],
                    'open_issues':payload['report']['open_issues'],'assumptions':payload['report']['assumptions']}
        if name=='harbourline_planning_risk':
            if 'preliminary_plan' in payload:
                return {'planning':payload['preliminary_plan'],'risk':payload['preliminary_risk']}
            return {'wbs_updates': [], 'risk_updates': []}
        raise ValueError('Unknown scripted model task')
