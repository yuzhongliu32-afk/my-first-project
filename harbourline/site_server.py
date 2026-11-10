"""Local server for the team's "Harbourline | Live Capstone Demo" page (web/site).

Serves the original front end unchanged in layout and implements its API on this repository's
A -> B -> C pipeline:

  GET  /api/status            OpenAI readiness for the page (never returns the key)
  POST /api/runs              run the integrated workflow (X-Demo-Access + Idempotency-Key)
  GET  /api/runs/<key>        recover a pending or finished run

"OpenAI report generation" keeps A's validated rule-based B context; "OpenAI planning + report"
runs B's full agent (Planning -> Risk -> What-if -> code checks -> independent B Critic) before C.
Free mode still runs in the browser. Runs are proposals for human review: no approvals, no Jira
writes. Run:  python -m harbourline.site_server --env-file .env
"""
from __future__ import annotations

import argparse
import hmac
from contextlib import contextmanager
import json
import os
import re
import threading
import time
from copy import deepcopy
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'web/site'
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
         '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.svg': 'image/svg+xml', '.json': 'application/json; charset=utf-8'}
REPORT_TYPES = ('MONTHLY_GRANT', 'WEEKLY_COMMITTEE')
KEY_RE = re.compile(r'^[A-Za-z0-9-]{8,100}$')


def now():
    return datetime.now(timezone.utc).isoformat()


def evidence_key(ref):
    # Same text as the page's keyOf(): JSON.stringify([id, version, page, start, end]).
    return json.dumps([ref['document_id'], ref['document_version'], ref.get('page'),
                       ref['line_start'], ref['line_end']], separators=(',', ':'), ensure_ascii=False)


def source_refs(value):
    if isinstance(value, list):
        for item in value:
            yield from source_refs(item)
    elif isinstance(value, dict):
        if 'document_id' in value and 'source_type' in value:
            yield value
        for item in value.values():
            yield from source_refs(item)


@contextmanager
def governance_store(path):
    """Open the audit database only for the moment it is needed, so the operations CLI
    (preview, human approval, Jira write, readback) can use the same database."""
    from harbourline.governance import GovernanceStore
    store = GovernanceStore(path)
    try:
        yield store
    finally:
        store.db.close(); store._lockfile.close()


def jira_board_url():
    base, key = os.getenv('JIRA_BASE_URL', '').rstrip('/'), os.getenv('JIRA_PROJECT_KEY', '')
    return f'{base}/jira/software/projects/{key}/boards' if base and key else None


class SiteState:
    def __init__(self, library_path: Path, env_file: Path | None, run_dir: Path, db: Path | None = None):
        self.db = Path(db) if db else None
        self.library_path = Path(library_path)
        self.env_file = env_file
        self.env_mtime = None
        self.run_dir = Path(run_dir)
        self.runs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.active: str | None = None
        data = json.loads((SITE / 'data/presentation-data.json').read_text(encoding='utf-8'))
        self.known = set(data['evidence']) | {evidence_key(c) for c in data['corpus']}

    def sync_env(self):
        if not self.env_file:
            return
        from modules.member_b.env_file import load_env_file
        try:
            mtime = Path(self.env_file).stat().st_mtime
        except OSError:
            return
        if mtime != self.env_mtime:
            self.env_mtime = mtime
            load_env_file(self.env_file, override=True)


def evidence_additions(full, library, known):
    """Verified local-library lines the run cites that the exported evidence map lacks."""
    docs = {(d['document_id'], d['version']): d for d in library.documents}
    added = {}
    for ref in source_refs(full):
        key = evidence_key(ref)
        if key in known or key in added:
            continue
        doc = docs.get((ref['document_id'], ref['document_version']))
        if not doc:
            continue
        lines = [{'number': n, 'text': doc['lines'][n - 1]} for n in range(ref['line_start'], ref['line_end'] + 1)]
        added[key] = {'document_id': ref['document_id'], 'version': ref['document_version'],
                      'page': ref.get('page'), 'start': ref['line_start'], 'end': ref['line_end'], 'lines': lines}
    return added


# One access box on the page; each member keeps their own code in .env.
ACCESS_CODES = (('B', 'MEMBER_B_ACCESS_CODE'), ('C', 'MEMBER_C_ACCESS_CODE'))


