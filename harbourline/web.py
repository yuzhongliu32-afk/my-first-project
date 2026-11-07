"""Hosted Harbourline workspace for one team and its invited evaluators."""
from base64 import b64decode
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import secrets
from threading import Lock
from time import monotonic

from flask import Flask, abort, jsonify, redirect, request, session
from werkzeug.exceptions import HTTPException

from .console import Console, details, json_block, page
from .governance import GateError, GovernanceStore
from .sources import EvidenceLibrary

BUNDLE_FILES = {
    'Harbourline_Brief.pdf', 'Harbourline_Data_Pack.zip', 'verified_source_metadata.json',
    'sponsor_answers_registry.json', 'week12_change.json',
}


def load_host_inputs(bundle_path, inputs):
    if not bundle_path.is_file():
        return
    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    if not isinstance(bundle, dict) or not set(bundle) <= BUNDLE_FILES:
        raise RuntimeError('Unexpected names in the private input bundle')
    files = {name: b64decode(content, validate=True) for name, content in bundle.items()}
    if not {'Harbourline_Brief.pdf', 'Harbourline_Data_Pack.zip'} <= files.keys():
        raise RuntimeError('The private input bundle must include the brief and official Data Pack')
    inputs.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in files.items():
        temp = inputs / ('.' + name + '.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        temp.replace(inputs / name)


ROLES = {
    'viewer': set(),
    'runner': {'run'},
    'approver': {'run', 'preview', 'approve', 'reject', 'apply', 'change', 'course_change', 'jira_check'},
}


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('HARBOURLINE_WEB_SESSION_KEY'),
        INPUT_BUNDLE=Path(os.environ.get('HARBOURLINE_INPUT_BUNDLE', '/etc/secrets/harbourline-inputs.json')),
        WEB_USERS=json.loads(os.environ.get('HARBOURLINE_WEB_USERS', '{}')),
        WORKSPACE=Path(os.environ.get('HARBOURLINE_WORKSPACE', '/var/data/harbourline')),
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
        MAX_CONTENT_LENGTH=8192,
        MAX_FORM_PARTS=16,
    )
    if config:
        app.config.update(config)
    if len(app.secret_key or '') < 32:
        raise RuntimeError('Set a random HARBOURLINE_WEB_SESSION_KEY of at least 32 characters')
    users = app.config['WEB_USERS']
    if not isinstance(users, dict) or not users:
        raise RuntimeError('Configure at least one named web user')
    for name, user in users.items():
        if (not re.fullmatch(r'[a-zA-Z0-9._-]{1,48}', name)
                or user.get('role') not in ROLES
                or not re.fullmatch(r'[0-9a-f]{64}', user.get('key_sha256', ''))):
            raise RuntimeError('Invalid web user configuration')
    approvers = {name for name, user in users.items() if user['role'] == 'approver'}
    root = Path(app.config['WORKSPACE'])
    root.mkdir(parents=True, exist_ok=True)
    load_host_inputs(Path(app.config['INPUT_BUNDLE']), root / 'inputs')
    state_path = root / 'web-state.json'
    lock = Lock()
    jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix='harbourline')
    active = None
    login_attempts = deque()

    @contextmanager
    def workspace(actor):
        store = GovernanceStore(root / 'governance.sqlite', approvers=approvers,
                                 actor_provider=lambda: actor)
        try:
            console = Console(True, root, store=store, inputs=root / 'inputs')
            if state_path.exists():
                console.__dict__.update(json.loads(state_path.read_text()))
            yield console
        finally:
            store.db.close()
            store._lockfile.close()

    def save(console, notice, error=False):
        fields = {k: getattr(console, k) for k in ('run_id', 'batch_id', 'trace', 'change', 'dates')}
        staged = state_path.with_suffix('.tmp')
        staged.write_text(json.dumps({**fields, 'notice': notice, 'error': error}), encoding='utf-8')
        staged.chmod(0o600)
        staged.replace(state_path)

    def error_notice(exc):
        if isinstance(exc, GateError):
            return str(exc)
        return f'Operation failed ({type(exc).__name__}). Review deployment configuration and audit.'

    def perform(actor, fields):
        with workspace(actor) as console:
            try:
                action = fields.get('action')
                if action in ('run', 'preview') and console.batch_id:
                    state = console.store.batch(console.batch_id)['state']
                    if state in ('PENDING', 'APPROVED', 'EXECUTING', 'FAILED_REVIEW_REQUIRED'):
                        raise GateError('Resolve the current Jira batch before generating a new run or preview.')
                if action == 'jira_check':
                    jira = console.jira()
                    types = jira.types()
                    save(console, f'Jira read verified for {jira.project}. '
                         f'{len(set(types.values()))} available work-item types. No writes performed.')
                elif action == 'course_change':
                    path = root / 'inputs/week12_change.json'
                    if not console.run_id or not path.is_file():
                        raise GateError('Run the workflow and configure the official change record first.')
                    event = json.loads(path.read_text())
                    refs = event.get('source_refs', [])
                    if not refs:
                        raise GateError('The official change must cite verified source lines.')
                    lib = EvidenceLibrary(root / 'data/evidence_library.json')
                    _, current = console.store.artifact(console.run_id)
                    if current['source_snapshot_id'] != lib.snapshot:
                        raise GateError('Run the workflow against the current evidence before applying the change.')
                    for ref in refs:
                        lib.verify(ref)
                    console.change = console.store.record_change(console.run_id, {
                        **event, 'hypothetical': False, 'new_source_snapshot_id': lib.snapshot,
                    })
                    save(console, 'Source-linked change recorded. Affected outputs require revalidation.')
                else:
                    save(console, console.act(fields))
            except Exception as exc:
                app.logger.warning('Workflow action %s failed (%s)', fields.get('action'), type(exc).__name__)
                save(console, error_notice(exc), True)

    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    def actor():
        name = session.get('actor')
        if name not in users:
            return None
        if not secrets.compare_digest(session.get('credential_id', ''), users[name]['key_sha256'][:16]):
            return None
        return name

    def verify_csrf():
        if not secrets.compare_digest(request.form.get('token', '').encode(), csrf().encode()):
            abort(403)

    def document(title, contents):
        return f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | Harbourline</title>
