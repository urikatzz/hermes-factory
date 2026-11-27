"""Aggregated Factory runs: the default board plus every registered run board, with board-scoped operations.

Reads never mutate a board. Lifecycle operations run through `scripts/factory_boards.py`, which loads the installed plugin so the
workflow guard authority is the same one the controller uses; this service never edits a board itself.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
from urllib.parse import quote

from .board_registry import DEFAULT_BOARD
from .model_policy import ConfigurationError
from .run_boards import RunBoards, describe_root

OPERATIONS = ('pause', 'resume', 'cancel', 'archive')
def _last_error(output):
    """The last line a script printed, without a `package.module.SomeError: ` prefix."""
    import re
    line = output.strip().splitlines()[-1] if output.strip() else ''
    return re.sub(r'^[\w.]*(Error|Exception): ', '', line)[:600]


RECOVERY_ACTIONS = ('resume', 'retry_stage', 'reevaluate', 'park', 'resume_task', 'extra_repairs')


class RunsService:
    def __init__(self, resolver, hermes_home, *, state_dir=None, evidence_root=None, cli_python=None, cli_script=None, collector_factory=None, builder=None):
        self._resolver = resolver
        self._registry = resolver.registry
        self._runs = RunBoards(self._registry)
        self._home = Path(hermes_home)
        self._state = Path(state_dir) if state_dir else self._home / 'state' / 'factory'
        self._evidence = evidence_root
        self._python = cli_python or sys.executable
        self._script = Path(cli_script) if cli_script else Path(__file__).resolve().parents[1] / 'scripts' / 'factory_boards.py'
        self._collector_factory = collector_factory
        self._builder = builder

    # ---- reads
    def _default_roots(self):
        path = self._registry.default_path
        if not path.is_file():
            return []
        with closing(sqlite3.connect('file:' + quote(str(path)) + '?mode=ro', uri=True, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            roots = conn.execute("SELECT id, title, status, created_at FROM tasks WHERE title LIKE 'FACTORY:%' AND status != 'archived' ORDER BY created_at DESC LIMIT 100").fetchall()
            return [dict(r, **describe_root(conn, r['id'])) for r in roots]

    def overview(self):
        summaries = [self._runs.summary(b) for b in self._registry.list()]
        live = [s for s in summaries if s['status'] in ('provisioning', 'active', 'paused')]
        return {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'default_board': {'board_id': self._registry.default_id, 'roots': self._default_roots()},
            'runs': summaries,
            'totals': {'runs': len(summaries), 'live': len(live), 'paused': sum(s['status'] == 'paused' for s in live),
                       'awaiting_approval': sum(s['awaiting'] for s in live), 'needs_intervention': sum(s['needs_intervention'] for s in live),
                       'failed': sum(s['status'] == 'failed' for s in summaries),
                       'archived': sum(s['status'] == 'archived' for s in summaries)}}

    def board(self, board_id, *, with_report=True):
        record = self._registry.get(board_id)
        if record is None:
            raise ConfigurationError('Unknown run board: ' + str(board_id))
        detail = self._runs.summary(record)
        if with_report and detail['available'] and self._collector_factory:
            published = self._state / ('published_%s.json' % board_id)
            report = self._builder.build(self._collector_factory(self._database(record, detail), board_id, published))
            detail['report'] = report
            detail['usage'] = report.get('usage')
        return detail

    @staticmethod
    def _database(record, detail):
        meta = dict(record.meta)
        return Path(meta['archived_path']) / 'kanban.db' if record.status == 'archived' and meta.get('archived_path') else record.db_path

    # ---- operations
    def operate(self, board_id, operation, reason=''):
        if operation not in OPERATIONS:
            raise ConfigurationError('Unsupported run operation: %s' % operation)
        if board_id == DEFAULT_BOARD or self._registry.get(board_id) is None:
            raise ConfigurationError('Only registered run boards support %s; the default board has no run lifecycle' % operation)
        command = [self._python, str(self._script), operation, board_id]
        if operation in ('pause', 'cancel'):
            command += ['--reason', (reason or operation + ' from the dashboard')[:300]]
        done = subprocess.run(command, capture_output=True, text=True, timeout=300, env=self._env())
        if done.returncode != 0:
            raise ConfigurationError((done.stderr or done.stdout).strip().splitlines()[-1][:400] if (done.stderr or done.stdout).strip() else '%s failed' % operation)
        return {'board_id': board_id, 'operation': operation, 'status': self._registry.get(board_id).status}

    def archive_cards(self, board_id, cards):
        """Remove replaced attempts from a run board, through `factory_boards.py archive-cards` (plugin loaded, controller scope)."""
        if board_id == DEFAULT_BOARD or self._registry.get(board_id) is None:
            raise ConfigurationError('Only registered run boards can be tidied from this page')
        if not isinstance(cards, list) or not 1 <= len(cards) <= 50 or any(not isinstance(c, str) or not c.replace('_', '').isalnum() for c in cards):
            raise ConfigurationError('Name 1 to 50 card ids')
        done = subprocess.run([self._python, str(self._script), 'archive-cards', board_id, *cards], capture_output=True, text=True, timeout=120, env=self._env())
        output = (done.stderr or done.stdout).strip()
        if done.returncode != 0:
            raise ConfigurationError(_last_error(output) or 'Archive failed')
        return {'board_id': board_id, 'archived': json.loads(done.stdout.strip().splitlines()[-1])}

    def recover(self, board_id, body):
        """A human recovery decision for a run's controller, applied through `resume_factory_workflow.py` (the same path an operator uses).
        Never touches cards directly: unblocking a card behind the controller's back is what leaves a run stalled."""
        action = body.get('action')
        note = body.get('note')
        if action not in RECOVERY_ACTIONS:
            raise ConfigurationError('Unknown recovery action; use one of: ' + ', '.join(RECOVERY_ACTIONS))
        if not isinstance(note, str) or len(note.strip()) < 10:
            raise ConfigurationError('Write a note (at least 10 characters) saying what you decided and why; it is recorded with the run')
        record = self._registry.get(board_id)
        if record is None or board_id == DEFAULT_BOARD:
            raise ConfigurationError('Only registered run boards can be recovered from this page')
        if record.status != 'active':
            raise ConfigurationError('Run board %s is %s; resume it first' % (board_id, record.status))
        if not record.root_id:
            raise ConfigurationError('Run board %s has no root yet' % board_id)
        command = [self._python, str(self._script.with_name('resume_factory_workflow.py')), '--hermes-source', str(self._home / 'hermes-agent'),
                   '--board-db', str(record.db_path), '--board', board_id, '--new-project-root', str(Path.home() / 'factory'),
                   '--root', record.root_id, '--note', note.strip()[:2000]]
        decision = None
        if action == 'retry_stage':
            command.append('--retry-stage')
        elif action == 'reevaluate':
            command.append('--reevaluate')
        elif action == 'park':
            command.append('--park')
        elif action == 'resume_task':
            task = body.get('task')
            if not isinstance(task, str) or not task.replace('-', '').isalnum():
                raise ConfigurationError('Name the parked task to resume')
            command += ['--task', task]
        elif action == 'extra_repairs':
            count = body.get('count', 1)
            if type(count) is not int or not 1 <= count <= 2:
                raise ConfigurationError('Extra repairs must be 1 or 2')
            decision = {'extra_repairs': count}
        import tempfile, os
        path = None
        try:
            if decision:
                fd, path = tempfile.mkstemp(suffix='.json', prefix='factory-decision-')
                with os.fdopen(fd, 'w') as handle:
                    json.dump(decision, handle)
                command += ['--decision-file', path]
            done = subprocess.run(command, capture_output=True, text=True, timeout=300, env=self._env())
        finally:
            if path:
                os.unlink(path)
        output = (done.stderr or done.stdout).strip()
        if done.returncode != 0:
            raise ConfigurationError(_last_error(output) or 'Recovery failed')
        return {'board_id': board_id, 'action': action, 'result': done.stdout.strip()[-400:]}

    def _env(self):
        import os
        return dict(os.environ, HERMES_HOME=str(self._home), FACTORY_HERMES_HOME=str(self._home))
