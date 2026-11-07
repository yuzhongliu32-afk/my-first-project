"""Single-operator browser console bound to IPv4 loopback."""
import argparse
import getpass
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import parse_qs
from uuid import uuid4
import webbrowser

from .governance import GateError, GovernanceStore
from .jira import MockJira, execute_actions, plan_actions
from .llm import ModelGateway
from .operations import client, write
from .pipeline import run_project
from .simulation import ScriptedModel
from .sources import EvidenceLibrary, build_library

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'inputs'
BRIEF = INPUTS / 'Harbourline_Brief.pdf'
PACK = INPUTS / 'Harbourline_Data_Pack.zip'
MODEL_CONFIG = ('OPENAI_API_KEY', 'OPENAI_MODEL')
JIRA_CONFIG = ('JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN', 'JIRA_PROJECT_KEY')
DATES = {
    'weekly_start': ('Weekly start', '2027-03-25'),
    'weekly_end': ('Weekly end', '2027-03-31'),
    'monthly_start': ('Monthly start', '2027-03-01'),
    'monthly_end': ('Monthly end', '2027-03-31'),
    'cutoff': ('Evidence cutoff', '2027-04-06'),
}


class Console:
    def __init__(self, live, runtime, *, store=None, inputs=INPUTS):
        self.live = live
        self.runtime = runtime
        self.inputs = inputs
        self.brief = inputs / BRIEF.name
        self.pack = inputs / PACK.name
        self.mock = None if live else MockJira()
        self.store = store or GovernanceStore(runtime / 'governance.sqlite',
                                     approvers=None if live else {getpass.getuser()})
        self.run_id = None
        self.batch_id = None
        self.trace = []
        self.change = None
        self.dates = {key: default for key, (_, default) in DATES.items()}

    def jira(self):
        return client(self.store) if self.live else self.mock

    def missing_inputs(self):
        return ([] if self.brief.is_file() else [self.brief.name]) + [
            key for key in MODEL_CONFIG if not os.getenv(key)
        ]

    def run(self, fields):
        from datetime import date

        if self.live and (missing := self.missing_inputs()):
            raise GateError('Live run requires ' + ', '.join(missing))
        dates = {key: fields.get(key, default) for key, default in self.dates.items()}
        for value in dates.values():
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError('Use YYYY-MM-DD dates')
        for period in ('weekly', 'monthly'):
            if not dates[f'{period}_start'] <= dates[f'{period}_end'] <= dates['cutoff']:
                raise ValueError('Each reporting period must end on or before the cutoff')
        self.dates = dates

        if self.live:
            command = [sys.executable, str(ROOT / 'scripts/prepare_evidence.py'),
                       '--brief', str(self.brief), '--root', str(self.runtime)]
            if self.pack.is_file():
                command.extend(['--pack', str(self.pack)])
            for flag, filename in (
                ('--metadata', 'verified_source_metadata.json'),
                ('--additional-registry', 'sponsor_answers_registry.json'),
            ):
                path = self.inputs / filename
                if path.is_file():
                    command.extend([flag, str(path)])
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if result.returncode:
                detail = result.stderr.strip().splitlines()
                raise GateError('Source preparation failed. ' + (detail[-1] if detail else 'Check the source files.'))
            lib = EvidenceLibrary(self.runtime / 'data/evidence_library.json')
            registry = self.runtime / 'data/brief_source_registry.json'
            context = {'data_pack_directory': str(self.runtime / 'data/Harbourline_Data_Pack')} if self.pack.is_file() else {}
            gateway = None
        else:
            registry = ROOT / 'examples/test_source_registry.json'
            lib = build_library(json.loads(registry.read_text()), self.runtime / 'evidence.json')
            context = {}
            gateway = ModelGateway(responder=ScriptedModel(revise_first=True))
        context['source_registry_path'] = str(registry)
        request = json.loads((ROOT / 'examples/request.json').read_text())
        request.update(message_id='REQUEST-' + str(uuid4()), run_id='RUN-' + str(uuid4()),
                       source_snapshot_id=lib.snapshot)
        request['request'].update(
            instructions='Prepare source-grounded proposals and human-review report drafts.',
            reporting_period={'start_date': dates['monthly_start'], 'end_date': dates['monthly_end']},
            requested_report_type=None,
        )
        full, trace = run_project(
            request, lib.path, cutoff=dates['cutoff'], b_context=context, c_gateway=gateway,
            reporting_periods={
                'WEEKLY_COMMITTEE': {'start_date': dates['weekly_start'], 'end_date': dates['weekly_end']},
                'MONTHLY_GRANT': {'start_date': dates['monthly_start'], 'end_date': dates['monthly_end']},
            },
        )
        self.store.save(full, mode='LIVE_MODEL_REQUESTED' if self.live else 'SCRIPTED_TEST')
        write(self.runtime / 'runs' / full['run_id'] / 'handoff.json', trace)
        self.run_id, self.trace = full['run_id'], trace
        self.batch_id = self.change = None
        return 'Workflow finished. Review the actual stage statuses below.'

    def act(self, fields):
        action = fields.get('action')
        if action == 'run':
            return self.run(fields)
        if not self.run_id:
            raise GateError('Run the workflow first')
        if action == 'preview':
            row, full = self.store.artifact(self.run_id)
            if row['stale'] or not full['planning']['wbs_items']:
                raise GateError('A current plan with WBS items is required')
            if self.live and row['mode'] != 'LIVE_MODEL_REQUESTED':
                raise GateError('A source-backed live workflow run is required before writing to Jira')
            jira = self.jira()
            payload = plan_actions(full, jira)
            batch = self.store.propose(self.run_id, 'JIRA_WRITE', jira.target, payload)
            self.batch_id = batch['id']
            return 'Preview created. Open the payload and review it before deciding.'
        if action == 'change':
            description = fields.get('description', '').strip()
            if not description:
                raise GateError('Describe the change to analyse')
            self.change = self.store.record_change(self.run_id, {
                'event_id': 'WHATIF-' + str(uuid4()), 'change_type': fields.get('change_type', 'OTHER'),
                'description': description, 'hypothetical': True,
            })
            return 'What-if recorded. Previous outputs are stale and pending approvals were invalidated.'
        if action not in ('approve', 'reject', 'apply') or not self.batch_id:
            raise GateError('Create a Jira preview first')
        batch = self.store.batch(self.batch_id)
        if fields.get('batch_id') != batch['id']:
            raise GateError('Preview changed. Refresh and review the current payload.')
        if action in ('approve', 'reject'):
            if fields.get('reviewed') != 'yes':
                raise GateError('Confirm that you reviewed the payload')
            self.store.approve(batch['id'], confirmed_hash=fields.get('hash'),
                               decision='APPROVED' if action == 'approve' else 'REJECTED')
            return 'Decision recorded.'
        jira = self.jira()
        result = self.store.execute(batch['id'], jira.target,
                                    lambda payload, audit: execute_actions(payload, jira, audit))
        return 'Jira batch state: ' + result['state']

    def export(self, kind):
        if kind == 'audit':
            return self.store.audit()
        if kind == 'handoff' and self.run_id:
            return self.trace
        if kind == 'result' and self.run_id:
            return self.store.export(self.run_id)
        raise KeyError(kind)