def billing():
    """Names (never values) of the key each part is billed to."""
    return {'B': 'OPENAI_API_KEY', 'C': 'OPENAI_API_KEY_C' if os.getenv('OPENAI_API_KEY_C') else 'OPENAI_API_KEY'}


def validate_input(body):
    if not isinstance(body, dict):
        raise ValueError('Body must be a JSON object')
    report = body.get('report_type')
    if report not in REPORT_TYPES:
        raise ValueError('report_type must be MONTHLY_GRANT or WEEKLY_COMMITTEE')
    dates = {}
    for k in ('start_date', 'end_date', 'as_of_date'):
        try:
            dates[k] = date.fromisoformat(str(body.get(k)))
        except ValueError:
            raise ValueError(f'{k} must be a date YYYY-MM-DD')
    if dates['start_date'] > dates['end_date']:
        raise ValueError('start_date must not be after end_date')
    rounds = body.get('max_review_rounds', 2)
    if type(rounds) is not int or not 1 <= rounds <= 5:
        raise ValueError('max_review_rounds must be 1-5')
    mode = body.get('planning_mode')
    if mode not in (None, 'live'):
        raise ValueError('planning_mode must be live or omitted')
    weeks, cost = body.get('delay_weeks', 6), body.get('extra_cost_sgd', 600000)
    if type(weeks) not in (int, float) or not 0 <= weeks <= 52:
        raise ValueError('delay_weeks must be a number from 0 to 52')
    if type(cost) not in (int, float) or not 0 <= cost <= 10_000_000:
        raise ValueError('extra_cost_sgd must be a number from 0 to 10,000,000')
    return {'report_type': report, **{k: v.isoformat() for k, v in dates.items()},
            'max_review_rounds': rounds, 'planning_mode': mode, 'delay_weeks': weeks, 'extra_cost_sgd': cost}


def apply_user_whatif(b, weeks, cost):
    """Same rule as the free demo (engine.rebuildPlanning): the asbestos scenario takes the page's
    delay and cost assumptions. The B proposal's own figures are kept in the assumptions."""
    scenarios = b['risk']['scenarios']
    if not scenarios:
        return None
    text = lambda x: (x.get('description', '') + ' ' + ' '.join(x.get('assumptions', []))).lower()
    target = next((x for x in scenarios if x['scenario_id'] == 'SC01'), None)         or next((x for x in scenarios if 'asbestos' in text(x) or 'chrysotile' in text(x)), scenarios[0])
    before = (target.get('schedule_impact_days'), target.get('cost_impact_sgd'))
    days = round(weeks * 7, 1)
    target['description'] = 'Live conditional asbestos-removal sensitivity — user assumptions'
    target['schedule_impact_days'] = int(days) if days == int(days) else days
    target['cost_impact_sgd'] = cost
    target['assumptions'] = [
        f'Presentation input assumes {weeks:g} weeks of delay and S${cost:,.0f} incremental cost; these are user assumptions, not approved facts.',
        f'The B proposal before this input was {before[0] if before[0] is not None else "unknown"} days and '
        f'{"S$" + format(before[1], ",.0f") if before[1] is not None else "unknown cost"}.',
        'One-for-one critical-path propagation and zero recoverable float are assumed; the actual project completion impact is unproven.',
        'The source removal estimate is S$350,000–600,000 and 4–6 weeks. Input outside this range is an illustrative sensitivity, not a revised source estimate.',
        'No variation, baseline, current risk rating or named owner is approved by this run.']
    target['calculation_basis'] = (f'{weeks:g} weeks × 7 = {target["schedule_impact_days"]} calendar days; incremental cost '
                                   f'assumption = S${cost:,.0f}. Conditional sensitivity only; source estimates remain unchanged.')
    target['estimate_status'] = 'QUANTIFIED_ASSUMPTION'
    return target['scenario_id']


