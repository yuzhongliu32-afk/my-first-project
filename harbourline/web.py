"""Hosted Harbourline workspace for one team and its invited evaluators."""
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

ROLES = {
    'viewer': set(),
    'runner': {'run'},
    'approver': {'run', 'preview', 'approve', 'reject', 'apply', 'change', 'course_change'},
}


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('HARBOURLINE_WEB_SESSION_KEY'),
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
                if action == 'course_change':
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
a{{color:#184978}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1f5;padding:1rem}}
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

    @app.get('/')
    def index():
        return document('Project overview', '''<h1>Harbourline Community Hub</h1>
<p>MA6094 Group A · Project management workspace</p>
<p>This system uses project evidence to build a work breakdown structure and milestones,
assess risk, and draft reports for two audiences. The integrated workflow shows the
automatic planning-to-reporting handoff and its Critic findings.</p>
<p>An authorised reviewer can review exact Jira actions, approve them and verify
the resulting sandbox records. Each action is recorded in an audit trail.</p>
<p><a href="/workspace">Open the system workspace</a></p>''')

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
