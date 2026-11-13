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
from .contracts import ContractError
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
    'approver': {'run', 'plan', 'preview', 'approve', 'reject', 'apply', 'change', 'course_change', 'jira_check'},
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
        if isinstance(exc, ContractError):
            detail = str(exc)
            schema_error = re.fullmatch(
                r'(Common|B|C|Full) schema violation at /([A-Za-z0-9_/]{0,160}): ([A-Za-z]+)', detail
            )
            if schema_error:
                return 'Output validation failed. ' + detail
            # Dynamic IDs are appended after a colon. Keep them out of the UI and logs.
            reason = detail.partition(':')[0]
            if re.fullmatch(r'[A-Za-z0-9 _/;*().-]{1,160}', reason):
                return 'Output validation failed. ' + reason
            return 'Output validation failed. The generated result did not meet the project contract.'
        if isinstance(exc, RuntimeError):
            detail = str(exc)
            if re.fullmatch(r'(?:OpenRouter|Gemini) request failed \(HTTP [1-5][0-9]{2}\)', detail):
                return detail + '. Check the configured model, access and quota.'
            if detail in (
                'OpenRouter request timed out or could not connect',
                'Gemini request timed out or could not connect',
            ):
                return detail + '.'
        return f'Operation failed ({type(exc).__name__}). Review deployment configuration and audit.'

    def perform(actor, fields):
        with workspace(actor) as console:
            try:
                action = fields.get('action')
                if action in ('run', 'plan', 'preview') and console.batch_id:
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
                notice = error_notice(exc)
                log_detail = type(exc).__name__ if isinstance(exc, GateError) else notice
                app.logger.warning('Workflow action %s failed: %s', action, log_detail)
                save(console, notice, True)

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
body{{max-width:980px;margin:2rem auto;padding:0 1.1rem;font:16px/1.6 system-ui;color:#14263a;background:#f2f6f5}}
header,.module{{background:white;padding:1.25rem;border-radius:12px;border:1px solid #d6e2df}}
header h1{{margin:.1rem 0}} header p{{margin:.2rem 0 .7rem}}
.actions,.stats{{display:flex;gap:.7rem;flex-wrap:wrap}} .stats{{margin:1rem 0}}
.stats div{{background:white;border:1px solid #d6e2df;border-radius:8px;padding:.55rem .9rem;min-width:115px}}
.stats strong,.stats span{{display:block}} .stats strong{{font-size:1.5rem;color:#175d52}}
.result{{padding:.6rem 1rem;background:#e5f4ed;border-left:4px solid #247365}}
dt{{font-weight:650}} dd{{margin:0 0 .4rem}} button{{background:#175d52;color:white;border:0;border-radius:6px;cursor:pointer}}
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

    def public_results(*, regenerate=False):
        nonlocal public_baseline
        from modules.member_b.adapter import run as plan
        from modules.member_b.data_pack import PACK_SNAPSHOT, load_pack_sources
        from modules.member_b.prepare_sources import prepare_sources
        from .console import ROOT
        from .contracts import validate, verify_evidence

        with public_lock:
            if public_baseline is not None and not regenerate:
                return public_baseline
            inputs = root / 'inputs'
            brief, pack = inputs / 'Harbourline_Brief.pdf', inputs / 'Harbourline_Data_Pack.zip'
            if not brief.is_file() or not pack.is_file():
                return None
            baseline_root = root / 'public-baseline'
            registry = baseline_root / 'data/brief_source_registry.json'
            if public_baseline is None:
                registry, _ = prepare_sources(brief, pack, root=baseline_root)
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

    public_statuses = ('Not started', 'In progress', 'Needs review', 'Done')

    @app.post('/public/work-item')
    def update_public_work_item():
        verify_csrf()
        result = public_results()
        item_id = request.form.get('item_id', '')
        status = request.form.get('status', '')
        note = request.form.get('note', '').strip()
        if (not result or status not in public_statuses or len(note.encode()) > 100
                or not any(row['wbs_id'] == item_id for row in result['planning']['wbs_items'])):
            abort(400)
        updates = dict(session.get('public_updates', {}))
        updates[item_id] = {'status': status, 'note': note}
        session['public_updates'] = updates
        return redirect('/?view=board', code=303)

    @app.get('/')
    def index():
        regenerate = request.args.get('run') == '1'
        result = public_results(regenerate=regenerate)
        modules = {'board': 'Manage work', 'planning': 'Planning', 'risks': 'Risk register', 'what-if': 'What-if',
                   'reporting': 'Reports', 'jira': 'Jira & approvals'}
        tab = request.args.get('view', 'board')
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
        if result and tab == 'board':
            updates = session.get('public_updates', {})
            content = '<p>Update work status and add short notes. This browser keeps your changes. The official baseline and Jira are separate.</p>'
            csrf_token = csrf()
            for row in result['planning']['wbs_items']:
                item_id = row['wbs_id']
                saved = updates.get(item_id, {})
                status = saved.get('status', 'Not started')
                note = escape(saved.get('note', ''), quote=True)
                options = ''.join(f'<option' + (' selected' if status == item else '') + f'>{item}</option>'
                                  for item in public_statuses)
                content += f'''<details><summary>{escape(item_id)} · {escape(row['title'])} <small>{status}</small></summary>
<form method="post" action="/public/work-item">
<input type="hidden" name="token" value="{csrf_token}">
<input type="hidden" name="item_id" value="{escape(item_id, quote=True)}">
<label>Status <select name="status">{options}</select></label>
<label>Note <input name="note" maxlength="100" value="{note}"></label>
<button>Save update</button></form></details>'''
        elif result and tab in ('planning', 'risks'):
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
            from modules.member_b.change import analyse_change
            choices = {'LIFT_DELAY': 'Lift supplier delay', 'CHILDCARE_CHANGE': 'Childcare handover change',
                       'GRANT_CHANGE': 'Grant conditions change', 'ACCESS_CHANGE': 'Accessibility requirements change',
                       'ASBESTOS_CONFIRMED': 'Asbestos remediation'}
            scenario_ids = {'ASBESTOS_CONFIRMED': 'SC01', 'LIFT_DELAY': 'SC02', 'CHILDCARE_CHANGE': 'SC03'}
            scenarios = {case['scenario_id']: case for case in result['risk']['scenarios']}
            selected = request.args.get('event', '')
            options = ''.join(f'<option value="{key}"' + (' selected' if selected == key else '')
                              + f'>{title}</option>' for key, title in choices.items())
            content = f'''<p>Choose a hypothetical change to calculate which work, milestones and risks need review.</p>
<form method="get"><input type="hidden" name="view" value="what-if">
<label>Change scenario <select name="event">{options}</select></label>
<button>Calculate impact</button></form>'''
            content += '<div class="actions">' + ''.join(
                f'<a class="tab" href="/?view=what-if&amp;event={key}">{label}</a>'
                for key, label in choices.items()
            ) + '</div>'
            if selected in choices:
                impact = analyse_change({'event_id': 'PUBLIC-WHATIF', 'change_type': selected, 'hypothetical': True},
                                        result['planning'], result['risk'])
                groups = (('Work items', 'stale_wbs_ids'), ('Milestones', 'stale_milestone_ids'),
                          ('Risks', 'stale_risk_ids'), ('Reports to review', 'stale_reports'))
                content += '<div class="result"><h3>Impact · ' + choices[selected] + '</h3><dl>'
                content += ''.join(f'<dt>{label}</dt><dd>{escape(", ".join(impact[key]) or "None identified")}</dd>'
                                   for label, key in groups)
                case = scenarios.get(scenario_ids.get(selected))
                timing = case['schedule_impact_days'] if case else None
                cost = case['cost_impact_sgd'] if case else None
                assumptions = case['assumptions'] if case else []
                schedule_text = f'{timing} calendar days' if timing is not None else 'Not quantified'
                cost_text = f'S${cost:,.0f}' if cost is not None else 'Not quantified'
                assumptions_html = ('<ul>' + ''.join(f'<li>{escape(item)}</li>' for item in assumptions)
                                    + '</ul>') if assumptions else 'No estimate assumptions are recorded for this change.'
                content += (
                    f'<dt>Schedule Impact</dt><dd>{schedule_text}</dd>'
                    f'<dt>Cost Impact</dt><dd>{cost_text}</dd>'
                    f'<dt>Stated Assumptions</dt><dd>{assumptions_html}</dd>'
                )
                if case:
                    content += f'<dt>Calculation basis</dt><dd>{escape(case["calculation_basis"])}</dd>'
                content += '</dl><p>Hypothetical analysis. The project baseline remains a proposal.</p></div>'
            content += '<h3>Existing schedule and cost estimates</h3>'
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
            content = '<p>Weekly committee update and monthly grant report.</p><p>Live reports are generated from the operator workspace.</p>'
        elif tab == 'jira':
            content = '<p>Planning items are previewed before any Jira write. An authorised team member reviews the batch, then the system verifies Jira read-back.</p>'

        counts = ''
        if result:
            plan, risks = result['planning'], result['risk']['risks']
            counts = '<div class="stats">' + ''.join(
                f'<div><strong>{count}</strong><span>{name}</span></div>'
                for count, name in ((len(plan['wbs_items']), 'Work items'),
                                    (len(plan['milestones']), 'Milestones'), (len(risks), 'Risks'))
            ) + '</div>'
        banner = '<p class="result" role="status">Planning run completed using the official Data Pack.</p>' if regenerate and result else ''
        return document('Public project workspace', f'''<header><p>MA6094 · Group A</p>
<h1>Harbourline Community Hub</h1><p>Manage work, run the planning model, or assess a change.</p>
<form method="get" class="actions"><button name="run" value="1">Run planning &amp; risk</button>
<a class="tab" href="/?view=what-if&amp;event=ASBESTOS_CONFIRMED">Analyse a change</a></form></header>
{banner}{counts}
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


    review_url = 'https://harbourline-individual-review.liuy0306.chatgpt.site/'
    review_jobs = {}
    review_starts = deque()

    def project_fields(item, names):
        return {name: item[name] for name in names.split() if name in item}

    def review_references(item, field):
        return [project_fields(ref, 'document_id page line_start line_end')
                for ref in item.get(field, [])]

    def review_result(full):
        plan, risk, reporting = full['planning'], full['risk'], full['reporting']
        return {
            **project_fields(full, 'run_id status'),
            'wbs': [project_fields(row, 'wbs_id title level parent_wbs_id status')
                    for row in plan['wbs_items']],
            'milestones': [project_fields(row, 'milestone_id title calendar_date status')
                           for row in plan['milestones']],
            'risks': [project_fields(row, 'risk_id title status score')
                      for row in risk['risks']],
            'reports': [
                dict(project_fields(report, 'report_type audience reporting_period status'),
                     sections=[dict(project_fields(section, 'heading text'),
                                    citations=review_references(section, 'citations'))
                               for section in report['sections']])
                for report in reporting['reports']
            ],
            'critic_reviews': [
                dict(project_fields(review, 'review_round verdict stop_reason'),
                     report_type=next((report['report_type'] for report in reporting['reports']
                                       if report['report_id'] == review['report_id']), None),
                     findings=[dict(project_fields(finding, 'severity category description required_fix'),
                                    citations=review_references(finding, 'citations'))
                               for finding in review['findings']])
                for review in reporting['critic_reviews']
            ],
            'error_codes': [item['code'] for item in full.get('errors', [])],
        }

    def run_review():
        from tempfile import TemporaryDirectory

        with TemporaryDirectory(prefix='harbourline-review-') as directory:
            runtime = Path(directory)
            store = GovernanceStore(runtime / 'governance.sqlite', approvers=set(),
                                    actor_provider=lambda: 'public-review')
            try:
                console = Console(True, runtime, store=store, inputs=root / 'inputs')
                console.run({}, include_reports=True)
                _, full = store.artifact(console.run_id)
                return review_result(full)
            finally:
                store.db.close()
                store._lockfile.close()

    def completed_review(future):
        try:
            return future.result()
        except Exception:
            return None

    @app.route('/review-run', methods=['GET', 'POST'])
    def public_review_run():
        nonlocal active
        job_key = session.get('public_review_job')
        if request.method == 'POST':
            verify_csrf()
            with lock:
                now = monotonic()
                while review_starts and review_starts[0] <= now - 86400:
                    review_starts.popleft()
                for key, (started, future) in list(review_jobs.items()):
                    if future.done() and started <= now - 86400:
                        del review_jobs[key]
                if active and not active.done():
                    session['public_review_notice'] = 'A run is in progress. Try again in a few minutes.'
                elif len(review_starts) >= 6 or (review_starts and now - review_starts[-1] < 300):
                    session['public_review_notice'] = 'Live runs are limited. Try again later or open the saved results.'
                else:
                    job_key = secrets.token_urlsafe(24)
                    active = jobs.submit(run_review)
                    review_jobs[job_key] = (now, active)
                    review_starts.append(now)
                    session['public_review_job'] = job_key
            return redirect('/review-run', code=303)

        with lock:
            job = review_jobs.get(job_key)
        future = job[1] if job else None
        busy = future is not None and not future.done()
        notice = session.pop('public_review_notice', '')
        content = (f'<header><p>MA6094 · Group 11</p><h1>Run B &amp; C</h1>'
                   f'<p>Run planning, risk and reporting with the preset course evidence.</p>'
                   f'<a href="{review_url}">Open saved results</a></header>')
        if notice:
            content += f'<p role="status">{escape(notice)}</p>'
        if busy:
            content += '<p role="status">Running B and C. This page refreshes automatically.</p>'
        else:
            content += (f'<form method="post"><input type="hidden" name="token" value="{csrf()}">'
                        '<button>Run B Planning Agent and C Reports</button></form>')
        if future is not None and not busy:
            result = completed_review(future)
            if result is None:
                content += '<p role="status">The live run could not complete. Saved results remain available.</p>'
            else:
                content += (f'<section class="module"><h2>Run results</h2><p>{escape(result["status"])} · '
                            f'{len(result["wbs"])} WBS items · {len(result["milestones"])} milestones · '
                            f'{len(result["risks"])} risks · {len(result["reports"])} reports · '
                            f'{len(result["critic_reviews"])} Critic reviews</p>'
                            f'<p>Run ID <code>{escape(result["run_id"])}</code></p>'
                            '<p><a href="/review-run/result">Download result JSON</a></p>')
                for title, key in [('Work breakdown', 'wbs'), ('Milestones', 'milestones'),
                                   ('Risk register', 'risks'), ('Report drafts', 'reports'),
                                   ('Critic reviews', 'critic_reviews'), ('Run notices', 'error_codes')]:
                    content += details(title, result[key])
                content += '</section>'
        response = app.make_response(document('Public live run', content))
        if busy:
            response.headers['Refresh'] = '4'
        return response

    @app.get('/review-run/result')
    def public_review_download():
        with lock:
            job = review_jobs.get(session.get('public_review_job'))
        if not job or not job[1].done():
            abort(404)
        result = completed_review(job[1])
        if result is None:
            abort(404)
        response = jsonify(result)
        response.headers['Content-Disposition'] = 'attachment; filename="harbourline-review-result.json"'
        return response

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


_create_workspace_app = create_app


def create_app(config=None):
    from pathlib import Path
    from flask import send_file

    app = _create_workspace_app(config)

    @app.get("/atlas")
    def project_atlas():
        return send_file(Path(__file__).with_name("Harbourline Project Atlas.html"), mimetype="text/html")

    def allow_atlas_scripts(response):
        from flask import request

        if request.endpoint == "project_atlas":
            response.headers["Content-Security-Policy"] += (
                "; script-src 'sha256-dujtd92fRHv58npWTVToXfSXmgZJrJoksoHIV9sGxUM='"
                " 'sha256-+MragbMQ0LS1W5qs3lgLN19Bb3Gby1LLfAW0HqYmsKc='"
            )
        return response

    # Flask runs application response hooks in reverse registration order.
    app.after_request_funcs[None].insert(0, allow_atlas_scripts)
    return app
