"""Managed task policy, authorized only by a scoped in-process controller call."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from .model_policy import ConfigurationError
from .workflow_state import WorkflowState

_CONTROLLER = ContextVar('factory_workflow_controller', default=None)


@contextmanager
def controller_scope(conn, root_id, stage=None, cycle=0, evidence_retry=0):
    token = _CONTROLLER.set((conn, root_id, stage, cycle, evidence_retry))
    try:
        yield
    finally:
        _CONTROLLER.reset(token)


def controller_context(conn):
    context = _CONTROLLER.get()
    return context if context and context[0] is conn else None


class WorkflowGuards:
    def __init__(self, store, board_path, board_id):
        self._store = store
        self._path = Path(board_path).resolve()
        self._board = board_id
        self._state = WorkflowState()

    def before_mutation(self, conn, operation, task_id, proposed, board, board_path):
        if Path(board_path).resolve() != self._path or (board or 'default') != self._board:
            return
        self._check(conn,operation,task_id,proposed)
        return 'factory-workflow/v1'

    def _check(self,conn,operation,task_id,proposed):
        root = self._state.read_root(conn, task_id)
        stage = self._state.stage_for_task(conn, task_id)
        if not root and not stage:
            if operation in ('link_tasks', 'unlink_tasks') and self._state.read_root(conn, proposed['parent_id']):
                raise ConfigurationError('workflow dependencies belong to the controller')
            return
        root_id = task_id if root else stage['root_id']
        context = controller_context(conn)
        if context and context[1] == root_id:
            return
        if operation == 'created':
            if root:
                conn.execute("UPDATE tasks SET status='blocked',block_kind='dependency' WHERE id=?", (task_id,))
                from hermes_cli.kanban_db import _append_event
                _append_event(conn,task_id,'blocked',{'reason':'Captured workflow controller owns progression'})
            return
        if operation == 'edit_task' and all(proposed.get(k) is None for k in ('body','result','summary','metadata')):
            return
        if stage:
            self._guard_stage(conn, operation, task_id, proposed, stage)
            return
        raise ConfigurationError('workflow root is controlled by its captured stages')

    def _guard_stage(self, conn, operation, task_id, proposed, stage):
        root = self._state.read_root(conn, stage['root_id'])
        task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        phase_kind = {'preparing':'prepare','implementing':'implement','reviewing':stage['kind'] if stage['kind'] in ('review','verify') else None,'repairing':'repair'}.get(root['phase'])
        current = stage['cycle'] == root['cycle'] and phase_kind == stage['kind'] and task['assignee'] == stage['profile']
        newest = conn.execute('SELECT MAX(evidence_retry) FROM factory_workflow_stages WHERE root_id=? AND stage_key=? AND cycle=?', (stage['root_id'],stage['stage_key'],stage['cycle'])).fetchone()[0]
        current = current and newest == stage['evidence_retry']
        if not current:
            raise ConfigurationError('workflow stage is no longer current')
        if operation == 'claimed':
            conn.execute('UPDATE factory_workflow_stages SET active_run_id=? WHERE task_id=?', (proposed['run_id'],task_id))
            return
        if operation in ('claim_task','claim_review_task','reclaim_task','block_task','schedule_task'):
            return
        if operation == 'complete_task' and proposed.get('expected_run_id') is not None and proposed['expected_run_id'] == task['current_run_id']:
            run = conn.execute('SELECT profile,claim_lock FROM task_runs WHERE id=?', (task['current_run_id'],)).fetchone()
            if run and run['profile'] == stage['profile'] and run['claim_lock']:
                return
        raise ConfigurationError('workflow stage mutation would bypass captured execution')
