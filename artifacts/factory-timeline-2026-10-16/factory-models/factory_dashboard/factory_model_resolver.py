"""Factory policy consumer for the generic Hermes pre-spawn hook."""
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

from .model_policy import ConfigurationError, ModelPolicy


def board_key(path: Path, board_id: str) -> str:
    return json.dumps([str(Path(path).resolve()), board_id], separators=(',', ':'))


def factory_root_id(task, board_path):
    title = task.get('title') or ''
    if title.startswith('FACTORY:'):
        root_id = task['id']
    else:
        match = re.search(r'\((t_[0-9a-f]+)\)\s*$', title)
        if not match:
            return None
        root_id = match[1]
    with closing(sqlite3.connect('file:' + quote(str(Path(board_path).resolve())) + '?mode=ro', uri=True)) as conn:
        root = conn.execute('SELECT title FROM tasks WHERE id=?', (root_id,)).fetchone()
    if not root or not (root[0] or '').startswith('FACTORY:'):
        return None
    return root_id


class FactoryModelResolver:
    def __init__(self, policy_store, board_path, board_id, validate_selection):
        self._store = policy_store
        self._board_path = Path(board_path).resolve()
        self._board_id = board_id
        self._validate = validate_selection

    def resolve(self, task: dict, board_path, board):
        if Path(board_path).resolve() != self._board_path or (board or 'default') != self._board_id:
            return None
        root_id = factory_root_id(task, self._board_path)
        if root_id is None:
            return None
        resolved = ModelPolicy.resolve(self._store.read(), board_key(self._board_path, self._board_id), root_id, task['assignee'])
        choice = resolved.selection
        if task.get('model_override') and (task['model_override'] != choice.model or task.get('provider_override') not in (None, choice.provider)):
            raise ConfigurationError('Native card override conflicts with Factory policy; clear it or align the selections')
        self._validate(choice, task['assignee'])
        return {**asdict(choice), 'source': resolved.source, 'revision': resolved.revision, 'root_id': root_id}
