"""Idempotent provisioning and lifecycle operations for dedicated Factory run boards.

Provisioning is a short state machine kept in the registry: reserve -> create Hermes board -> initialize schema -> activate.
Every step is safe to repeat, so a crash or retry at any point converges on exactly one board per ticket. A board that keeps
failing is marked `failed` and fails closed until an operator resets it.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .board_registry import BoardRegistry, BoardResolver, FactoryBoard
from .model_policy import ConfigurationError


class ProvisionError(ConfigurationError):
    pass


def describe_root(conn, root_id):
    """Workflow phase and approval state of one root on a read-only board connection; {} when the board has no workflow state."""
    conn.row_factory = sqlite3.Row
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='factory_workflow_roots'").fetchone():
        return {}
    state = conn.execute('SELECT phase, cycle, reason FROM factory_workflow_roots WHERE root_id=?', (root_id,)).fetchone()
    if not state:
        return {}
    result = dict(phase=state['phase'], cycle=state['cycle'], reason=state['reason'])
    project = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='factory_project_execution'").fetchone():
        row = conn.execute('SELECT document FROM factory_project_execution WHERE root_id=?', (root_id,)).fetchone()
        project = json.loads(row[0]) if row else None
    # Same rule as the Kanban board's "Awaiting approval" column.
    result['awaiting'] = bool((project and project.get('awaiting') and not project.get('terminal')) or state['phase'] == 'human_review')
    if project:
        result['project_mode'] = project.get('mode')
        result['active_stages'] = list(project.get('active_keys', []))
    return result


class HermesBoards:
    """The only place the Factory touches Hermes' board API; replaceable in tests."""

    def create(self, slug, name, description):
        from hermes_cli import kanban_db_boards
        return kanban_db_boards.create_board(slug, name=name, description=description)

    def db_path(self, slug):
        from hermes_cli import kanban_db
        return kanban_db.kanban_db_path(board=slug)

    def connect(self, path, slug):
        from hermes_cli import kanban_db_connect
        return kanban_db_connect.connect(Path(path), board=slug)

    def archive(self, slug):
        from hermes_cli import kanban_db_boards
        return kanban_db_boards.remove_board(slug, archive=True)

    def board_api(self):
        from hermes_cli import kanban_db
        return kanban_db