<style>
body{{max-width:760px;margin:2rem auto;padding:0 1.1rem;font:17px/1.6 system-ui;color:#14263a}}
input,button{{font:inherit;padding:.45rem .7rem}} label{{display:block;margin:.65rem 0}}
a{{color:#184978}} header{{border-bottom:1px solid #c8d3dd;margin-bottom:1rem}}
nav{{display:flex;gap:.45rem;flex-wrap:wrap}} .tab{{padding:.45rem .75rem;border:1px solid #c8d3dd;border-radius:6px;text-decoration:none}}
.tab[aria-current=page]{{background:#184978;color:white}} .module{{margin-top:1rem}}
details{{border:1px solid #d6e0e9;padding:.65rem .9rem;margin:.45rem 0;border-radius:5px}}
summary{{cursor:pointer;font-weight:600}} summary small{{color:#52667b;margin-left:.6rem;font-weight:400}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1f5;padding:1rem}}
</style><main>{contents}</main></html>'''

    @app.after_request
    def secure(response):
        response.headers.update({
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
        })
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return document(exc.name, f'<h1>{escape(exc.name)}</h1><p><a href="/">Return to Harbourline</a></p>'), exc.code

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    public_lock = Lock()
    public_baseline = None

    def public_results():
        nonlocal public_baseline
        from modules.member_b.adapter import run as plan
        from modules.member_b.data_pack import PACK_SNAPSHOT, load_pack_sources
        from modules.member_b.prepare_sources import prepare_sources
        from .console import ROOT
        from .contracts import validate, verify_evidence

        with public_lock:
            if public_baseline is not None:
                return public_baseline
            inputs = root / 'inputs'
            brief, pack = inputs / 'Harbourline_Brief.pdf', inputs / 'Harbourline_Data_Pack.zip'
            if not brief.is_file() or not pack.is_file():
                return None
            registry, _ = prepare_sources(brief, pack, root=root / 'public-baseline')
            pack_dir = registry.parent / 'Harbourline_Data_Pack'
            payload = json.loads((ROOT / 'examples/request.json').read_text())
            payload.update(recipient='B', operation='PLAN_RISK', source_snapshot_id=PACK_SNAPSHOT)
            result = plan(payload, {
                'source_snapshot_id': PACK_SNAPSHOT, 'source_registry_path': str(registry),
                'data_pack_directory': str(pack_dir),
            })
            validate(result, 'B', expected_producer='B')
            records = json.loads(registry.read_text()) + list(load_pack_sources(pack_dir).values())
            verify_evidence(result, {(r['document_id'], r['version']): r['lines'] for r in records})
            if result['status'] not in ('SUCCESS', 'PARTIAL'):
                return None
            public_baseline = result
            return result

    @app.get('/')
    def index():
        result = public_results()
        modules = {'planning': 'Planning', 'risks': 'Risk register', 'what-if': 'What-if',
                   'reporting': 'Reports', 'jira': 'Jira & approvals'}
        tab = request.args.get('view', 'planning')
        if tab not in modules:
            abort(404)
        query = request.args.get('q', '').strip()[:100]
        nav = ''.join(
            f'<a class="tab" href="/?view={key}"' +
            (' aria-current="page"' if key == tab else '') + f'>{title}</a>'
            for key, title in modules.items()
        )

        def list_items(rows, ident, extra):
            matches = []
            for row in rows:
                title = f"{row[ident]} · {row['title']}"
                if query.casefold() in title.casefold():
                    matches.append(
                        f'<details><summary>{escape(title)} <small>{escape(row["status"])}</small></summary>'
                        f'<p>{escape(extra(row))}</p></details>'
                    )
            return f'<p>{len(matches)} of {len(rows)} items</p>' + (''.join(matches) or '<p>No matching items.</p>')

        content = '<p>Planning results are temporarily unavailable.</p>'
        search = ''
        if result and tab in ('planning', 'risks'):
            search = f'''<form method="get"><input type="hidden" name="view" value="{tab}">
<label>Filter by ID or title <input name="q" value="{escape(query, quote=True)}" maxlength="100"></label>
<button>Search</button> <a href="/?view={tab}">Clear</a></form>'''
            plan = result['planning']
            if tab == 'planning':
                content = '<h3>Work breakdown structure</h3>' + list_items(
                    plan['wbs_items'], 'wbs_id', lambda row: row['dictionary']['work_description'])
                content += '<h3>Milestones</h3>' + list_items(
                    plan['milestones'], 'milestone_id', lambda row: row['relative_timing'])
            else:
                content = list_items(result['risk']['risks'], 'risk_id',
                    lambda row: 'Score: ' + str(row['score'] if row['score'] is not None else 'pending review')
                    + ' · ' + row['description'])
        elif result and tab == 'what-if':
            content = '<p>Compare proposed impacts. These are conditional estimates from the planning model.</p>'
            for case in result['risk']['scenarios']:
                timing, cost = case['schedule_impact_days'], case['cost_impact_sgd']
                impact = f'{timing} days · S${cost:,.0f}' if timing is not None and cost is not None else 'Not quantified'
                content += (
                    f'<details><summary>{escape(case["scenario_id"])} · {impact}</summary>'
                    f'<p>{escape(case["description"])}</p><ul>'
                    + ''.join(f'<li>{escape(item)}</li>' for item in case['assumptions'])
                    + '</ul></details>'
                )
        elif tab == 'reporting':
            content = '<p>Weekly committee update and monthly grant report.</p><p>Live reports are pending. The current OpenAI project is rate-limited.</p>'
        elif tab == 'jira':
            content = '<p>Planning items are previewed before any Jira write. An authorised team member reviews the batch, then the system verifies Jira read-back.</p><p><a href="/workspace">Open team operations</a></p>'

        return document('Public project workspace', f'''<header><p>MA6094 · Group A</p>
<h1>Harbourline Community Hub</h1><p>Project planning and risk workspace</p></header>
<nav aria-label="Project modules">{nav}</nav>
<section class="module"><h2>{modules[tab]}</h2>{search}{content}</section>''')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = ''
        if request.method == 'POST':
            verify_csrf()
            with lock:
                now = monotonic()
                while login_attempts and login_attempts[0] < now - 60:
                    login_attempts.popleft()
                if len(login_attempts) >= 30:
                    abort(429)
                login_attempts.append(now)
            name = request.form.get('name', '').strip()
            candidate = sha256(request.form.get('key', '').encode()).hexdigest()
            user = users.get(name)
            expected = user['key_sha256'] if user else '0' * 64
            if secrets.compare_digest(candidate, expected) and user:
                session.clear()
                session.permanent = True
                session.update(actor=name, credential_id=expected[:16])
                return redirect('/workspace', code=303)
            error = '<p role="alert">The username or access key was incorrect.</p>'
        return document('Sign in', f'''<h1>Open Harbourline</h1>{error}
<p>Use the reviewer or team access details supplied by the group.</p>
<form method="post"><input type="hidden" name="token" value="{csrf()}">
<label>Username <input name="name" autocomplete="username" required></label>
<label>Access key <input type="password" name="key" autocomplete="current-password" required></label>
<button>Sign in</button></form>''')

    @app.post('/logout')
    def logout():
        verify_csrf()
        session.clear()
        return redirect('/', code=303)

    @app.route('/workspace', methods=['GET', 'POST'])
    def dashboard():
        nonlocal active
        name = actor()
        if not name:
            return redirect('/login', code=303)
        role = users[name]['role']
        if request.method == 'POST':
            verify_csrf()
            fields = request.form.to_dict()
            if fields.get('action') not in ROLES[role]:
                abort(403)
            with lock:
                if active and not active.done():
                    abort(409)
                active = jobs.submit(perform, name, fields)
            return redirect('/workspace', code=303)
        with lock:
            busy = active is not None and not active.done()
        toolbar = (f'<p>Signed in as {escape(name)} · {role} · <a href="/evidence">Search evidence</a></p>'
                   f'<form action="/logout" method="post"><input type="hidden" name="token" value="{csrf()}">'
                   '<button>Sign out</button></form>')
        if role == 'approver' and not busy:
            toolbar += (f'<form action="/workspace" method="post"><input type="hidden" name="token" value="{csrf()}">'
                        '<button name="action" value="jira_check">Check Jira connection</button></form>')
        if role == 'approver' and not busy and (root / 'inputs/week12_change.json').is_file():
            toolbar += (f'<form action="/workspace" method="post"><input type="hidden" name="token" value="{csrf()}">'
                        '<button name="action" value="course_change">Review source-linked course change</button></form>')
        with workspace(name) as console:
            response = app.make_response(page(
                console, csrf(),
                'Working on the requested action. This page refreshes automatically.' if busy
                else getattr(console, 'notice', ''),
                False if busy else getattr(console, 'error', False),
                allowed=ROLES[role], toolbar=toolbar, busy=busy,
            ))
        if busy:
            response.headers['Refresh'] = '3'
        return response

    @app.route('/evidence', methods=['GET', 'POST'])
    def evidence():
        name = actor()
        if not name:
            return redirect('/login', code=303)
        output = ''
        if request.method == 'POST':
            verify_csrf()
            query = request.form.get('query', '').strip()
            if not query or len(query) > 300:
                abort(400)
            with workspace(name) as console:
                library = root / 'data/evidence_library.json'
                if not console.run_id or not library.is_file():
                    output = '<p>Complete a project run to prepare the evidence library.</p>'
                else:
                    lib = EvidenceLibrary(library)
                    _, result = console.store.artifact(console.run_id)
                    if result['source_snapshot_id'] != lib.snapshot:
                        abort(409)
                    hits = lib.search(query, cutoff=console.dates['cutoff'])
                    output = details('View matching source lines', json_block(hits)) if hits else '<p>NOT FOUND</p>'
        return document('Search project evidence', f'''<h1>Search project evidence</h1>
<p>Results show exact source lines available as of the current run's evidence cutoff.</p>
<form method="post"><input type="hidden" name="token" value="{csrf()}">
<label>Evidence question <input name="query" maxlength="300" required></label><button>Search</button>
</form>{output}<p><a href="/workspace">Return to workspace</a></p>''')

    @app.get('/download/<kind>')
    def download(kind):
        name = actor()
        if not name:
            abort(403)
        with workspace(name) as console:
            try:
                value = console.export(kind)
            except KeyError:
                abort(404)
        response = jsonify(value)
        response.headers['Content-Disposition'] = f'attachment; filename="harbourline-{kind}.json"'
        return response

    return app