def execute_run(state: SiteState, params: dict) -> dict:
    """Run A -> B -> C exactly as operations.run does, shaped as the page's run record."""
    from harbourline.llm import ModelGateway
    from harbourline.pipeline import run_project
    from harbourline.sources import EvidenceLibrary
    from modules.member_b.agent import generate
    lib = EvidenceLibrary(state.library_path)
    base = json.loads((ROOT / 'examples/request.json').read_text(encoding='utf-8'))
    base.update(message_id='REQUEST-' + str(uuid4()), run_id='RUN-' + str(uuid4()), source_snapshot_id=lib.snapshot)
    period = {'start_date': params['start_date'], 'end_date': params['end_date']}
    base['request'].update(instructions='Prepare source-grounded proposals and human-review report drafts.',
                           reporting_period=period, requested_report_type=params['report_type'],
                           max_review_rounds=params['max_review_rounds'])
    ctx = {'source_registry_path': str(ROOT / 'data/brief_source_registry.json')}
    live = params['planning_mode'] == 'live'
    b_trace: dict = {}
    refiner = (lambda b, library, gateway: generate(b, library, gateway, max_rounds=3, trace=b_trace)) if live else None
    adjust = lambda b: apply_user_whatif(b, params['delay_weeks'], params['extra_cost_sgd'])
    c_gateway, b_gateway = ModelGateway(key_env='OPENAI_API_KEY_C'), ModelGateway()
    started = time.monotonic()
    b_status, failure = 'VALIDATED', None
    try:
        full, trace = run_project(base, lib.path, cutoff=params['as_of_date'], plan_mode='live' if live else 'rules',
                                  b_context=ctx, c_gateway=c_gateway, b_gateway=b_gateway,
                                  reporting_periods={params['report_type']: period}, b_refiner=refiner, b_adjust=adjust)
    except Exception as exc:  # B (or A's checks) stopped the handoff: keep a rules record, no reports
        if not live:
            raise
        b_status, failure = 'BLOCKED', f'{type(exc).__name__}: {str(exc)[:600]}'
        base['run_id'] = 'RUN-' + str(uuid4())
        full, trace = run_project(base, lib.path, cutoff=params['as_of_date'], plan_mode='rules',
                                  b_context=ctx, reporting_periods={params['report_type']: period},
                                  include_reports=False, b_adjust=adjust)
        full['errors'].append({'code': 'B_AGENT_BLOCKED', 'message': failure[:500], 'recoverable': True})
    from harbourline.governance import run_incidents
    full['governance']['incidents'] = run_incidents(full['run_id'], full)
    reporting = full['reporting']
    critic_runs = [a for a in b_trace.get('attempts', []) if a.get('stage') == 'Critic']
    last = critic_runs[-1] if critic_runs else {}
    record = {
        'id': 'api-' + full['run_id'][4:16], 'mode': 'live', 'provider': 'openai', 'operation': 'report',
        'full': full, 'trace': trace, 'created_at': now(), 'as_of_date': params['as_of_date'],
        'notice': ('Local server run on this repository\'s A -> B -> C pipeline. Human review and approval '
                   'remain required; nothing was written to Jira.'),
        'api_details': {
            'completed': bool(reporting['reports']) and bool(reporting['critic_reviews']),
            'planning_mode': 'live' if live else 'rules',
            'model': os.getenv('OPENAI_MODEL'),
            'elapsed_seconds': round(time.monotonic() - started, 1),
            'b_metrics': b_gateway.metrics(), 'c_metrics': c_gateway.metrics(),
            'access_holder': params.get('access_holder'), 'billed_key': billing(),
        },
    }
    if live:
        record['api_details']['b_agent'] = {
            'status': b_status,
            'critic': {'verdict': (last.get('result') or 'CRITIC_NONE').replace('CRITIC_', ''),
                       'findings': (last.get('findings') or []) + (b_trace.get('critic_notes') or [])},
            'attempts': [{k: a.get(k) for k in ('round', 'stage', 'try', 'result')} for a in b_trace.get('attempts', [])],
            'auto_flags': b_trace.get('auto_flags', []), 'what_if': b_trace.get('whatif'),
            'error': failure,
        }
    record['evidence_additions'] = evidence_additions(full, lib, state.known)
    state.run_dir.mkdir(parents=True, exist_ok=True)
    if state.db:  # every page run enters the audit chain; Jira writes still need the CLI and a human approval
        try:
            with governance_store(state.db) as store:
                store.save(full, mode='LIVE_MODEL_REQUESTED')
            record['api_details']['governance_db'] = str(state.db.name)
        except Exception as exc:  # the result is still shown; the missing audit save is visible
            record['api_details']['governance_db_error'] = f'{type(exc).__name__}: {str(exc)[:200]}'
    (state.run_dir / f"{record['id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                         encoding='utf-8')
    return record


SNAPSHOT_NOTES = ROOT / 'examples/member_b_presentation_snapshot/change_notes'


def load_notes(state: SiteState):
    """Recorded Week 12 notes (snapshot) plus notes written on this server, newest last."""
    notes = []
    for folder, origin in ((SNAPSHOT_NOTES, 'recorded'), (state.run_dir / 'change_notes', 'local')):
        for f in sorted(folder.glob('*.json')) if folder.is_dir() else []:
            try:
                n = json.loads(f.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                continue
            if isinstance(n, dict) and isinstance(n.get('event'), dict):
                n['origin'] = origin
                notes.append(n)
    return notes


def note_additions(notes, state: SiteState):
    from harbourline.sources import EvidenceLibrary
    lib = EvidenceLibrary(state.library_path)
    added = {}
    for n in notes:
        added.update(evidence_additions(n, lib, state.known | set(added)))
    return added


def write_change_note(state: SiteState, body: dict) -> dict:
    """Week 12 Template B note for CE-01/CE-02 against the planning/risk of the shown run."""
    from harbourline.llm import ModelGateway
    from harbourline.sources import EvidenceLibrary
    from modules.member_b.change_note import change_impact_note
    event_id = body.get('event_id')
    events = {}
    for f in (ROOT / 'examples/change_events').glob('*.json'):
        e = json.loads(f.read_text(encoding='utf-8'))
        events[e['event_id']] = e
    if event_id not in events:
        raise ValueError('event_id must be one of ' + ', '.join(sorted(events)))
    planning, risk = body.get('planning'), body.get('risk')
    if not (isinstance(planning, dict) and isinstance(risk, dict) and planning.get('wbs_items') and risk.get('risks')):
        raise ValueError('planning and risk from the shown run are required')
    e = events[event_id]
    event = {'event_id': e['event_id'], 'change_type': e['change_type'], 'description': e['description']}
    gateway = ModelGateway()
    note = change_impact_note(event, planning, risk, EvidenceLibrary(state.library_path), gateway)
    note['based_on'] = {'source': 'site', 'run_id': body.get('run_id')}
    note['metrics'] = gateway.metrics()
    note['model'] = os.getenv('OPENAI_MODEL')
    folder = state.run_dir / 'change_notes'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{event_id}-{int(time.time())}.json").write_text(json.dumps(note, ensure_ascii=False, indent=1), encoding='utf-8')
    note['origin'] = 'local'
    return note


class Handler(BaseHTTPRequestHandler):
    server_version = 'HarbourlineSite/1.0'
    state: SiteState = None

    def log_message(self, fmt, *args):
        pass

    def send_json(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def error(self, code, err, message):
        self.send_json(code, {'error': {'code': err, 'message': message}})

    def jira_bootstrap(self, previous):
        target = os.getenv('JIRA_BASE_URL', '').rstrip('/') + '#' + os.getenv('JIRA_PROJECT_KEY', '')
        latest = None
        if self.state.db and self.state.db.exists():
            try:
                with governance_store(self.state.db) as store:
                    reads = [e for e in store.audit() if e['event'] == 'JIRA_READ_VERIFIED' and e['detail'].get('target') == target]
                latest = reads[-1] if reads else None
            except Exception:
                latest = None
        s = (latest or {}).get('detail', {}).get('summary', {})
        return {'url': jira_board_url(), 'mode': 'local' if latest else 'not_yet_read',
                'observed_count': s.get('observed_count', 0), 'readback_at': (latest or {}).get('time'),
                'readback_verified': bool(latest), 'new_writes_on_replay': s.get('new_writes_on_replay'),
                'duplicate_external_keys': s.get('duplicate_external_keys'),
                'notice': ('Read back from this team Jira by the local operations tool and logged in the audit chain.'
                           if latest else 'No read-back from this Jira yet. Run the preview, approval, write and read steps.'),
                'previous_site': previous.get('url')}

    def access_holder(self):
        """Which team member's presentation code was typed into the page's single access box."""
        supplied = self.headers.get('X-Demo-Access', '').encode('utf-8')
        holder = None
        for member, name in ACCESS_CODES:
            code = os.getenv(name, '').encode('utf-8')
            if code and hmac.compare_digest(supplied, code):  # compare every code (constant work)
                holder = holder or member
        return holder

    def access_ok(self):
        return self.access_holder() is not None

    def same_origin(self):
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]')
        if host not in ('127.0.0.1', 'localhost', '::1'):
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin.split('://', 1)[-1] == self.headers.get('Host')

    # -------------------------------------------------------------- GET
    def do_GET(self):
        self.state.sync_env()
        path = self.path.split('?', 1)[0]
        if path == '/api/status':
            ready = bool(os.getenv('OPENAI_API_KEY') and os.getenv('OPENAI_MODEL'))
            code = any(os.getenv(name) for _, name in ACCESS_CODES)
            self.send_json(200, {
                'configured': ready and code, 'model': os.getenv('OPENAI_MODEL') if ready else None,
                'remaining_calls': None, 'max_review_rounds': 2, 'planning_modes': ['rules', 'live'],
                'live_b_overhead_calls': 3,
                'message': ('Local server ready.' if ready and code else
                            'Set OPENAI_API_KEY, OPENAI_MODEL and MEMBER_B_ACCESS_CODE in .env '
                            '(set_openai_key.bat). Free mode remains available.')})
            return
        if path == '/api/local-runs':
            files = sorted(self.state.run_dir.glob('api-*.json'), key=lambda f: f.stat().st_mtime)[-8:]
            runs = []
            for f in files:
                try:
                    runs.append(json.loads(f.read_text(encoding='utf-8')))
                except (ValueError, OSError):
                    continue
            if self.state.db and self.state.db.exists():
                try:  # show the current approvals, Jira writes, readbacks and incidents for each run
                    with governance_store(self.state.db) as store:
                        for run in runs:
                            try:
                                run['full']['governance'] = store.export(run['full']['run_id'])['governance']
                            except Exception:
                                continue
                except Exception:
                    pass
            self.send_json(200, {'runs': runs})
            return
        if path == '/api/change-notes':
            notes = load_notes(self.state)
            self.send_json(200, {'notes': notes, 'evidence_additions': note_additions(notes, self.state)})
            return
        if path.startswith('/api/runs/'):
            if not self.access_ok():
                self.error(403, 'ACCESS_REQUIRED', 'Enter the presentation access code.')
                return
            key = path.rsplit('/', 1)[-1]
            entry = self.state.runs.get(key)
            if not entry:
                self.error(404, 'NOT_FOUND', 'No run with this request key on this server.')
            elif entry['status'] == 'RUNNING':
                self.send_json(202, {'status': 'RUNNING'})
            else:
                self.send_json(200, {k: v for k, v in entry.items() if k != 'fingerprint'})
            return
        if path == '/data/presentation-data.json' and jira_board_url():
            # Point the page at this team's own Jira. Evidence and corpus (the hashed parts) are untouched.
            data = json.loads((SITE / 'data/presentation-data.json').read_text(encoding='utf-8'))
            data['bootstrap']['jira'] = self.jira_bootstrap(data['bootstrap'].get('jira') or {})
            self.send_json(200, data)
            return
        file = (SITE / ('index.html' if path in ('/', '') else path.lstrip('/'))).resolve()
        if SITE.resolve() not in file.parents and file != SITE.resolve() / 'index.html' or not file.is_file():
            self.error(404, 'NOT_FOUND', 'Unknown path')
            return
        data = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', TYPES.get(file.suffix, 'application/octet-stream'))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -------------------------------------------------------------- POST
    def do_POST(self):
        self.state.sync_env()
        if self.path == '/api/change-note':
            self.post_change_note()
            return
        if self.path != '/api/runs':
            self.error(404, 'NOT_FOUND', 'Unknown path')
            return
        if not self.same_origin():
            self.error(403, 'ORIGIN_REJECTED', 'Open the page from this local server.')
            return
        if not (os.getenv('OPENAI_API_KEY') and os.getenv('OPENAI_MODEL')):
            self.error(503, 'API_NOT_CONFIGURED', 'OPENAI_API_KEY and OPENAI_MODEL are not set on the server.')
            return
        if not self.access_ok():
            time.sleep(1)
            self.error(403, 'ACCESS_REQUIRED', 'Wrong or missing presentation access code.')
            return
        key = self.headers.get('Idempotency-Key', '')
        if not KEY_RE.match(key):
            self.error(400, 'IDEMPOTENCY_REQUIRED', 'A request key is required.')
            return
        length = int(self.headers.get('Content-Length', '-1'))
        if not 0 <= length <= 64 * 1024:
            self.error(413, 'BODY_TOO_LARGE', 'Request body too large.')
            return
        try:
            params = validate_input(json.loads(self.rfile.read(length)))
            params['access_holder'] = self.access_holder()
        except (ValueError, json.JSONDecodeError) as exc:
            self.error(400, 'INVALID_INPUT', str(exc))
            return
        fingerprint = json.dumps(params, sort_keys=True)
        with self.state.lock:
            existing = self.state.runs.get(key)
            if existing:
                if existing['fingerprint'] != fingerprint:
                    self.error(409, 'INVALID_SETTINGS', 'This request key was used with different inputs.')
                elif existing['status'] == 'RUNNING':
                    self.send_json(202, {'status': 'RUNNING'})
                else:
                    self.send_json(200, {k: v for k, v in existing.items() if k != 'fingerprint'})
                return
            if self.state.active:
                self.error(409, 'RUN_IN_PROGRESS', 'Another run is in progress on this server.')
                return
            self.state.active = key
            self.state.runs[key] = {'status': 'RUNNING', 'fingerprint': fingerprint}
        try:
            record = execute_run(self.state, params)
            result = {'status': 'COMPLETE', 'run': record, 'fingerprint': fingerprint}
            code = 200
        except Exception as exc:
            result = {'status': 'FAILED', 'fingerprint': fingerprint,
                      'error': {'code': 'RUN_FAILED', 'message': f'{type(exc).__name__}: {str(exc)[:400]}'}}
            code = 502
        finally:
            with self.state.lock:
                self.state.active = None
        self.state.runs[key] = result
        self.send_json(code, {k: v for k, v in result.items() if k != 'fingerprint'})


def _post_change_note(self):
    if not self.same_origin():
        self.error(403, 'ORIGIN_REJECTED', 'Open the page from this local server.'); return
    if not (os.getenv('OPENAI_API_KEY') and os.getenv('OPENAI_MODEL')):
        self.error(503, 'API_NOT_CONFIGURED', 'OPENAI_API_KEY and OPENAI_MODEL are not set on the server.'); return
    if not self.access_ok():
        time.sleep(1); self.error(403, 'ACCESS_REQUIRED', 'Wrong or missing presentation access code.'); return
    length = int(self.headers.get('Content-Length', '-1'))
    if not 0 <= length <= 8 * 1024 * 1024:
        self.error(413, 'BODY_TOO_LARGE', 'Request body too large.'); return
    with self.state.lock:
        if self.state.active:
            self.error(409, 'RUN_IN_PROGRESS', 'Another run is in progress on this server.'); return
        self.state.active = 'change-note'
    try:
        note = write_change_note(self.state, json.loads(self.rfile.read(length)))
        self.send_json(200, {'note': note, 'evidence_additions': note_additions([note], self.state)})
    except (ValueError, json.JSONDecodeError) as exc:
        self.error(400, 'INVALID_INPUT', str(exc)[:600])
    except Exception as exc:
        self.error(502, 'NOTE_FAILED', f'{type(exc).__name__}: {str(exc)[:400]}')
    finally:
        with self.state.lock:
            self.state.active = None


Handler.post_change_note = _post_change_note


def main():
    from modules.member_b.env_file import load_env_file
    p = argparse.ArgumentParser(description='Serve the Harbourline demo page on the local A-B-C pipeline')
    p.add_argument('--port', type=int, default=8080)
    p.add_argument('--library', type=Path, default=ROOT / 'data/evidence_library.json')
    p.add_argument('--env-file', type=Path)
    p.add_argument('--runs', type=Path, default=ROOT / '.local/site_runs')
    p.add_argument('--db', type=Path, default=ROOT / '.local/governance_mine.sqlite',
                   help='Audit database shared with harbourline.operations (preview/approve/jira-apply/jira-read)')
    a = p.parse_args()
    if a.env_file:
        print(json.dumps({'env_file_loaded': load_env_file(a.env_file, override=True)}))
    Handler.state = SiteState(a.library, a.env_file, a.runs, a.db)
    server = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print(f'Harbourline site: http://127.0.0.1:{a.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
