"""Persistent registry of Factory run boards and the single resolver that decides which boards the Factory governs.

Every Factory hook, controller and script asks `BoardResolver` about a board; nothing else hard-codes a board name or
database path. A board is Factory-managed only when it is the configured legacy default board or an entry in the registry.
Unregistered boards are never touched. A registered board whose identity is inconsistent fails closed with a diagnostic.
"""
from contextlib import closing, contextmanager
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import re
import sqlite3
import time

from .factory_model_resolver import board_key
from .model_policy import ConfigurationError

DEFAULT_BOARD = 'default'
SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
TICKET = re.compile(r'^[a-z0-9][a-z0-9_-]{0,50}$')
# provisioning/active/paused boards are governed and counted; cancelled/archived boards are history; failed boards fail closed.
STATES = ('provisioning', 'active', 'paused', 'cancelled', 'archived', 'failed')
GOVERNED = ('provisioning', 'active', 'paused')
RUNNING = ('active',)
MAX_PROVISION_ATTEMPTS = 3

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS factory_boards(
    board_id TEXT PRIMARY KEY,
    db_path TEXT NOT NULL UNIQUE,
    source_board_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    workflow_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    root_id TEXT,
    project_dir TEXT,
    branch TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(source_board_id, ticket_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS factory_boards_project_dir ON factory_boards(project_dir)
    WHERE project_dir IS NOT NULL AND project_dir != '' AND status IN ('provisioning','active','paused');
CREATE UNIQUE INDEX IF NOT EXISTS factory_boards_branch ON factory_boards(project_id, branch)
    WHERE branch IS NOT NULL AND branch != '' AND status IN ('provisioning','active','paused');
'''


@dataclass(frozen=True)
class FactoryBoard:
    board_id: str
    db_path: Path
    identity: str
    kind: str                      # 'default' (legacy) or 'run'
    source_board_id: str = DEFAULT_BOARD
    source_identity: str = ''
    ticket_id: str = ''
    project_id: str = ''
    workflow_id: str = ''
    status: str = 'active'
    root_id: str = ''
    name: str = ''
    project_dir: str = ''
    branch: str = ''
    meta: tuple = ()

    @property
    def is_run(self):
        return self.kind == 'run'

    def public(self):
        data = asdict(self)
        data['db_path'] = str(self.db_path)
        data['meta'] = dict(self.meta)
        return data


def run_board_slug(ticket_id):
    ticket = str(ticket_id)
    slug = 'run-' + ticket
    if not TICKET.match(ticket) or not SLUG.match(slug):
        raise ConfigurationError('Ticket id cannot name a run board: %r' % (ticket_id,))
    return slug


def default_boards_root(default_board_path):
    """Hermes keeps named boards at <root>/kanban/boards/<slug>/kanban.db, beside the default <root>/kanban.db."""
    return Path(default_board_path).resolve().parent / 'kanban' / 'boards'


def _to_board(row, source_identity):
    meta = json.loads(row['meta'] or '{}')
    return FactoryBoard(
        board_id=row['board_id'], db_path=Path(row['db_path']), identity=board_key(Path(row['db_path']), row['board_id']), kind='run',
        source_board_id=row['source_board_id'], source_identity=source_identity, ticket_id=row['ticket_id'], project_id=row['project_id'],
        workflow_id=row['workflow_id'], status=row['status'], root_id=row['root_id'] or '', name=row['name'],
        project_dir=row['project_dir'] or '', branch=row['branch'] or '', meta=tuple(sorted(meta.items())))


class BoardRegistry:
    def __init__(self, path, boards_root, default_board_path, default_board_id=DEFAULT_BOARD, *, create=True):
        self.path = Path(path)
        self.boards_root = Path(boards_root).resolve()
        self.default_path = Path(default_board_path).resolve()
        self.default_id = default_board_id
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._open()) as conn:
                conn.executescript(_SCHEMA)
        elif not self.path.exists():
            raise ConfigurationError('Board registry is missing: ' + str(self.path))

    def _open(self):
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    @contextmanager
    def _txn(self):
        with closing(self._open()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield conn
            except BaseException:
                conn.execute('ROLLBACK')
                raise
            conn.execute('COMMIT')

    def source_identity(self, source_board_id):
        if source_board_id != self.default_id:
            raise ConfigurationError('Unknown source board for a Factory run: %r' % (source_board_id,))
        return board_key(self.default_path, self.default_id)

    def expected_db_path(self, board_id):
        return (self.boards_root / board_id / 'kanban.db').resolve()

    def _wrap(self, row):
        return _to_board(row, self.source_identity(row['source_board_id'])) if row else None

    # ---- reads
    def get(self, board_id):
        with closing(self._open()) as conn:
            return self._wrap(conn.execute('SELECT * FROM factory_boards WHERE board_id=?', (board_id,)).fetchone())

    def by_ticket(self, ticket_id, source_board_id=DEFAULT_BOARD):
        with closing(self._open()) as conn:
            return self._wrap(conn.execute('SELECT * FROM factory_boards WHERE source_board_id=? AND ticket_id=?', (source_board_id, ticket_id)).fetchone())

    def by_path(self, db_path):
        with closing(self._open()) as conn:
            return self._wrap(conn.execute('SELECT * FROM factory_boards WHERE db_path=?', (str(Path(db_path).resolve()),)).fetchone())

    def by_root(self, root_id):
        with closing(self._open()) as conn:
            return [self._wrap(r) for r in conn.execute('SELECT * FROM factory_boards WHERE root_id=?', (root_id,))]

    def list(self, statuses=None):
        with closing(self._open()) as conn:
            rows = conn.execute('SELECT * FROM factory_boards ORDER BY created_at, board_id').fetchall()
        boards = [self._wrap(r) for r in rows]
        return [b for b in boards if statuses is None or b.status in statuses]

    def error_of(self, board_id):
        with closing(self._open()) as conn:
            row = conn.execute('SELECT last_error, attempts FROM factory_boards WHERE board_id=?', (board_id,)).fetchone()
        return (row['last_error'], row['attempts']) if row else ('', 0)

    # ---- writes
    def begin(self, ticket_id, *, name='', project_id='', workflow_id='', project_dir='', branch='', source_board_id=DEFAULT_BOARD):
        """Idempotently reserve the run board of one ticket. A second call returns the existing record unchanged."""
        board_id = run_board_slug(ticket_id)
        self.source_identity(source_board_id)
        now = time.time()
        with self._txn() as conn:
            row = conn.execute('SELECT * FROM factory_boards WHERE source_board_id=? AND ticket_id=?', (source_board_id, ticket_id)).fetchone()
            if row:
                # A retry must describe the same run; a different directory or branch means the caller lost track of the reservation.
                for field, given in (('project_dir', project_dir), ('branch', branch), ('project_id', project_id)):
                    if given and row[field] and row[field] != given:
                        raise ConfigurationError('Run board %s reserved %s=%r; refusing a retry with %r' % (row['board_id'], field, row[field], given))
                return self._wrap(row)
            clash = conn.execute('SELECT board_id FROM factory_boards WHERE board_id=?', (board_id,)).fetchone()
            if clash:
                raise ConfigurationError('Board id %s is already registered for another ticket' % board_id)
            if project_dir:
                other = conn.execute("SELECT board_id FROM factory_boards WHERE project_dir=? AND status IN ('provisioning','active','paused')", (project_dir,)).fetchone()
                if other:
                    raise ConfigurationError('Project directory %s is already owned by run board %s' % (project_dir, other['board_id']))
            if branch:
                other = conn.execute("SELECT board_id FROM factory_boards WHERE project_id=? AND branch=? AND status IN ('provisioning','active','paused')", (project_id, branch)).fetchone()
                if other:
                    raise ConfigurationError('Branch %s of %s is already owned by run board %s' % (branch, project_id, other['board_id']))
            conn.execute(
                'INSERT INTO factory_boards(board_id,db_path,source_board_id,ticket_id,project_id,workflow_id,name,status,project_dir,branch,created_at,updated_at) '
                "VALUES(?,?,?,?,?,?,?,'provisioning',?,?,?,?)",
                (board_id, str(self.expected_db_path(board_id)), source_board_id, ticket_id, project_id, workflow_id, name, project_dir or None, branch or None, now, now))
            return self._wrap(conn.execute('SELECT * FROM factory_boards WHERE board_id=?', (board_id,)).fetchone())

    def _update(self, board_id, **fields):
        fields['updated_at'] = time.time()
        columns = ','.join(k + '=?' for k in fields)
        with self._txn() as conn:
            if conn.execute('SELECT 1 FROM factory_boards WHERE board_id=?', (board_id,)).fetchone() is None:
                raise ConfigurationError('Unknown run board: ' + board_id)
            conn.execute('UPDATE factory_boards SET ' + columns + ' WHERE board_id=?', (*fields.values(), board_id))
        return self.get(board_id)

    def mark_active(self, board_id):
        board = self.get(board_id)
        if board is None:
            raise ConfigurationError('Unknown run board: ' + board_id)
        if board.status in ('failed', 'cancelled', 'archived'):
            raise ConfigurationError('Run board %s is %s and cannot be activated' % (board_id, board.status))
        return self._update(board_id, status='active' if board.status == 'provisioning' else board.status, last_error='')

    def set_status(self, board_id, status, **meta):
        if status not in STATES:
            raise ConfigurationError('Unknown run board status: ' + status)
        current = self.get(board_id)
        if current is None:
            raise ConfigurationError('Unknown run board: ' + board_id)
        merged = {**dict(current.meta), **meta}
        return self._update(board_id, status=status, meta=json.dumps(merged, sort_keys=True))

    def set_root(self, board_id, root_id):
        board = self.get(board_id)
        if board is None:
            raise ConfigurationError('Unknown run board: ' + board_id)
        if board.root_id and board.root_id != root_id:
            raise ConfigurationError('Run board %s already owns root %s; refusing to bind %s' % (board_id, board.root_id, root_id))
        return self._update(board_id, root_id=root_id)

    def record_failure(self, board_id, error):
        """Count a provisioning failure; the board fails closed once the attempt budget is spent."""
        with self._txn() as conn:
            row = conn.execute('SELECT attempts, status FROM factory_boards WHERE board_id=?', (board_id,)).fetchone()
            if row is None:
                raise ConfigurationError('Unknown run board: ' + board_id)
            attempts = row['attempts'] + 1
            status = 'failed' if attempts >= MAX_PROVISION_ATTEMPTS and row['status'] == 'provisioning' else row['status']
            conn.execute('UPDATE factory_boards SET attempts=?, last_error=?, status=?, updated_at=? WHERE board_id=?',
                         (attempts, str(error)[:1000], status, time.time(), board_id))
        return self.get(board_id)

    def reset_failed(self, board_id):
        """Operator decision: give a failed run board a fresh provisioning budget."""
        board = self.get(board_id)
        if board is None or board.status != 'failed':
            raise ConfigurationError('Only failed run boards can be reset')
        return self._update(board_id, status='provisioning', attempts=0, last_error='')


class BoardResolver:
    """Decides whether a board is Factory-managed. Path is authoritative; labels only guard against cross-board mixups."""

    def __init__(self, registry):
        self.registry = registry

    def default(self):
        reg = self.registry
        return FactoryBoard(board_id=reg.default_id, db_path=reg.default_path, identity=board_key(reg.default_path, reg.default_id), kind='default',
                            source_board_id=reg.default_id, source_identity=board_key(reg.default_path, reg.default_id), status='active')

    def resolve(self, board_path, board_label=None):
        """Return the governing FactoryBoard, None for an unrelated board, or raise ConfigurationError for a broken identity."""
        path = Path(board_path).resolve()
        label = board_label or DEFAULT_BOARD
        reg = self.registry
        if path == reg.default_path:
            return self.default() if label == reg.default_id else None
        record = reg.by_path(path)
        if record is None:
            # An unregistered database that claims to be a registered run board is an identity error, not an unrelated board.
            claimed = reg.get(label) if label != DEFAULT_BOARD else None
            if claimed is not None:
                raise ConfigurationError('Board label %s is registered for %s but the database is %s; refusing to apply Factory policy to the wrong board'
                                         % (label, claimed.db_path, path))
            return None
        if label not in (DEFAULT_BOARD, record.board_id) and reg.get(label) is not None:
            raise ConfigurationError('Run board %s was addressed as board %s; refusing cross-board access' % (record.board_id, label))
        if record.status == 'failed':
            error, attempts = reg.error_of(record.board_id)
            raise ConfigurationError('Run board %s is failed (%d provisioning attempts): %s. Fix it, then run `factory_boards.py reset %s`.'
                                     % (record.board_id, attempts, error or 'no error recorded', record.board_id))
        if path != reg.expected_db_path(record.board_id):
            raise ConfigurationError('Run board %s is registered at %s, expected %s' % (record.board_id, path, reg.expected_db_path(record.board_id)))
        return record

    def for_label(self, label):
        """Resolve by Hermes board slug (dispatch ticks and completion hooks carry a slug, not a path)."""
        reg = self.registry
        if label in (None, '', DEFAULT_BOARD) or label == reg.default_id:
            return self.default()
        record = reg.get(label)
        return self.resolve(record.db_path, label) if record else None

    def governed(self, *, running_only=False):
        states = RUNNING if running_only else GOVERNED
        return [self.default(), *self.registry.list(states)]


def build_resolver(config, *, create=False):
    """Build the resolver from plugin settings (`board_path`, `board_id`, `snapshot_path`, optional `registry_path`, `boards_root`)."""
    default_path = Path(config['board_path'])
    registry_path = config.get('registry_path') or str(Path(config['snapshot_path']).parent / 'board-registry.db')
    boards_root = config.get('boards_root') or default_boards_root(default_path)
    if not create and not Path(registry_path).exists():
        # No registry yet: only the legacy default board is governed.
        return BoardResolver(_EmptyRegistry(registry_path, boards_root, default_path, config.get('board_id', DEFAULT_BOARD)))
    return BoardResolver(BoardRegistry(registry_path, boards_root, default_path, config.get('board_id', DEFAULT_BOARD), create=create))


class _EmptyRegistry(BoardRegistry):
    """Read-only stand-in before the first run board exists; it never creates a file."""

    def __init__(self, path, boards_root, default_board_path, default_board_id):
        self.path = Path(path)
        self.boards_root = Path(boards_root).resolve()
        self.default_path = Path(default_board_path).resolve()
        self.default_id = default_board_id

    def _open(self):
        if not self.path.exists():
            raise ConfigurationError('Board registry has not been created')
        return super()._open()

    def get(self, board_id):
        return None if not self.path.exists() else super().get(board_id)

    def by_path(self, db_path):
        return None if not self.path.exists() else super().by_path(db_path)

    def by_ticket(self, ticket_id, source_board_id=DEFAULT_BOARD):
        return None if not self.path.exists() else super().by_ticket(ticket_id, source_board_id)

    def list(self, statuses=None):
        return [] if not self.path.exists() else super().list(statuses)