def json_block(value):
    return '<pre>' + escape(json.dumps(value, indent=2, ensure_ascii=False)) + '</pre>'


def details(label, value):
    return f'<details><summary>{escape(label)}</summary>{json_block(value)}</details>'


def page(console, token, notice='', error=False, *, allowed=None, toolbar='', busy=False):
    if allowed is None:
        allowed = {'run', 'preview', 'approve', 'reject', 'apply', 'change'}
    if busy:
        allowed = set()
    def form(body):
        return f'<form method="post"><input type="hidden" name="token" value="{token}">{body}</form>'

    def button(action, title):
        return f'<button name="action" value="{action}">{title}</button>'

    mode = 'LIVE MODEL + JIRA SANDBOX' if console.live else 'REHEARSAL · SCRIPTED MODEL + SIMULATED JIRA'
    mode_note = ('Writes require local human approval and target the configured team sandbox.'
                 if console.live else 'Rehearsal uses included sample data. No model or Jira service is contacted.')
    banner = f'<p class="notice {"error" if error else ""}" role="status">{escape(notice)}</p>' if notice else ''
    dates = ''.join(
        f'<label>{label}<input name="{key}" type="date" value="{escape(console.dates[key], quote=True)}" required></label>'
        for key, (label, _) in DATES.items()
    )
    setup = ''
    if console.live:
        missing = console.missing_inputs() + [key for key in JIRA_CONFIG if not os.getenv(key)]
        setup = ('<p>Setup needed: ' + escape(', '.join(missing)) + '</p>') if missing else '<p>Input files and configuration detected.</p>'
    coverage = '<p>Evidence input: <strong>Brief + Data Pack</strong>.</p>' if console.pack.is_file() else '<p>Evidence input: <strong>Brief only</strong>. Official Data Pack unavailable.</p>'
    content = f'<section><h2>1. Run the integrated workflow</h2>{setup}{coverage}'
    if 'run' in allowed:
        content += form(f'<div class="dates">{dates}</div>' + button('run', 'Run planning, risk and reports'))
    content += '</section>'
    if console.run_id:
        row, full = console.store.artifact(console.run_id)
        plan, risk, reporting = full['planning'], full['risk'], full['reporting']
        reports, reviews = reporting['reports'], reporting['critic_reviews']
        status = full['status'] + (' · STALE' if row['stale'] else '')
        content += (
            f'<section><h2>2. Review results</h2><p><strong>{escape(status)}</strong> · '
            f'{len(plan["wbs_items"])} WBS items · {len(plan["milestones"])} milestones · '
            f'{len(risk["risks"])} risks · {len(reports)} reports · {len(reviews)} Critic reviews</p>'
            '<p>Run ID <code>' + escape(console.run_id) + '</code></p>'
            + details('Automatic B → C handoff', console.trace)
            + details('Planning and milestones', plan) + details('Risk register and what-if', risk)
            + details('Weekly and monthly reports, evidence and Critic', reporting)
            + '<p><a href="/download/result">Download full result</a> · '
              '<a href="/download/handoff">Download handoff trace</a></p></section>'
        )
        content += '<section><h2>3. Jira preview, approval and readback</h2>'
        if not row['stale'] and 'preview' in allowed:
            content += form(button('preview', 'Build Jira preview'))
        if console.batch_id:
            batch = console.store.batch(console.batch_id)
            content += (
                f'<p><strong>{escape(batch["state"])}</strong> · {escape(batch["target"])}</p>'
                + details('Review the exact Jira payload', batch['payload'])
                + '<p>Review hash <code>' + escape(batch['hash']) + '</code></p>'
            )
            identity = f'<input type="hidden" name="batch_id" value="{escape(batch["id"], quote=True)}">'
            if batch['state'] == 'PENDING' and 'approve' in allowed:
                content += form(identity + f'<input type="hidden" name="hash" value="{batch["hash"]}">'
                                '<label><input type="checkbox" name="reviewed" value="yes" required> '
                                'I reviewed this exact payload and target.</label><div>'
                                + button('approve', 'Approve reviewed batch') + button('reject', 'Reject batch') + '</div>')
            if batch['state'] == 'APPROVED' and 'apply' in allowed:
                content += form(identity + button('apply', 'Execute approved Jira batch and verify readback'))
            events = [event for event in console.store.audit()
                      if event['detail'].get('batch_id') == console.batch_id]
            keys = list(dict.fromkeys(e['detail']['issue_key'] for e in events
                                     if e['event'] == 'JIRA_READBACK_VERIFIED' and e['detail'].get('issue_key')))
            if keys:
                content += '<p>Issue fields verified by readback: ' + escape(', '.join(keys)) + '</p>'
            content += details('Batch audit and readback', events)
        content += '</section><section><h2>4. Analyse a change</h2>'
        if not row['stale'] and 'change' in allowed:
            content += form(
                '<label>Change scenario <select name="change_type"><option value="LIFT_DELAY">Lift delay</option>'
                '<option value="OTHER">Other change</option></select></label>'
                '<label>Description <input name="description" maxlength="1000" required '
                'value="Hypothetical supplier delay for the lifts"></label>'
                + button('change', 'Analyse what-if and flag affected outputs')
            )
        if console.change is not None:
            content += details('Change impact and stale artifacts', console.change)
        content += '</section>'
    content += '<section><h2>Audit export</h2><a href="/download/audit">Download audit log JSON</a></section>'
    return f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Harbourline · MA6094</title>
