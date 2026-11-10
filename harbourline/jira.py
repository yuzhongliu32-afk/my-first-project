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
        except HTTPError as e:
            route = path.split('?', 1)[0]
            if route.startswith('/issue/createmeta/'):
                operation = 'read project work-item metadata'
            elif route == '/search/jql':
                operation = 'search for existing work items'
            elif route == '/myself':
                operation = 'verify sandbox account'
            elif route == '/issueLink':
                operation = 'link dependencies'
            else:
                operation = 'access work item'
            raise GateError(f'Jira HTTP {e.code} while attempting to {operation}.') from None
        except URLError:raise GateError('Jira network failure; reconcile any uncertain remote write before retry') from None

    def types(self):
        found={};token=None
        self.request('GET', '/myself')
        for _ in range(10):
            args={'maxResults':100}
            if token:args['startAt']=token
            data=self.request('GET',f'/issue/createmeta/{quote(self.project)}/issuetypes?'+urlencode(args))
            for row in data.get('issueTypes', data.get('values', [])):
                found[row['name']] = str(row['id'])
                if row.get('untranslatedName'):
                    found[row['untranslatedName']] = str(row['id'])
                if row.get('subtask') and row.get('untranslatedName') == 'Subtask':
                    found.setdefault('Sub-task', str(row['id']))
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

    def search_label(self,label):
        """Read-only: every work item in the project carrying a label (paginated JQL search)."""
        if not re.fullmatch(r'[a-z0-9-]{3,40}',label):raise GateError('Invalid label')
        rows=[];token=None
        for _ in range(20):
            body={'jql':f'project = "{self.project}" AND labels = "{label}" ORDER BY key',
                  'fields':['summary','labels','issuetype'],'maxResults':100}
            if token:body['nextPageToken']=token
            data=self.request('POST','/search/jql',body)
            rows.extend(data.get('issues',[]))
            token=data.get('nextPageToken')
            if data.get('isLast',True) or not token:return rows
        raise GateError('Board readback pagination limit')

    def create(self,fields):return self.request('POST','/issue',{'fields':fields})['key']
    def update(self,key,fields):self.request('PUT','/issue/'+key,{'fields':fields})
    def link(self,predecessor,successor,link_type='Blocks'):
        self.request('POST','/issueLink',{'type':{'name':link_type},'inwardIssue':{'key':predecessor},'outwardIssue':{'key':successor}})
    def linked(self,predecessor,successor,link_type='Blocks'):
        for link in self.get(predecessor)['fields'].get('issuelinks',[]):
            kind=link.get('type',{})
            if link_type=='Blocks':
                if kind.get('outward','').lower()=='blocks' and link.get('outwardIssue',{}).get('key')==successor:return True
            elif kind.get('name','').lower()==link_type.lower() and successor in (
                    link.get('outwardIssue',{}).get('key'),link.get('inwardIssue',{}).get('key')):return True
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


def risk_description(r,external):
    score=('Unrated (the sources do not establish probability and impact)' if r.get('score') is None
           else f"{r['probability']} x {r['impact']} = {r['score']}")
    sources='; '.join(f"{x['document_id']} L{x['line_start']}" for x in r.get('source_refs',[])[:8]) or 'none'
    return '\n'.join([
        f'PROPOSED risk for human review - external ID {external}',
        f"Status: {r.get('status')}",
        f'Score (probability x impact): {score}',
        f"Owner: {r.get('owner') or 'not named in the sources'}",
        f"Trigger: {r.get('trigger') or 'not stated'}",
        f"Response plan: {r.get('response_plan') or 'not stated'}",
        f"Description: {r.get('description','')}",
        f"Related WBS: {', '.join(r.get('related_wbs_ids',[])) or 'none'}",
        f"Related milestones: {', '.join(r.get('related_milestone_ids',[])) or 'none'}",
        f'Sources: {sources}',
        'Agent-created; ratings and owners are proposals. Closing or resolving is a human act.'])


