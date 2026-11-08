"""Member B entrypoint: backward compatible A contract, explicit live opt-in."""
from copy import deepcopy
import json
from pathlib import Path
from .planning_risk import run_real


def run(request: dict, context: dict) -> dict:
    mode=context.get('mode','rules')
    if mode not in ('rules','live'):
        raise ValueError('Unknown B mode; choose rules or live')
    if mode=='live':
        # A invokes the original adapter in rules mode and subsequently calls
        # agent.refine() when --plan-mode live. Standalone callers may use this
        # explicit mode to skip the entire deterministic planning stage.
        import os
        from .agent import generate
        from harbourline.llm import ModelGateway
        from harbourline.sources import EvidenceLibrary
        library=EvidenceLibrary(context.get('evidence_library_path') or
                                Path(__file__).resolve().parents[2] / 'data/evidence_library.json')
        model=context.get('model') or os.environ.get('OPENAI_MODEL')
        if not model or not os.environ.get('OPENAI_API_KEY'):
            raise ValueError('Set OPENAI_MODEL and OPENAI_API_KEY for live Member B')
        if request['source_snapshot_id'] not in (library.snapshot, library.bundle['b_source_mode']):
            raise ValueError('Requested source snapshot differs from the evidence library')
        return generate(request, library, ModelGateway(model=model),
                        cutoff=context.get('cutoff'),
                        max_rounds=request['request'].get('max_review_rounds',2))
    if request['source_snapshot_id'].startswith('FIXTURE-'):
        root=Path(__file__).resolve().parents[2]
        output=json.loads((root / 'examples/b_output.json').read_text())
        for field in ('run_id','project_id','source_snapshot_id','request'):
            output[field]=deepcopy(request[field])
        return output
    return run_real(request,context)
