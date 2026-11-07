"""Approved, idempotent Jira Cloud create/update/link with exact-field readback."""
import base64
from copy import deepcopy
import json
import os
import re
from urllib.parse import urlencode,quote,urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from .sources import digest
from .governance import GateError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


class JiraCloud:
    mode='LIVE_JIRA'
    def __init__(self,base_url,email,token,project):
        parsed=urlsplit(base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use a credential-free HTTPS Jira base URL')
        if parsed.path.rstrip('/') or not re.fullmatch(r'[A-Z][A-Z0-9_]*',project):raise ValueError('Invalid Jira base URL/project key')
        self.base=base_url.rstrip('/');self.project=project
        self.known={}
        self.auth=base64.b64encode(f'{email}:{token}'.encode()).decode();self.opener=build_opener(NoRedirect())

    @classmethod
    def from_env(cls):
        values=[os.getenv(k) for k in ('JIRA_BASE_URL','JIRA_EMAIL','JIRA_API_TOKEN','JIRA_PROJECT_KEY')]
        if not all(values):raise ValueError('Jira environment configuration incomplete')
        return cls(*values)

    @property
    def target(self):return self.base+'#'+self.project

    def request(self,method,path,body=None):
        if method not in ('GET','POST','PUT'):raise GateError('Jira delete/transition operations prohibited')
        if 'transitions' in path or '/archive' in path:raise GateError('Jira closing/archive operations prohibited')
        req=Request(self.base+'/rest/api/3'+path,data=None if body is None else json.dumps(body).encode(),method=method,
                    headers={'Authorization':'Basic '+self.auth,'Content-Type':'application/json','Accept':'application/json'})
        try:
            with self.opener.open(req,timeout=30) as res:
                raw=res.read();return json.loads(raw) if raw else {}
        except HTTPError as e:raise GateError(f'Jira HTTP {e.code}; request body/credentials omitted') from None
        except URLError:raise GateError('Jira network failure; reconcile any uncertain remote write before retry') from None

    def types(self):
        found={};token=None
        for _ in range(10):
            args={'maxResults':100}
            if token:args['startAt']=token
            data=self.request('GET',f'/issue/createmeta/{quote(self.project)}/issuetypes?'+urlencode(args))
            for row in data.get('issueTypes',data.get('values',[])):found[row['name']]=str(row['id'])
            if data.get('isLast',True):return found
            token=data.get('startAt',0)+len(data.get('issueTypes',data.get('values',[])))
        raise GateError('Issue-type metadata pagination limit')

    def find(self,label):
        if not re.fullmatch(r'hl-[a-f0-9]{24}',label):raise GateError('Invalid external label')
        if label in self.known:
            issue=self.get(self.known[label])
            if label not in issue['fields'].get('labels',[]):raise GateError('Stored external mapping no longer matches Jira')
            return issue
        data=self.request('POST','/search/jql',{'jql':f'project = "{self.project}" AND labels = "{label}"','fields':['summary','description','labels','parent','issuetype','duedate'],'maxResults':2})
        issues=data.get('issues',[])
        if len(issues)>1 or not data.get('isLast',True):raise GateError('Duplicate external ID; human reconciliation needed')
        return issues[0] if issues else None

    def get(self,key):
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+',key):raise GateError('Invalid Jira key')
        return self.request('GET','/issue/'+key+'?fields=summary,description,labels,parent,issuetype,duedate,issuelinks')

    def create(self,fields):return self.request('POST','/issue',{'fields':fields})['key']
    def update(self,key,fields):self.request('PUT','/issue/'+key,{'fields':fields})
    def link(self,predecessor,successor):self.request('POST','/issueLink',{'type':{'name':'Blocks'},'inwardIssue':{'key':predecessor},'outwardIssue':{'key':successor}})
    def linked(self,predecessor,successor):
        for link in self.get(predecessor)['fields'].get('issuelinks',[]):
            if link.get('type',{}).get('outward','').lower()=='blocks' and link.get('outwardIssue',{}).get('key')==successor:return True
        return False


def marker(external):return 'hl-'+digest(external)[:24]


def adf(text):return {'type':'doc','version':1,'content':[{'type':'paragraph','content':[{'type':'text','text':text}]}]}


def normal(fields):
    result={k:deepcopy(fields.get(k)) for k in ('summary','description','labels','parent','issuetype','duedate') if k in fields}
    for key in ('parent','issuetype'):
        if result.get(key):result[key]={('key' if key=='parent' else 'id'):str(result[key]['key' if key=='parent' else 'id'])}
    if 'labels'in result:result['labels']=sorted(result['labels'])
    return result


def matches(actual,expected):return all(normal(actual).get(k)==v for k,v in normal(expected).items())


def plan_actions(full,jira):
    if full.get('change',{}).get('stale_artifacts') or any(r['is_stale'] for r in full['reporting']['reports']):raise GateError('Stale project outputs block Jira preview')
    types=jira.types();actions=[];lookup={};project=jira.project
    level_names={1:os.getenv('JIRA_TYPE_LEVEL1','Epic'),2:os.getenv('JIRA_TYPE_LEVEL2','Task'),3:os.getenv('JIRA_TYPE_LEVEL3','Sub-task')}
    def add(external,title,description,type_name,parent=None,date=None,wbs_id=None,milestone_id=None):
        if type_name not in types:raise GateError(f'Jira issue type unavailable: {type_name}; configure explicit type mapping')
        fields={'project':{'key':project},'summary':title,'description':adf(description),
                'issuetype':{'id':types[type_name]},'labels':[marker(external),'harbourline-proposed','ai-generated']}
        if date:fields['duedate']=date
        existing=jira.find(marker(external));key=existing['key'] if existing else None
        parent_key=lookup.get(parent,{}).get('issue_key') if parent else None
        if parent_key:fields['parent']={'key':parent_key}
        before=normal(jira.get(key)['fields']) if key else None
        action={'external_key':external,'label':marker(external),'action':'UPDATE' if key else 'CREATE',
                'issue_key':key,'fields':fields,'parent_external_key':parent,'before':before,
                'wbs_id':wbs_id,'milestone_id':milestone_id}
        actions.append(action);lookup[external]=action
    work=sorted(full['planning']['wbs_items'],key=lambda w:(w['level'],w['wbs_id']))
    for w in work:
        external=f"{project}:WBS:{w['wbs_id']}";parent=f"{project}:WBS:{w['parent_wbs_id']}" if w['parent_wbs_id'] else None
        add(external,w['title'],f"PROPOSED — external ID {external}\n"+json.dumps(w['dictionary'],ensure_ascii=False),level_names[w['level']],parent,wbs_id=w['wbs_id'])
    for m in full['planning']['milestones']:
        external=f"{project}:MILESTONE:{m['milestone_id']}"
        add(external,m['title'],f"PROPOSED milestone — external ID {external}\nRelative timing: {m['relative_timing']}; linked WBS: {m['related_wbs_ids']}",os.getenv('JIRA_TYPE_MILESTONE','Task'),date=m['calendar_date'],milestone_id=m['milestone_id'])
    for w in work:
        for pred in w['predecessor_wbs_ids']:
            actions.append({'action':'LINK','predecessor':f'{project}:WBS:{pred}','successor':f"{project}:WBS:{w['wbs_id']}"})
    for m in full['planning']['milestones']:
        for pred in m['predecessor_milestone_ids']:
            actions.append({'action':'LINK','predecessor':f'{project}:MILESTONE:{pred}','successor':f"{project}:MILESTONE:{m['milestone_id']}"})
    return {'target':jira.target,'transport':jira.mode,'actions':actions}


def execute_actions(payload,jira,audit):
    if payload['target']!=jira.target or payload['transport']!=jira.mode:raise GateError('Jira service differs from approved preview')
    keys={};verified=[]
    # Recheck ALL remote preconditions before the first write, avoiding stale approved edits.
    for a in payload['actions']:
        if a['action']=='LINK':continue
        current=jira.find(a['label'])
        if a['action']=='CREATE' and current:raise GateError('Proposed create already exists; generate a fresh preview')
        if a['action']=='UPDATE':
            if not current or current['key']!=a['issue_key'] or normal(jira.get(a['issue_key'])['fields'])!=a['before']:
                raise GateError('Jira changed since approval; generate a new preview')
    for index,a in enumerate(payload['actions']):
        action_id='JIRA-'+str(index+1)
        if a['action']=='LINK':
            pred,succ=keys[a['predecessor']],keys[a['successor']]
            if not jira.linked(pred,succ):
                audit('JIRA_WRITE_ATTEMPT',{'action_id':action_id,'action':'LINK','predecessor':pred,'successor':succ})
                jira.link(pred,succ)
                audit('JIRA_WRITE_RETURNED',{'action_id':action_id,'action':'LINK'})
            if not jira.linked(pred,succ):raise GateError('Jira dependency readback differs')
            audit('JIRA_READBACK_VERIFIED',{'action_id':action_id,'action':'LINK','hash':digest(a)})
            verified.append({'action_id':action_id,'issue_key':succ,'readback_hash':digest(a)});continue
        fields=deepcopy(a['fields']);parent=a['parent_external_key']
        if parent:fields['parent']={'key':keys[parent]}
        key=a['issue_key']
        desired={k:v for k,v in fields.items() if k!='project'}
        if key:
            # Preserve unrelated labels; proposed content and ownership remain identifiable.
            desired['labels']=sorted(set(a['before'].get('labels',[]))|set(desired['labels']))
            if not matches(jira.get(key)['fields'],desired):
                audit('JIRA_WRITE_ATTEMPT',{'action_id':action_id,'action':'UPDATE','issue_key':key,'payload_hash':digest(desired)})
                jira.update(key,desired)
                audit('JIRA_WRITE_RETURNED',{'action_id':action_id,'action':'UPDATE','issue_key':key})
        else:
            audit('JIRA_WRITE_ATTEMPT',{'action_id':action_id,'action':'CREATE','payload_hash':digest(fields)})
            key=jira.create(fields)
            audit('JIRA_WRITE_RETURNED',{'action_id':action_id,'action':'CREATE','issue_key':key,'label':a['label'],'target':jira.target})
        actual=jira.get(key)['fields']
        if not matches(actual,desired):raise GateError('Jira field readback mismatch; execution halted')
        keys[a['external_key']]=key
        proof=digest(normal(actual));audit('JIRA_READBACK_VERIFIED',{'action_id':action_id,'issue_key':key,'hash':proof})
        verified.append({'action_id':action_id,'issue_key':key,'external_key':a['external_key'],'readback_hash':proof})
    return {'mode':jira.mode,'verified_actions':verified}


class MockJira:
    """In-memory simulator for tests; never reports a live Jira execution."""
    mode='SIMULATED_JIRA'
    project='DEMO'
    target='simulated://jira#DEMO'
    def __init__(self):self.issues={};self.links=set();self.writes=0;self.corrupt=False
    def types(self):return {'Epic':'10000','Task':'10001','Sub-task':'10002'}
    def find(self,label):
        rows=[i for i in self.issues.values() if label in i['fields'].get('labels',[])]
        if len(rows)>1:raise GateError('Duplicate external ID')
        return deepcopy(rows[0]) if rows else None
    def get(self,key):
        result=deepcopy(self.issues[key])
        if self.corrupt:result['fields']['summary']='CORRUPTED READBACK'
        return result
    def create(self,fields):
        self.writes+=1;key=f'DEMO-{len(self.issues)+1}';self.issues[key]={'key':key,'fields':deepcopy(fields)};return key
    def update(self,key,fields):self.writes+=1;self.issues[key]['fields'].update(deepcopy(fields))
    def linked(self,pred,succ):return (pred,succ) in self.links
    def link(self,pred,succ):self.writes+=1;self.links.add((pred,succ))
