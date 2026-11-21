#!/usr/bin/env python3
"""Behavioral probe: does the Hermes kanban owner run a task on the model the dispatcher captured for its attempt?

`hermes_patches.py status` proves the patches are present, not that they work, and a Hermes update once kept every patch applying cleanly while the
worker-model hook stopped taking effect (workers silently ran each profile's default). This builds a throwaway kanban board in a temporary HERMES_HOME,
puts a running task whose run carries a captured `worker_model_selection` in front of the owner's own `build_kanban_policy`, and reads the model it picked.

    probe_owner_model.py [--source DIR] [--json]       exit 0 when the owner honours the selection
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SELECTION = dict(provider='openrouter', model='anthropic/claude-opus-5.5', effort='low', source='probe', root_id='t_probe', revision=1)


def run_child(source, selection, python=None):
    """One probe case in a fresh process with Hermes importable from `source`: {model, provider, reasoning} or {refused: reason}."""
    source = Path(source).expanduser().resolve()
    python = python or os.environ.get('HERMES_PYTHON') or next((str(c) for c in (source / 'venv/bin/python', Path.home() / '.hermes/hermes-agent/venv/bin/python') if c.exists()), sys.executable)
    env = dict(os.environ, PYTHONPATH=str(source) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    done = subprocess.run([python, str(Path(__file__).resolve()), '--child', json.dumps(selection)], capture_output=True, text=True, env=env, timeout=180, cwd=tempfile.gettempdir())
    lines = [line for line in done.stdout.splitlines() if line.startswith('{')]
    if not lines:
        return dict(error=(done.stderr or done.stdout)[-400:])
    return json.loads(lines[-1])


def probe(source, python=None):
    """Three cases; `ok` is True only when the captured selection is applied, an absent one leaves the profile default, and a malformed one is refused."""
    with_selection = run_child(source, SELECTION, python)
    without = run_child(source, {}, python)
    malformed = run_child(source, {'provider': 'openrouter'}, python)
    applied = (with_selection.get('model'), with_selection.get('provider')) == (SELECTION['model'], SELECTION['provider']) and 'low' in str(with_selection.get('reasoning'))
    untouched = not without.get('error') and not without.get('refused') and without.get('model') in ('', None)
    refused = bool(malformed.get('refused'))
    detail = '' if applied else ('the owner ignored the captured selection (it picked ' + repr(with_selection.get('model')) + '/' + repr(with_selection.get('provider'))
                                 + '): workers run the profile default instead of the Factory\'s choice' if not with_selection.get('error') else 'probe failed: ' + with_selection['error'])
    return dict(ok=applied and untouched and refused, applied=applied, untouched_without_selection=untouched, refuses_malformed=refused, detail=detail,
                cases=dict(with_selection=with_selection, without_selection=without, malformed=malformed))


def child(selection_text):
    from types import SimpleNamespace
    try:
        import hermes_bootstrap  # noqa: F401  every Hermes entry point imports this first: in a managed checkout it re-execs into the runtime that holds the dependencies
    except ImportError:
        pass
    selection = json.loads(selection_text)
    # HERMES_HOME is deliberately left alone: pointing it at a temporary directory makes the checkout's launcher bootstrap a new runtime and re-exec. The board and profile are passed by path.
    tmp = tempfile.mkdtemp(prefix='owner-model-probe-')
    profile = Path(tmp) / 'profiles' / 'probe'
    profile.mkdir(parents=True)
    (profile / 'config.yaml').write_text('model:\n  provider: anthropic\n  default: claude-haiku-5-5\n  reasoning_effort: low\n')
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    db = Path(tmp) / 'kanban.db'
    conn = kbc.connect(db)
    task_id = kb.create_task(conn, title='probe', assignee='probe', workspace_kind='dir', workspace_path=tmp)
    conn.execute("UPDATE tasks SET status='running', current_run_id=1, claim_lock='lock' WHERE id=?", (task_id,))
    conn.execute('INSERT INTO task_runs(id,task_id,profile,status,claim_lock,started_at,metadata) VALUES(1,?,?,?,?,?,?)',
                 (task_id, 'probe', 'running', 'lock', int(time.time()), json.dumps({'worker_model_selection': selection} if selection else {})))
    conn.commit()
    conn.close()
    import gateway.session_kanban as owner
    import hermes_cli.profiles as profiles
    profiles.resolve_profile_env = lambda name: str(profile)   # the one HERMES_HOME-dependent lookup (imported inside the function): the probe's profile lives in a temporary directory
    build_kanban_policy = owner.build_kanban_policy
    from persistence.core.errors import AuthorityRefusal
    connection = SimpleNamespace(authority=SimpleNamespace(profile_id=str(profile)), actor=SimpleNamespace(profile_id=str(profile), capabilities={'session:create'}), native_owner=True)
    try:
        policy, _ = build_kanban_policy(connection, {'board': 'default', 'task_id': task_id, 'run_id': 1, 'claim_lock': 'lock', 'db': str(db)}, {})
    except AuthorityRefusal as exc:
        print(json.dumps({'refused': str(exc), 'cause': repr(exc.__cause__)[:300]}))
        return 0
    print(json.dumps({'model': policy.model, 'provider': policy.provider, 'reasoning': str(policy.reasoning_config), 'toolsets': sorted(policy.toolsets)}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', help='Hermes source tree (default $HERMES_SOURCE or ~/.hermes/hermes-agent)')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--child', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child is not None:
        return child(args.child)
    source = args.source or os.environ.get('HERMES_SOURCE') or Path.home() / '.hermes' / 'hermes-agent'
    result = probe(source)
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(('ok: the owner runs a task on the model captured for its attempt' if result['ok'] else 'FAILED: ' + (result['detail'] or 'see --json')))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
