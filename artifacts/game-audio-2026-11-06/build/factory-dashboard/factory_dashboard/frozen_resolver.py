"""Resolve managed attempts exclusively from immutable task associations."""
from dataclasses import asdict
from pathlib import Path
import re
import sqlite3
from contextlib import closing
from urllib.parse import quote
from .factory_model_resolver import board_key
from .model_policy import ConfigurationError
from .task_identity import is_root, root_id


class FrozenFactoryResolver:
    def __init__(self, store, board_path, board_id, validate_selection):
        self._store = store
        self._path = Path(board_path).resolve()
        self._board = board_id
        self._validate = validate_selection

    def resolve(self, task, board_path, board):
        if Path(board_path).resolve() != self._path or (board or 'default') != self._board:
            return None
        identity = board_key(self._path, self._board)
        snapshot = self._store.snapshot_for_task(identity, task['id'])
        if snapshot is None:
            title = task.get('title') or ''
            managed = is_root(task)
            if not managed and (re.search(r'\(t_[0-9a-f]+\)\s*$', title) or re.match(r'^\[t_[0-9a-f]+\]', title)):
                with closing(sqlite3.connect('file:' + quote(str(self._path)) + '?mode=ro', uri=True)) as conn:
                    conn.row_factory = sqlite3.Row
                    def lookup(tid):
                        row = conn.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
                        return dict(row) if row else None
                    referenced = root_id(task, lookup)
                    referenced_snapshot = self._store.snapshot_for_task(identity,referenced) if referenced else None
                    # Managed workflows use registered identity, never title references.
                    managed = referenced is not None and not (referenced_snapshot and referenced_snapshot.workflow)
            if managed:
                raise ConfigurationError('Factory task snapshot is missing; migration is required')
            return None
        role = task.get('assignee')
        choice = snapshot.legacy_card_settings.get(task['id']) or snapshot.roles.get(role)
        if choice is None:
            raise ConfigurationError('Profile was not captured in this task snapshot: ' + str(role))
        for field, expected in [('model_override', choice.model), ('provider_override', choice.provider), ('reasoning_effort', choice.effort)]:
            if task.get(field) and task[field] != expected:
                raise ConfigurationError('Native card setting conflicts with immutable Factory snapshot: ' + field)
        self._validate(choice, role)
        return {**asdict(choice), 'source': snapshot.origin, 'revision': snapshot.defaults_revision,
                'root_id': self._store.root_for_snapshot(identity, snapshot.id) or task['id'], 'snapshot_id': snapshot.id}
