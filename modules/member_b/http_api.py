"""Local-only B HTTP service and browser workbench. Live mode calls OpenAI.

Not a public endpoint: binds loopback and does not provide authentication.

Run:  python -m modules.member_b.http_api --env-file .env
Open: http://127.0.0.1:8765/          (the Member B workbench page)

GET  /health
GET  /v1/status                 readiness: key/model set, evidence library, saved B output
POST /v1/configure              {api_key?, model?, forget_key?}  page input; memory only
GET  /v1/b-output?source=live|rules   saved B output (+ what-if computation trace)
POST /v1/generate-baseline      {cutoff?, model?}  live Planning -> Risk -> What-if -> checks -> Critic
POST /v1/generate-offline       {}  deterministic rules preview, no key, not AI
POST /v1/whatif-recompute       {elements:[{label,kind,optimistic,most_likely,pessimistic,on_critical_path}]}
                                user what-if assumptions, P50/P80 computed in code, no AI
POST /v1/change-note            {change_event, source?}  Week 12 Template B change impact note
POST /v1/change-impact-live     {change_event, cutoff?, model?}  AI impact review + rules mapping
POST /v1/plan-risk              {request, context, mode: "live"|"rules", model?}
POST /v1/change-impact          {event, planning, risk}
POST /v1/schedule-forecast      {request?, context?, scenario?, change_event?, model?, cutoff?}

Nothing here approves a change or writes to Jira. A key entered on the local page is held in
this process's memory only (never written to disk or logged) and cross-origin calls are refused.
"""
import argparse
import hmac
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .adapter import run, forecast
from .change import analyse_change, ALIASES

MAX_BODY = 5 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]
PAGE = Path(__file__).with_name('change_event_form.html')
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "connect-src 'self'; form-action 'self'; base-uri 'none'")


def _default_gateway(model):
    from harbourline.llm import ModelGateway
    return ModelGateway(model=model)


def _default_library(path):
    from harbourline.sources import EvidenceLibrary
    return EvidenceLibrary(path)