def plan_actions(full,jira):
    if full.get('change',{}).get('stale_artifacts') or any(r['is_stale'] for r in full['reporting']['reports']):raise GateError('Stale project outputs block Jira preview')
    types=jira.types();actions=[];lookup={};project=jira.project
    level_names={1:os.getenv('JIRA_TYPE_LEVEL1','Epic'),2:os.getenv('JIRA_TYPE_LEVEL2','Task'),3:os.getenv('JIRA_TYPE_LEVEL3','Sub-task')}
    def add(external,title,description,type_name,parent=None,date=None,wbs_id=None,milestone_id=None,
            extra_labels=(),risk_id=None):
        if type_name not in types:raise GateError(f'Jira issue type unavailable: {type_name}; configure explicit type mapping')
        fields={'project':{'key':project},'summary':title,'description':adf(description),
                'issuetype':{'id':types[type_name]},
                'labels':[marker(external),'harbourline-proposed','ai-generated',*extra_labels]}
        if date:fields['duedate']=date
        existing=jira.find(marker(external));key=existing['key'] if existing else None
        parent_key=lookup.get(parent,{}).get('issue_key') if parent else None
        if parent_key:fields['parent']={'key':parent_key}
        before=normal(jira.get(key)['fields']) if key else None
        action={'external_key':external,'label':marker(external),'action':'UPDATE' if key else 'CREATE',
                'issue_key':key,'fields':fields,'parent_external_key':parent,'before':before,
                'wbs_id':wbs_id,'milestone_id':milestone_id}
        if risk_id:action['risk_id']=risk_id
        actions.append(action);lookup[external]=action
    work=sorted(full['planning']['wbs_items'],key=lambda w:(w['level'],w['wbs_id']))
    for w in work:
        external=f"{project}:WBS:{w['wbs_id']}";parent=f"{project}:WBS:{w['parent_wbs_id']}" if w['parent_wbs_id'] else None
        add(external,w['title'],f"PROPOSED — external ID {external}\n"+json.dumps(w['dictionary'],ensure_ascii=False),level_names[w['level']],parent,wbs_id=w['wbs_id'])
    for m in full['planning']['milestones']:
        external=f"{project}:MILESTONE:{m['milestone_id']}"
        add(external,m['title'],f"PROPOSED milestone — external ID {external}\nRelative timing: {m['relative_timing']}; linked WBS: {m['related_wbs_ids']}",os.getenv('JIRA_TYPE_MILESTONE','Task'),date=m['calendar_date'],milestone_id=m['milestone_id'])
    # Risk register (Member B): one work item per risk, stable external key RISK:<id>, so a re-run
    # (e.g. after re-scoring) updates the same item. Linked with "Relates" to the work it threatens.
    risk_type=os.getenv('JIRA_TYPE_RISK','Task');relates=os.getenv('JIRA_RISK_LINK_TYPE','Relates')
    risk_links=[]
    for r in full.get('risk',{}).get('risks',[]):
        external=f"{project}:RISK:{r['risk_id']}"
        add(external,f"[Risk {r['risk_id']}] {r['title']}",risk_description(r,external),risk_type,
            extra_labels=('harbourline-risk',),risk_id=r['risk_id'])
        for wbs in r.get('related_wbs_ids',[]):
            if f'{project}:WBS:{wbs}' in lookup:
                risk_links.append({'action':'LINK','link_type':relates,'predecessor':external,'successor':f'{project}:WBS:{wbs}'})
        for mid in r.get('related_milestone_ids',[]):
            if f'{project}:MILESTONE:{mid}' in lookup:
                risk_links.append({'action':'LINK','link_type':relates,'predecessor':external,'successor':f'{project}:MILESTONE:{mid}'})
    for w in work:
        for pred in w['predecessor_wbs_ids']:
            actions.append({'action':'LINK','predecessor':f'{project}:WBS:{pred}','successor':f"{project}:WBS:{w['wbs_id']}"})
    for m in full['planning']['milestones']:
        for pred in m['predecessor_milestone_ids']:
            actions.append({'action':'LINK','predecessor':f'{project}:MILESTONE:{pred}','successor':f"{project}:MILESTONE:{m['milestone_id']}"})
    actions.extend(risk_links)
    return {'target':jira.target,'transport':jira.mode,'actions':actions}