class RunBoards:
    def __init__(self, registry: BoardRegistry, hermes=None):
        self.registry = registry
        self.hermes = hermes or HermesBoards()
        self.resolver = BoardResolver(registry)

    # ---- provisioning
    def provision(self, ticket_id, *, name='', project_id='', workflow_id='', project_dir='', branch='') -> FactoryBoard:
        """Create (or return) the one run board of a ticket. Safe to call any number of times, from any process."""
        record = self.registry.begin(ticket_id, name=name, project_id=project_id, workflow_id=workflow_id, project_dir=project_dir, branch=branch)
        if record.status in ('cancelled', 'archived'):
            raise ProvisionError('Run board %s for ticket %s is %s; a new ticket is required' % (record.board_id, ticket_id, record.status))
        if record.status == 'failed':
            error, attempts = self.registry.error_of(record.board_id)
            raise ProvisionError('Run board %s failed after %d attempts: %s. Fix the cause, then `factory_boards.py reset %s`.' % (record.board_id, attempts, error, record.board_id))
        if record.status in ('active', 'paused') and record.db_path.is_file():
            return record
        try:
            self.hermes.create(record.board_id, (record.name or ticket_id)[:80], 'Factory run for ticket %s (%s)' % (ticket_id, project_id or 'no project'))
            path = Path(self.hermes.db_path(record.board_id)).resolve()
            if path != record.db_path:
                raise ConfigurationError('Hermes resolved board %s to %s, but the registry expects %s' % (record.board_id, path, record.db_path))
            from .workflow_state import WorkflowState
            with closing(self.hermes.connect(path, record.board_id)) as conn:
                with conn:
                    WorkflowState().initialize(conn)
            return self.registry.mark_active(record.board_id) if record.status == 'provisioning' else record
        except Exception as exc:
            failed = self.registry.record_failure(record.board_id, '%s: %s' % (type(exc).__name__, exc))
            raise ProvisionError('Provisioning run board %s failed (attempt %d, status %s): %s' % (record.board_id, self.registry.error_of(record.board_id)[1], failed.status, exc)) from exc

    def bind_root(self, board: FactoryBoard, root_id):
        return self.registry.set_root(board.board_id, root_id)

    # ---- inspection
    def summary(self, board: FactoryBoard):
        """One run board's status for dashboards: stage, blockers, approvals, cost. Reads only; never mutates the board."""
        path = board.db_path
        if board.status == 'archived' and dict(board.meta).get('archived_path'):
            path = Path(dict(board.meta)['archived_path']) / 'kanban.db'
        result = dict(board.public(), counts={}, phase='', reason='', awaiting=False, needs_intervention=False, blockers=[], stages=[], available=False)
        if not Path(path).is_file():
            return result
        with closing(sqlite3.connect('file:' + quote(str(Path(path).resolve())) + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            result['available'] = True
            result['counts'] = {r['status']: r['n'] for r in conn.execute('SELECT status, COUNT(*) n FROM tasks GROUP BY status')}
            root = conn.execute("SELECT id, title, status, result FROM tasks WHERE title LIKE 'FACTORY:%' ORDER BY created_at LIMIT 1").fetchone()
            if root:
                result['root'] = dict(root)
            if root:
                result.update(describe_root(conn, root['id']))
            # The root card is always "blocked" while the controller owns it; only other blocked cards, or a stopped phase, are blockers.
            root_id = root['id'] if root else ''
            result['blockers'] = [dict(r) for r in conn.execute("SELECT id, title, block_kind, result FROM tasks WHERE status='blocked' AND id != ? ORDER BY created_at LIMIT 20", (root_id,))]
            if result['phase'] in ('blocked', 'human_review') and root:
                result['blockers'].insert(0, dict(id=root_id, title=root['title'], block_kind='needs_input', result=result['reason']))
            result['needs_intervention'] = bool(result['blockers']) and not result['awaiting'] and not (root and root['status'] == 'done')
            result['stages'] = [dict(r) for r in conn.execute("SELECT id, title, status, assignee FROM tasks WHERE status IN ('ready','running','review','scheduled') ORDER BY created_at LIMIT 20")]
        return result

    # ---- lifecycle
    def _with_board(self, board_id, allowed, action):
        board = self.registry.get(board_id)
        if board is None:
            raise ConfigurationError('Unknown run board: ' + board_id)
        if board.status not in allowed:
            raise ConfigurationError('Cannot %s run board %s while it is %s' % (action, board_id, board.status))
        return board

    def _scoped(self, conn, board):
        from .workflow_guards import controller_scope
        if not board.root_id:
            raise ConfigurationError('Run board %s has no root yet' % board.board_id)
        return controller_scope(conn, board.root_id)

    def pause(self, board_id, reason='paused by operator'):
        """Stop new work: park every queued stage card and stop reconciling. Workers already running finish their attempt."""
        board = self._with_board(board_id, ('active',), 'pause')
        kb = self.hermes.board_api()
        parked = []
        with closing(self.hermes.connect(board.db_path, board.board_id)) as conn:
            with self._scoped(conn, board):
                for row in conn.execute("SELECT id FROM tasks WHERE status IN ('todo','ready') AND id != ?", (board.root_id,)).fetchall():
                    if kb.schedule_task(conn, row['id'], reason=reason):
                        parked.append(row['id'])
        self.registry.set_status(board_id, 'paused', paused_cards=parked, pause_reason=reason)
        return parked

    def resume(self, board_id):
        board = self._with_board(board_id, ('paused',), 'resume')
        kb = self.hermes.board_api()
        meta = dict(board.meta)
        restored = []
        with closing(self.hermes.connect(board.db_path, board.board_id)) as conn:
            with self._scoped(conn, board):
                for task_id in meta.get('paused_cards', []):
                    row = conn.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
                    if row and row['status'] == 'scheduled' and kb.unblock_task(conn, task_id):
                        restored.append(task_id)
        self.registry.set_status(board_id, 'active', paused_cards=[], pause_reason='')
        return restored

    def cancel(self, board_id, reason='cancelled by operator'):
        """Stop this run for good: block its open cards and the workflow root. Other boards are untouched."""
        board = self._with_board(board_id, ('provisioning', 'active', 'paused'), 'cancel')
        if board.root_id:
            kb = self.hermes.board_api()
            from .workflow_controller import WorkflowController
            from .workflow_state import WorkflowState
            state = WorkflowState()
            with closing(self.hermes.connect(board.db_path, board.board_id)) as conn:
                with self._scoped(conn, board):
                    for row in conn.execute("SELECT id, status, current_run_id FROM tasks WHERE status IN ('todo','ready','running','scheduled','review') AND id != ?", (board.root_id,)).fetchall():
                        if row['status'] == 'scheduled':
                            kb.unblock_task(conn, row['id'])
                        kb.block_task(conn, row['id'], reason='Run cancelled: ' + reason, kind='needs_input')
                    root = state.read_root(conn, board.root_id)
                    if root:
                        with conn:
                            WorkflowController(kb, state, '.')._stop(conn, root, 'blocked', 'Run cancelled: ' + reason)
        self.registry.set_status(board_id, 'cancelled', cancel_reason=reason)

    def archive(self, board_id):
        """Move a finished/cancelled/failed run board out of the dispatcher's sight; history stays readable."""
        board = self.registry.get(board_id)
        if board is None:
            raise ConfigurationError('Unknown run board: ' + board_id)
        if board.status == 'archived':
            return dict(board.meta)
        summary = self.summary(board)
        finished = board.status in ('cancelled', 'failed') or summary['phase'] == 'delivered' or summary.get('root', {}).get('status') == 'done'
        if not finished or summary['counts'].get('running'):
            raise ConfigurationError('Run board %s is still in progress (%s); cancel it before archiving' % (board_id, board.status))
        moved = self.hermes.archive(board_id) if board.db_path.parent.is_dir() else {}
        self.registry.set_status(board_id, 'archived', archived_path=str(moved.get('new_path') or ''))
        return moved