class MemberBHTTPHandler(BaseHTTPRequestHandler):
    server_version = 'HarbourlineMemberB/4.0'
    # Overridable for tests; production uses the repository paths and OpenAI.
    saved_output_path = ROOT / '.local/member_b_live_output.json'
    library_path = ROOT / 'data/evidence_library.json'
    request_path = ROOT / 'examples/member_b_pack_request.json'
    change_events_dir = ROOT / 'examples/change_events'
    # Presentation snapshot: a recorded real AI run replayed without API calls. Committable
    # (no keys): B output, what-if trace, change notes and run metadata.
    snapshot_dir = ROOT / 'examples/member_b_presentation_snapshot'
    gateway_factory = staticmethod(_default_gateway)
    library_factory = staticmethod(_default_library)
    env_file_path = None   # set by main() from --env-file; re-read whenever the file is saved
    _env_mtime = None
    # Presentation mode: MEMBER_B_ACCESS_CODE in .env makes every AI action require the code,
    # so presenters type a password, never the key. MEMBER_B_AI_RUN_LIMIT caps AI runs per start.
    _runs_used = 0
    _runs_lock = threading.Lock()
    PROTECTED = {'/v1/unlock', '/v1/configure', '/v1/snapshot-save', '/v1/plan-risk', '/v1/schedule-forecast',
                 '/v1/generate-baseline', '/v1/change-note', '/v1/change-impact-live'}

    @staticmethod
    def _run_limit():
        try:
            return int(os.getenv('MEMBER_B_AI_RUN_LIMIT', '')) or None
        except ValueError:
            return None

    def _access_ok(self):
        code = os.getenv('MEMBER_B_ACCESS_CODE')
        if not code:
            return True
        supplied = self.headers.get('X-Access-Code', '')
        return hmac.compare_digest(supplied.encode('utf-8'), code.encode('utf-8'))

    @classmethod
    def sync_env_file(cls):
        """Reload .env after the user saves it, so no server restart is needed."""
        if not cls.env_file_path:
            return
        from .env_file import load_env_file
        try:
            mtime = Path(cls.env_file_path).stat().st_mtime
        except OSError:
            return
        if mtime != cls._env_mtime:
            cls._env_mtime = mtime
            load_env_file(cls.env_file_path, override=True)  # values only, never logged

    def log_message(self, format, *args):
        pass  # never log request bodies, which can contain source material

    def send(self, code, payload):
        content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # ---- helpers -------------------------------------------------------
    def _model(self, body):
        return body.get('model') or os.getenv('OPENAI_MODEL')

    def _live_missing(self, body):
        """Return a 503 payload if the backend has no key/model, else None."""
        missing = [n for n, ok in (('OPENAI_API_KEY', os.getenv('OPENAI_API_KEY')),
                                   ('OPENAI_MODEL', self._model(body))) if not ok]
        if missing:
            return {'error': 'LIVE_MODEL_NOT_CONFIGURED', 'missing': missing,
                    'message': 'Enter your OpenAI API key and model in step 0 of the page, or start '
                               'the server with --env-file .env.'}
        return None

    def _path(self, kind):
        """Files next to the saved live output: live, trace (what-if detail), rules preview."""
        live = Path(self.saved_output_path)
        snap = Path(self.snapshot_dir)
        return {'live': live, 'trace': live.with_name('member_b_live_trace.json'),
                'rules': live.with_name('member_b_rules_output.json'),
                'snapshot': snap / 'b_output.json', 'snapshot_trace': snap / 'trace.json',
                'snapshot_meta': snap / 'meta.json'}[kind]

    def _notes_dir(self, source):
        return (Path(self.snapshot_dir) / 'change_notes' if source == 'snapshot'
                else Path(self.saved_output_path).parent)

    def _change_notes(self, source):
        folder = self._notes_dir(source)
        pattern = '*.json' if source == 'snapshot' else 'member_b_change_note_*.json'
        notes = []
        for f in sorted(folder.glob(pattern)) if folder.is_dir() else []:
            try:
                n = json.loads(f.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                continue
            if isinstance(n, dict) and isinstance(n.get('event'), dict):
                notes.append(n)
        return notes

    @staticmethod
    def _read(path):
        path = Path(path)
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None

    @staticmethod
    def _write(path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def _load_saved(self, source='live'):
        return self._read(self._path(source))

    def _example_events(self):
        events = []
        folder = Path(self.change_events_dir)
        for file in sorted(folder.glob('*.json')) if folder.is_dir() else []:
            try:
                e = json.loads(file.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                continue
            if isinstance(e, dict) and e.get('event_id') and e.get('change_type'):
                events.append({k: e.get(k) for k in ('event_id', 'change_type', 'issued', 'description')})
        return events

    @staticmethod
    def _labels(saved):
        planning, risk = saved.get('planning') or {}, saved.get('risk') or {}
        return {'wbs': {x['wbs_id']: x.get('title') for x in planning.get('wbs_items', [])},
                'milestones': {x['milestone_id']: x.get('title') for x in planning.get('milestones', [])},
                'risks': {x['risk_id']: x.get('title') for x in risk.get('risks', [])}}

    # ---- GET -----------------------------------------------------------
    def do_GET(self):
        self.sync_env_file()
        path = self.path.split('?', 1)[0]
        if path == '/health':
            self.send(200, {'service': 'member-b', 'status': 'ok', 'modes': ['rules', 'live']})
        elif path in ('/', '/change-event'):
            data = PAGE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == '/v1/status':
            self.send(200, self._status())
        elif path == '/v1/b-output':
            query = self.path.split('?', 1)[1] if '?' in self.path else ''
            source = ('rules' if 'source=rules' in query else
                      'snapshot' if 'source=snapshot' in query else 'live')
            try:
                saved = self._load_saved(source)
            except ValueError:
                self.send(422, {'error': 'INVALID_SAVED_OUTPUT', 'message': f'Saved {source} output is not valid JSON'})
                return
            if saved is None:
                self.send(404, {'error': 'B_OUTPUT_NOT_FOUND', 'source': source,
                                'message': 'Generate it first (step 1).'})
                return
            trace = (self._read(self._path('trace')) if source == 'live' else
                     self._read(self._path('snapshot_trace')) if source == 'snapshot' else None)
            meta = self._read(self._path('snapshot_meta')) if source == 'snapshot' else None
            recorded = ''
            if meta:
                recorded = (f" (recorded {str(meta.get('saved_at', ''))[:16].replace('T', ' ')} UTC, "
                            f"model {meta.get('model') or 'unknown'}, {meta.get('api_calls', '?')} API calls)")
            note = {'live': 'AI-generated proposal for human review',
                    'rules': 'Offline preview from fixed rules, NOT the AI agent; '
                             'its what-if figures are rule constants, not computed ranges',
                    'snapshot': 'Recorded AI run replayed for the presentation: no API call is made now'
                                + recorded}
            self.send(200, {'source': source, 'output': saved, 'trace': trace, 'meta': meta,
                            'change_notes': [n['event']['event_id'] for n in self._change_notes(source)]
                                            if source != 'rules' else [],
                            'mode_note': note[source]})
        elif path == '/v1/change-notes':
            source = 'snapshot' if 'source=snapshot' in self.path else 'live'
            self.send(200, {'source': source, 'notes': self._change_notes(source)})
        else:
            self.send(404, {'error': 'unknown path'})

    def _info(self, source):
        path = self._path(source)
        try:
            saved = self._read(path)
        except ValueError:
            return {'error': f'Saved {source} output is not valid JSON'}
        if saved is None:
            return None
        return {'status': saved.get('status'), 'run_id': saved.get('run_id'),
                'saved_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                'wbs_items': len((saved.get('planning') or {}).get('wbs_items', [])),
                'milestones': len((saved.get('planning') or {}).get('milestones', [])),
                'risks': len((saved.get('risk') or {}).get('risks', [])),
                'scenarios': len((saved.get('risk') or {}).get('scenarios', [])),
                'sponsor_questions': len((saved.get('planning') or {}).get('sponsor_questions', []))}

    def _status(self):
        return {'service': 'member-b',
                'api_key_configured': bool(os.getenv('OPENAI_API_KEY')),  # never the value
                'model': os.getenv('OPENAI_MODEL') or None,
                'evidence_library': Path(self.library_path).is_file(),
                'saved_b_output': self._info('live'),
                'saved_rules_output': self._info('rules'),
                'saved_snapshot': self._read(self._path('snapshot_meta')),
                'example_change_events': self._example_events(),
                'change_type_aliases': ALIASES,
                'access_code_required': bool(os.getenv('MEMBER_B_ACCESS_CODE')),
                'ai_run_limit': self._run_limit(),
                'ai_runs_remaining': (None if self._run_limit() is None
                                      else max(0, self._run_limit() - type(self)._runs_used))}

    # ---- POST ----------------------------------------------------------
    def _same_origin(self):
        """Block cross-site and DNS-rebinding calls to this unauthenticated local server."""
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]')
        if host not in ('127.0.0.1', 'localhost', '::1'):
            return False
        origin = self.headers.get('Origin')
        if origin is None:
            return True  # non-browser clients (tests, CLI, A's http_client)
        return origin.split('://', 1)[-1] == self.headers.get('Host')

    def _configure(self, body):
        """Accept the user's own key from the local page.

        Held in this process's memory; with save_to_env it is also written to the local,
        git-ignored .env so it survives a restart. It is never returned, logged or uploaded.
        """
        from .env_file import set_values
        key = body.get('api_key')
        model = body.get('model')
        values = {}
        if key is not None:
            key = key.strip().strip('"\'') if isinstance(key, str) else key
            if not isinstance(key, str) or not 20 <= len(key) <= 400 or any(c.isspace() for c in key):
                raise ValueError('api_key does not look like an API key')
            os.environ['OPENAI_API_KEY'] = values['OPENAI_API_KEY'] = key
        if model is not None:
            if not isinstance(model, str) or not 1 <= len(model.strip()) <= 100:
                raise ValueError('model must be a model ID')
            os.environ['OPENAI_MODEL'] = values['OPENAI_MODEL'] = model.strip()
        if body.get('forget_key') is True:
            os.environ.pop('OPENAI_API_KEY', None)
            values['OPENAI_API_KEY'] = ''
        saved = False
        if body.get('save_to_env') is True and values:
            path = Path(type(self).env_file_path or ROOT / '.env')
            if path.name != '.env':
                raise ValueError('Only a file named .env (git-ignored) can hold the key')
            set_values(path, values)
            type(self).env_file_path, type(self)._env_mtime = path, path.stat().st_mtime
            saved = True
        return {'status': 'CONFIGURED', 'api_key_configured': bool(os.getenv('OPENAI_API_KEY')),
                'model': os.getenv('OPENAI_MODEL') or None, 'saved_to_env': saved,
                'note': ('Saved to the local, git-ignored .env and to server memory.' if saved else
                         'Held in local server memory only; cleared when the server stops.')}

    def do_POST(self):
        self.sync_env_file()
        if not self._same_origin():
            self.send(403, {'error': 'FORBIDDEN_ORIGIN',
                            'message': 'Open the page from http://127.0.0.1:<port>/'})
            return
        routes = {'/v1/configure': self._configure,'/v1/plan-risk': self._plan_risk, '/v1/change-impact': self._change_impact,
                  '/v1/schedule-forecast': self._schedule_forecast,
                  '/v1/generate-baseline': self._generate_baseline,
                  '/v1/generate-offline': self._generate_offline,
                  '/v1/whatif-recompute': self._whatif_recompute,
                  '/v1/change-note': self._change_note,
                  '/v1/change-impact-live': self._change_impact_live,
                  '/v1/unlock': lambda body: {'status': 'UNLOCKED'},
                  '/v1/snapshot-save': self._snapshot_save}
        handler = routes.get(self.path)
        if handler is None:
            self.send(404, {'error': 'unknown path'})
            return
        if self.path in self.PROTECTED and not self._access_ok():
            time.sleep(1)  # slow down guessing
            self.send(403, {'error': 'ACCESS_CODE_REQUIRED',
                            'message': 'Enter the presentation access code in step 0.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '-1'))
            if length < 0 or length > MAX_BODY:
                self.send(413, {'error': 'invalid body length'})
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Body must be JSON object')
            result = handler(body)
            if result is None:
                return  # handler already responded
            self.send(200 if result.get('status') not in ('BLOCKED', 'FAILED') else 422, result)
        except FileNotFoundError as exc:
            self.send(422, {'error': 'FILE_NOT_FOUND', 'message': str(exc)[:280]})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.send(400, {'error': type(exc).__name__, 'message': str(exc)[:1200]})
        except Exception as exc:
            # Surface the provider's error type and a short message (never the key) so the
            # page can say why, e.g. AuthenticationError or NotFoundError for a bad model ID.
            self.send(502, {'error': 'LIVE_AGENT_FAILED', 'type': type(exc).__name__,
                            'message': (str(exc) or 'Generation or validation failed')[:280]
                            + ' — no rules output was substituted.'})

    def _require_live(self, body):
        missing = self._live_missing(body)
        if missing:
            self.send(503, missing)
            return False
        limit = self._run_limit()
        with type(self)._runs_lock:
            if limit is not None and type(self)._runs_used >= limit:
                self.send(429, {'error': 'AI_RUN_LIMIT_REACHED',
                                'message': f'All {limit} AI runs for this session are used. Saved results '
                                           'and the offline preview still work; restart the server to reset.'})
                return False
            type(self)._runs_used += 1
        return True

    def _require_library(self):
        if not Path(self.library_path).is_file():
            self.send(422, {'error': 'EVIDENCE_LIBRARY_NOT_FOUND',
                            'message': 'Build it once: python scripts/prepare_evidence.py --brief '
                                       '"<brief.pdf>" --pack "<Harbourline_Data_Pack.zip>"'})
            return False
        return True

    def _plan_risk(self, body):
        context = body.get('context', {}).copy()
        context['mode'] = body.get('mode', 'rules')
        if context['mode'] == 'live' and not self._require_live(body):
            return None
        if body.get('model'):
            context['model'] = body['model']
        if body.get('cutoff'):
            context['cutoff'] = body['cutoff']
        return run(body['request'], context)

    def _change_impact(self, body):
        return analyse_change(body['event'], body['planning'], body['risk'])

    def _generate_baseline(self, body):
        """Run the live Planning/Risk agent from the evidence library and save its output."""
        from .agent import generate
        if not self._require_live(body) or not self._require_library():
            return None
        library = self.library_factory(self.library_path)
        request = json.loads(Path(self.request_path).read_text(encoding='utf-8'))
        request['run_id'] = 'B-LIVE-' + str(uuid4())
        request['source_snapshot_id'] = library.snapshot
        gateway = self.gateway_factory(self._model(body))
        trace = {'run_id': request['run_id'], 'started_at': datetime.now(timezone.utc).isoformat()}
        try:
            # Up to 3 attempts so mechanical-check and Critic findings can be corrected.
            output = generate(request, library, gateway, cutoff=body.get('cutoff') or None,
                              max_rounds=3, trace=trace)
        except ValueError:
            trace['result'] = 'FAILED'
            trace['metrics'] = gateway.metrics() if hasattr(gateway, 'metrics') else None
            self._write(self._path('trace'), trace)  # keep findings for diagnosis
            raise
        trace['result'] = 'PASSED'
        self._write(self._path('live'), output)
        self._write(self._path('trace'), trace)
        return {'status': output['status'], 'run_id': output['run_id'],
                'wbs_items': len(output['planning']['wbs_items']),
                'milestones': len(output['planning']['milestones']),
                'risks': len(output['risk']['risks']),
                'scenarios': len(output['risk']['scenarios']),
                'sponsor_questions': len(output['planning'].get('sponsor_questions', [])),
                'attempts': trace.get('attempts'),
                'metrics': output.get('metrics'),
                'note': 'Proposed plan for human review; not approved, nothing written to Jira.'}

    def _whatif_recompute(self, body):
        """User what-if: the person's own three-point assumptions, arithmetic in code, no AI call."""
        from .whatif import COST, SCHEDULE, pert, simulate
        elements = body.get('elements')
        if not isinstance(elements, list) or not 1 <= len(elements) <= 30:
            raise ValueError('elements must be a list of 1-30 items')
        clean = []
        for i, e in enumerate(elements, start=1):
            if not isinstance(e, dict) or e.get('kind') not in (COST, SCHEDULE):
                raise ValueError(f'Element {i}: kind must be COST or SCHEDULE')
            try:
                o, m, p = (float(e[k]) for k in ('optimistic', 'most_likely', 'pessimistic'))
            except (KeyError, TypeError, ValueError):
                raise ValueError(f'Element {i}: optimistic, most likely and pessimistic must be numbers')
            if not 0 <= o <= m <= p or p > (20_000 if e['kind'] == COST else 260):
                raise ValueError(f'Element {i}: needs 0 <= O <= M <= P within a plausible range')
            mean, sigma = pert(o, m, p)
            clean.append({'label': str(e.get('label') or f'Element {i}')[:120], 'kind': e['kind'],
                          'optimistic': o, 'most_likely': m, 'pessimistic': p,
                          'on_critical_path': bool(e.get('on_critical_path')),
                          'pert_mean': round(mean, 2), 'sigma': round(sigma, 2)})
        return {'status': 'USER_ASSUMPTION', 'elements': clean,
                'cost_sgd_k': simulate([e for e in clean if e['kind'] == COST]),
                'schedule_weeks': simulate([e for e in clean if e['kind'] == SCHEDULE and e['on_critical_path']]),
                'note': 'Your assumptions, computed in code (10,000 PERT-beta draws). Not sourced '
                        'and not approved; the agent output is unchanged.'}

    def _snapshot_save(self, body):
        """Freeze the current real AI run (plan, risk, what-if, change notes) for a no-API demo."""
        import shutil
        live = self._load_saved('live')
        if live is None:
            self.send(422, {'error': 'B_OUTPUT_NOT_FOUND',
                            'message': 'Run Generate with AI first; a snapshot only records a real AI run.'})
            return None
        snap = Path(self.snapshot_dir)
        notes_dir = snap / 'change_notes'
        if notes_dir.is_dir():
            shutil.rmtree(notes_dir)
        notes_dir.mkdir(parents=True, exist_ok=True)
        self._write(self._path('snapshot'), live)
        trace = self._read(self._path('trace'))
        if trace is not None:
            self._write(self._path('snapshot_trace'), trace)
        elif self._path('snapshot_trace').is_file():
            self._path('snapshot_trace').unlink()
        notes = [n for n in self._change_notes('live')
                 if (n.get('based_on') or {}).get('run_id') == live.get('run_id')]
        for n in notes:
            safe = ''.join(c for c in n['event']['event_id'] if c.isalnum() or c in '-_') or 'event'
            self._write(notes_dir / f'{safe}.json', n)
        metrics = live.get('metrics') or {}
        meta = {'saved_at': datetime.now(timezone.utc).isoformat(), 'run_id': live.get('run_id'),
                'model': os.getenv('OPENAI_MODEL') or None,
                'source_snapshot_id': live.get('source_snapshot_id'),
                'api_calls': metrics.get('api_calls'), 'input_tokens': metrics.get('input_tokens'),
                'output_tokens': metrics.get('output_tokens'),
                'elapsed_seconds': metrics.get('elapsed_seconds'),
                'change_notes': [n['event']['event_id'] for n in notes],
                'note': 'Recorded real AI run for the presentation. Replaying it makes no API call. '
                        'Proposal for human review; nothing approved or written to Jira.'}
        self._write(self._path('snapshot_meta'), meta)
        return {'status': 'SAVED', **meta}

    def _generate_offline(self, body):
        """Offline preview from the deterministic rules generator: no key, no AI."""
        request = json.loads(Path(self.request_path).read_text(encoding='utf-8'))
        output = run(request, {'mode': 'rules'})
        self._write(self._path('rules'), output)
        return {'status': output['status'], 'source': 'rules',
                'wbs_items': len(output['planning']['wbs_items']),
                'risks': len(output['risk']['risks']),
                'note': 'Offline rules preview, not the AI agent. Use it to test the page without a key.'}

    def _change_note(self, body):
        """Week 12 Template B change impact note against the saved B output."""
        from .change_note import change_impact_note
        event = body.get('change_event')
        if not isinstance(event, dict):
            raise ValueError('change_event must be an object')
        event = {'event_id': str(event.get('event_id', '')).strip()[:80],
                 'change_type': str(event.get('change_type', '')).strip()[:80],
                 'description': str(event.get('description', '')).strip()[:4000],
                 'hypothetical': event.get('hypothetical') is True}
        if not event['event_id'] or not event['change_type'] or not event['description']:
            raise ValueError('event_id, change_type and description are required')
        source = body.get('source') if body.get('source') in ('rules', 'snapshot') else 'live'
        if not self._require_live(body) or not self._require_library():
            return None
        saved = self._load_saved(source)
        if saved is None:
            self.send(422, {'error': 'B_OUTPUT_NOT_FOUND',
                            'message': 'Generate the B plan & risks first (step 1).'})
            return None
        gateway = self.gateway_factory(self._model(body))
        note = change_impact_note(event, saved['planning'], saved['risk'],
                                  self.library_factory(self.library_path), gateway,
                                  cutoff=body.get('cutoff') or None)
        note['based_on'] = {'source': source, 'run_id': saved.get('run_id')}
        note['labels'] = self._labels(saved)
        note['metrics'] = gateway.metrics() if hasattr(gateway, 'metrics') else None
        safe = ''.join(c for c in event['event_id'] if c.isalnum() or c in '-_') or 'event'
        self._write(self._path('live').with_name(f'member_b_change_note_{safe}.json'), note)
        return note

    def _saved_or_422(self):
        saved = self._load_saved()
        if saved is None:
            self.send(422, {'error': 'B_OUTPUT_NOT_FOUND',
                            'message': 'Click "Generate B plan & risks with AI" first (or run '
                                       'python -m modules.member_b.live_demo --env-file .env).'})
        return saved

    def _change_impact_live(self, body):
        """Model-driven impact review of a user-entered change against the saved B output."""
        from .change_live import analyse_change_live
        event = body.get('change_event')
        if not isinstance(event, dict):
            raise ValueError('change_event must be an object')
        event = {'event_id': str(event.get('event_id', '')).strip(),
                 'change_type': str(event.get('change_type', '')).strip(),
                 'description': str(event.get('description', '')).strip()[:2000],
                 'hypothetical': event.get('hypothetical') is True}
        if not event['event_id'] or not event['change_type'] or not event['description']:
            raise ValueError('event_id, change_type and description are required')
        if not self._require_live(body) or not self._require_library():
            return None
        saved = self._saved_or_422()
        if saved is None:
            return None
        planning, risk = saved['planning'], saved['risk']
        gateway = self.gateway_factory(self._model(body))
        ai = analyse_change_live(event, planning, risk, self.library_factory(self.library_path),
                                 gateway, cutoff=body.get('cutoff') or None)
        rules = analyse_change(event, planning, risk)
        metrics = gateway.metrics() if hasattr(gateway, 'metrics') else None
        return {'status': 'REVIEW_REQUIRED', 'event': event, 'ai': ai, 'rules': rules,
                'labels': self._labels(saved), 'metrics': metrics, 'approved': False,
                'note': 'AI proposal for human review; no change approved, nothing written to Jira.'}

    def _schedule_forecast(self, body):
        if not self._require_live(body):
            return None
        context = body.get('context', {}).copy()
        if body.get('model'):
            context['model'] = body['model']
        if body.get('cutoff'):
            context['cutoff'] = body['cutoff']
        request = body.get('request')
        if request is None:
            # The browser page reuses the saved B output; it never sends a filesystem
            # path or a public URL.
            request = self._saved_or_422()
            if request is None:
                return None
        context.setdefault('planning', request.get('planning'))
        context.setdefault('risk', request.get('risk'))
        return forecast(request, context, scenario=body.get('scenario'),
                        change_event=body.get('change_event'))


def main():
    from .env_file import load_env_file
    parser = argparse.ArgumentParser(description='Local Member B HTTP server and workbench page')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--env-file', type=Path,
                        help='Local .env with OPENAI_API_KEY/OPENAI_MODEL; never commit it')
    args = parser.parse_args()
    if args.host not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('Do not expose an unauthenticated LLM endpoint to the internet')
    if args.env_file:
        if not args.env_file.is_file():
            parser.error(f'Env file not found: {args.env_file}')
        print(json.dumps({'env_file_loaded': load_env_file(args.env_file)}))  # names only
        MemberBHTTPHandler.env_file_path = args.env_file
        MemberBHTTPHandler._env_mtime = args.env_file.stat().st_mtime
    try:
        server = ThreadingHTTPServer((args.host, args.port), MemberBHTTPHandler)
    except OSError:
        parser.error(f'Port {args.port} is already in use: Member B may already be running. Open '
                     f'http://{args.host}:{args.port}/ or close the other window first.')
    print(f'Member B workbench: http://{args.host}:{args.port}/')
    if not os.getenv('OPENAI_API_KEY') or not os.getenv('OPENAI_MODEL'):
        print('OPENAI_API_KEY / OPENAI_MODEL not set yet: run set_openai_key.bat (or enter them in '
              'step 0 of the page). A saved .env is picked up without restarting.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