<style>
body{{margin:0;background:#f3f5f7;color:#14263a;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:940px;margin:auto;padding:24px}} h1{{margin:0 0 10px}} h2{{font-size:1.2rem;margin-top:0}}
section,.notice{{background:white;padding:16px 20px;margin:14px 0;border:1px solid #c8d3dd;border-radius:7px}}
.notice{{border-left:5px solid #17704d}} .error{{border-left-color:#a52126}}
.mode{{font-weight:bold;color:#264a71}} button{{margin:8px 8px 0 0;background:#184978;color:white;border:0;border-radius:4px;padding:9px 13px;cursor:pointer;font:inherit}}
a{{color:#174b82}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1f5;padding:12px;max-height:420px;overflow:auto}}
details{{margin:8px 0}} summary{{cursor:pointer;font-weight:600}} code{{overflow-wrap:anywhere}}
label{{display:block;margin:4px 0}} .dates{{display:flex;flex-wrap:wrap;gap:12px}} .dates input{{display:block}}
</style>
<main><header><h1>Harbourline Community Hub</h1><p class="mode">MA6094 · {mode}</p>
<p>{mode_note}</p>{toolbar}</header>{banner}{content}</main></html>'''


def handler(console):
    token = secrets.token_urlsafe(32)
    notice = ''

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, media='text/html; charset=utf-8', filename=None):
            body = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', media)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def allowed_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.allowed_host():
                self.send_error(403)
                return
            if self.path == '/':
                self.respond(200, page(console, token, notice))
                return
            files = {'/download/audit': 'audit', '/download/result': 'result', '/download/handoff': 'handoff'}
            try:
                kind = files[self.path]
                value = console.export(kind)
            except KeyError:
                self.send_error(404)
                return
            self.respond(200, json.dumps(value, indent=2, ensure_ascii=False), 'application/json',
                         f'harbourline-{kind}-{"live" if console.live else "rehearsal"}.json')

        def do_POST(self):
            nonlocal notice
            if not self.allowed_host() or self.path != '/':
                self.send_error(403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8192:
                    raise ValueError
                fields = {k: v[0] for k, v in parse_qs(
                    self.rfile.read(size).decode(), max_num_fields=16).items()}
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            if not secrets.compare_digest(fields.get('token', '').encode(), token.encode()):
                self.send_error(403)
                return
            try:
                notice = console.act(fields)
            except (ValueError, KeyError, OSError) as exc:
                self.respond(400, page(console, token, str(exc), error=True))
            except Exception as exc:
                self.respond(500, page(console, token, f'Operation failed ({type(exc).__name__}). Review local setup and audit.', error=True))
            else:
                self.send_response(303)
                self.send_header('Location', '/')
                self.end_headers()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Use local .env credentials and the team Jira sandbox')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if args.live:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', interpolate=False)
    runtime = ROOT / '.local' / ('live-console' if args.live else f'rehearsal-{uuid4()}')
    console = Console(args.live, runtime)
    with HTTPServer(('127.0.0.1', 0), handler(console)) as server:
        url = f'http://127.0.0.1:{server.server_port}/'
        print(f'Open {url} · Keep this window open. Press Ctrl+C to stop.', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            console.store.db.close()
            console.store._lockfile.close()


if __name__ == '__main__':
    main()
