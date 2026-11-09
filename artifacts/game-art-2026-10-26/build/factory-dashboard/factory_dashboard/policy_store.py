"""One revisioned, private policy database per Factory configuration."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .model_policy import ConfigurationError, ModelSelection, PolicySnapshot, identifier


class RevisionConflict(ConfigurationError):
    pass


class PolicyStore:
    def __init__(self, path: Path, *, create: bool = True):
        self.path = Path(path).absolute()
        if self.path.is_symlink():
            raise ConfigurationError('Policy database must not be a symlink')
        if create:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            with self._connect() as conn:
                conn.executescript('''
                    CREATE TABLE IF NOT EXISTS revision (id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL);
                    INSERT OR IGNORE INTO revision VALUES(1,0);
                    CREATE TABLE IF NOT EXISTS defaults (role TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS overrides (board TEXT NOT NULL, root TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, PRIMARY KEY(board,root));
                ''')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect('file:' + quote(str(self.path)) + '?mode=rw', uri=True, timeout=2)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _snapshot(conn):
        revision = conn.execute('SELECT value FROM revision WHERE id=1').fetchone()[0]
        defaults = {r: ModelSelection(p, m) for r, p, m in conn.execute('SELECT role,provider,model FROM defaults')}
        overrides = {(b, r): ModelSelection(p, m) for b, r, p, m in conn.execute('SELECT board,root,provider,model FROM overrides')}
        return PolicySnapshot(revision, defaults, overrides)

    def read(self) -> PolicySnapshot:
        with self._connect() as conn:
            conn.execute('BEGIN')
            return self._snapshot(conn)

    def _write(self, sql, args, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ConfigurationError('A nonnegative configuration revision is required')
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            changed = conn.execute('UPDATE revision SET value=value+1 WHERE id=1 AND value=?', (expected_revision,))
            if changed.rowcount != 1:
                raise RevisionConflict('Configuration changed; reload and review before saving')
            conn.execute(sql, args)
            return self._snapshot(conn)

    def set_default(self, role: str, selection: ModelSelection, expected_revision: int) -> PolicySnapshot:
        identifier(role)
        return self._write('INSERT INTO defaults VALUES(?,?,?) ON CONFLICT(role) DO UPDATE SET provider=excluded.provider,model=excluded.model',
                           (role, selection.provider, selection.model), expected_revision)

    def set_override(self, board_key: str, root_id: str, selection: ModelSelection | None, expected_revision: int) -> PolicySnapshot:
        identifier(board_key)
        identifier(root_id)
        if selection is None:
            return self._write('DELETE FROM overrides WHERE board=? AND root=?', (board_key, root_id), expected_revision)
        return self._write('INSERT INTO overrides VALUES(?,?,?,?) ON CONFLICT(board,root) DO UPDATE SET provider=excluded.provider,model=excluded.model',
                           (board_key, root_id, selection.provider, selection.model), expected_revision)
