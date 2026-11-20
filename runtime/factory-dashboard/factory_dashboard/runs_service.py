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

    def _env(self):
        import os
        return dict(os.environ, HERMES_HOME=str(self._home), FACTORY_HERMES_HOME=str(self._home))