def read_board(full,jira):
    """Read-only board readback: compare every planned item and link with Jira. Never writes.

    IN_SYNC / DIFFERS / MISSING for planned items, LINKED / NOT_LINKED / PENDING for links, and
    NOT_IN_PLAN for agent-created items the current plan no longer contains (reported for a
    human to decide; the agent never deletes or closes them).
    """
    payload=plan_actions(full,jira)  # reads only: issue types, label search, current fields
    items=[];keys={}
    for a in payload['actions']:
        if a['action']=='LINK':continue
        keys[a['external_key']]=a['issue_key']
        row={'external_key':a['external_key'],'issue_key':a['issue_key'],'wbs_id':a.get('wbs_id'),
             'milestone_id':a.get('milestone_id'),'risk_id':a.get('risk_id'),'summary':a['fields']['summary']}
        if not a['issue_key']:
            row['status']='MISSING'
        else:
            before=a['before'] or {};desired=normal({k:v for k,v in a['fields'].items() if k!='project'})
            diffs=[k for k in ('summary','description','issuetype','duedate') if k in desired and before.get(k)!=desired[k]]
            if not set(desired.get('labels',[]))<=set(before.get('labels',[])):diffs.append('labels')
            row['status']='DIFFERS' if diffs else 'IN_SYNC'
            row['differs']=diffs
        items.append(row)
    links=[]
    for a in payload['actions']:
        if a['action']!='LINK':continue
        pred,succ=keys.get(a['predecessor']),keys.get(a['successor']);kind=a.get('link_type','Blocks')
        status='PENDING' if not (pred and succ) else ('LINKED' if jira.linked(pred,succ,kind) else 'NOT_LINKED')
        links.append({'type':kind,'from':a['predecessor'],'to':a['successor'],'status':status})
    planned={a['label'] for a in payload['actions'] if a['action']!='LINK'}
    agent_items=jira.search_label('ai-generated')
    extra=[{'issue_key':i['key'],'summary':i['fields'].get('summary')}
           for i in agent_items
           if not planned & set(i['fields'].get('labels',[])) and 'harbourline-proposed' in i['fields'].get('labels',[])]
    # Idempotency evidence: one Jira item per stable external label, and nothing new on a replay.
    per_label={}
    for i in agent_items:
        for label in set(i['fields'].get('labels',[]))&planned:per_label[label]=per_label.get(label,0)+1
    duplicates=sum(1 for n in per_label.values() if n>1)
    replay_creates=sum(1 for a in payload['actions'] if a['action']=='CREATE')
    count=lambda rows,s:sum(1 for r in rows if r['status']==s)
    summary={'planned_items':len(items),'in_sync':count(items,'IN_SYNC'),'differs':count(items,'DIFFERS'),
             'missing':count(items,'MISSING'),'links_linked':count(links,'LINKED'),
             'links_not_linked':count(links,'NOT_LINKED'),'links_pending':count(links,'PENDING'),
             'not_in_plan':len(extra),'risks':sum(1 for r in items if r['risk_id']),
             'observed_count':sum(1 for r in items if r['issue_key']),'duplicate_external_keys':duplicates,
             'new_writes_on_replay':replay_creates}
    return {'target':jira.target,'transport':jira.mode,'read_only':True,'summary':summary,
            'items':items,'links':links,'not_in_plan':extra}


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
            kind=a.get('link_type','Blocks')
            if not jira.linked(pred,succ,kind):
                audit('JIRA_WRITE_ATTEMPT',{'action_id':action_id,'action':'LINK','link_type':kind,'predecessor':pred,'successor':succ})
                jira.link(pred,succ,kind)
                audit('JIRA_WRITE_RETURNED',{'action_id':action_id,'action':'LINK','link_type':kind})
            if not jira.linked(pred,succ,kind):raise GateError('Jira link readback differs')
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
    def search_label(self,label):
        return [deepcopy(i) for i in self.issues.values() if label in i['fields'].get('labels',[])]
    def linked(self,pred,succ,link_type='Blocks'):return (pred,succ,link_type) in self.links
    def link(self,pred,succ,link_type='Blocks'):self.writes+=1;self.links.add((pred,succ,link_type))
