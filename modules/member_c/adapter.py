"""A-compatible C entrypoint; fixture calls remain explicitly marked."""
from copy import deepcopy
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4
from harbourline.contracts import validate
from harbourline.sources import EvidenceLibrary
from harbourline.llm import ModelGateway

ROOT=Path(__file__).resolve().parents[2]


def run(request:dict,context:dict)->dict:
    if request['source_snapshot_id'].startswith('FIXTURE-'):
        out=json.loads((ROOT/'examples/c_output.json').read_text())
        for key in ('run_id','project_id','source_snapshot_id','request'):out[key]=deepcopy(request[key])
        for report in out['reporting']['reports']:report['source_snapshot_id']=request['source_snapshot_id']
        count=len(context.get('planning',{}).get('wbs_items',[]))
        out['memory']['open_questions'].append(f'Fixture context received {count} proposed WBS items; no model report generated.')
        return out
    from .service import empty_memory,memory_query,generate_reports
    started=monotonic();gateway=context.get('model_gateway') or ModelGateway()
    out={k:deepcopy(request[k]) for k in ('schema_version','run_id','project_id','source_snapshot_id','request')}
    out.update(message_id='C-'+str(uuid4()),producer='C',recipient='A',operation=request['operation'],status='BLOCKED',source_evidence=[],
        memory=empty_memory(),reporting={'reports':[],'critic_reviews':[]},metrics={'api_calls':0,'input_tokens':None,'output_tokens':None,'estimated_cost_usd':None,'elapsed_seconds':None},errors=[])
    try:
        if request['producer']!='A' or request['recipient']!='C':raise ValueError('Expected A to C request')
        lib=EvidenceLibrary(context.get('evidence_library',ROOT/'data/evidence_library.json'))
        lib.semantic_path=context.get('semantic_index')
        if lib.snapshot!=request['source_snapshot_id'] or context.get('source_snapshot_id')!=lib.snapshot:raise ValueError('Source snapshot mismatch')
        if request['operation']=='MEMORY_QUERY':
            question=request['request']['question']
            if not question:raise ValueError('Memory question missing')
            out['memory']=memory_query(question,lib,gateway,context.get('as_of_date'))
            out['status']='SUCCESS' if out['memory']['answer_status']=='SUPPORTED' else 'PARTIAL'
        elif request['operation']=='GENERATE_REPORTS':
            out['memory'],out['reporting']=generate_reports(request,context,lib,gateway)
            out['status']='PARTIAL' if all(r['status']=='READY_FOR_HUMAN_REVIEW' for r in out['reporting']['reports']) else 'BLOCKED'
        else:raise ValueError('Unsupported C operation')
        from harbourline.contracts import _walk
        refs={json.dumps(v,sort_keys=True):v for v in _walk({'memory':out['memory'],'reporting':out['reporting']}) if 'document_id'in v and 'source_type'in v}
        out['source_evidence']=list(refs.values())
        for ref in out['source_evidence']:lib.verify(ref,context.get('as_of_date'))
    except Exception as exc:
        # Do not echo SDK exception bodies (which may include user data or auth).
        reason = f'{type(exc).__name__}: missing configuration, invalid evidence or invalid model output; inspect the local validation trace.'
        if getattr(exc, 'code', None) == 'insufficient_quota':
            reason = 'OpenAI quota is unavailable or exhausted. Check the project usage and plan.'
        elif type(exc).__name__ == 'RateLimitError':
            reason = 'OpenAI rejected the request with HTTP 429.'
            code = getattr(exc, 'code', None)
            if code in ('rate_limit_exceeded', 'requests', 'tokens'):
                reason += f' Limit: {code}.'
            response = getattr(exc, 'response', None)
            retry_after = response.headers.get('Retry-After', '') if response is not None else ''
            if retry_after.isdigit() and len(retry_after) < 8:
                reason += f' Provider retry delay: {retry_after} seconds.'
        out['status']='BLOCKED';out['errors'].append({'code':'C_MODULE_BLOCKED','message':reason,'recoverable':True})
    out['metrics']={**gateway.metrics(),'elapsed_seconds':monotonic()-started}
    validate(out,'C',expected_producer='C')
    return out
