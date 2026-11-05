"""Actual module integration; mappings require verified evidence, not relabelled data."""
from copy import deepcopy
from time import monotonic
from .contracts import validate,verify_evidence,common_projection,_walk
from .integration import empty_backend,aggregate
from .sources import EvidenceLibrary,digest
from .llm import ModelGateway
from uuid import uuid4
from datetime import datetime,timezone


def run_project(common,library_path,*,cutoff,plan_mode='rules',b_context=None,c_gateway=None,b_gateway=None,semantic_index=None,reporting_periods=None):
    from modules.member_b.adapter import run as b_run
    from modules.member_c.adapter import run as c_run
    started=monotonic();lib=EvidenceLibrary(library_path);request=deepcopy(common)
    validate(request,'Common',expected_producer='A')
    if request['source_snapshot_id']!=lib.snapshot:raise ValueError('Requested snapshot differs from evidence content')
    if plan_mode not in ('rules','live'):raise ValueError('Unknown planning mode')
    trace=[]
    def record(event,value):
        trace.append({'trace_id':str(uuid4()),'occurred_at':datetime.now(timezone.utc).isoformat(),'event':event,
                      'run_id':request['run_id'],'source_snapshot_id':lib.snapshot,'sha256':digest(value)})
    legacy=lib.bundle['b_source_mode']
    req_b={**deepcopy(request),'recipient':'B','operation':'PLAN_RISK','source_snapshot_id':legacy}
    ctx={'source_snapshot_id':legacy,**(b_context or {})}
    if ctx['source_snapshot_id']!=legacy:raise ValueError('B legacy source mode mismatch')
    b=b_run(req_b,ctx)
    validate(b,'B',expected_producer='B')
    if b['status'] not in ('SUCCESS','PARTIAL'):raise ValueError('B cannot run: authoritative sources unavailable')
    if b['request']!=req_b['request'] or b['run_id']!=request['run_id'] or b['project_id']!=request['project_id'] or b['source_snapshot_id']!=legacy:
        raise ValueError('B response metadata mismatch')
    verify_evidence(b,lib.line_registry())
    for ref in _walk(b):
        if 'document_id'in ref and 'source_type'in ref:lib.verify(ref)
    # B supports named source modes; attach the content-addressed ID only after verification.
    b['source_snapshot_id']=lib.snapshot
    record('B_SOURCE_MODE_VERIFIED_AND_MAPPED',{'legacy':legacy,'canonical':lib.snapshot})
    if plan_mode=='live':
        from modules.member_b.agent import refine
        b=refine(b,lib,b_gateway or ModelGateway())
    record('B_OUTPUT_VALIDATED',b)
    req_c={**deepcopy(request),'recipient':'C','operation':'GENERATE_REPORTS'}
    context={'source_snapshot_id':lib.snapshot,'evidence_library':str(lib.path),'as_of_date':cutoff,
             'planning':deepcopy(b['planning']),'risk':deepcopy(b['risk']),'b_source_evidence':deepcopy(b['source_evidence'])}
    if reporting_periods:context['reporting_periods']=deepcopy(reporting_periods)
    if semantic_index:context['semantic_index']=str(semantic_index)
    if c_gateway:context['model_gateway']=c_gateway
    record('AUTOMATIC_B_TO_C_HANDOFF',{'planning':b['planning'],'risk':b['risk']})
    c=c_run(req_c,context)
    validate(c,'C',expected_producer='C');verify_evidence(c,lib.line_registry())
    for ref in _walk(c):
        if 'document_id'in ref and 'source_type'in ref:lib.verify(ref,cutoff)
    record('C_WRITER_CRITIC_OUTPUT_VALIDATED',c)
    a=empty_backend(request);a['integration']['handoff_completed']=True
    a['integration']['handoff_trace_ids']=[r['trace_id'] for r in trace]
    full=aggregate(a,b,c);full['metrics']['elapsed_seconds']=monotonic()-started
    validate(full,'Full',expected_producer='A')
    return full,trace
