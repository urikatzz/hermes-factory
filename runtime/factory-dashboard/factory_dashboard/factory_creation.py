"""Bind Factory settings before a board task can become dispatchable."""
from pathlib import Path
import re
from .factory_model_resolver import board_key
from .task_identity import is_root
from .model_policy import ConfigurationError
from .workflow_capture import intake_selection

class FactoryCreation:
    def __init__(self,store,board_path,board_id,*,run=None,registry=None):
        # run: the registered FactoryBoard when this is a dedicated run board; registry: used to refuse a duplicate root on the source board.
        self._store=store;self._path=Path(board_path).resolve();self._board=board_id;self._run=run;self._registry=registry

    def prepare_creation(self,task,board_path,board,conn=None):
        if Path(board_path).resolve()!=self._path or (board or 'default')!=self._board:return
        from .workflow_guards import controller_context
        from .workflow_state import WorkflowState
        context = controller_context(conn) if conn is not None else None
        state = WorkflowState()
        creator = task.get('creator_task_id')
        if conn is not None and creator and (state.read_root(conn, creator) or state.stage_for_task(conn, creator)) and not context:
            raise ConfigurationError('workflow stages must be created by the controller')
        identity=board_key(self._path,self._board);key=task.get('idempotency_key') or ''
        # A run board's snapshots were captured under its ticket board; only that source board may be named.
        source=self._run.source_identity if self._run is not None else None
        if context and context[2]:
            root_id, stage, cycle, retry = context[1:]
            snapshot = self._store.snapshot_for_task(identity, root_id)
            self._store.bind_task(identity, task['id'], snapshot.id, 'stage', source_board=source)
            state.register_stage(conn, task['id'], root_id, stage, cycle, retry)
            return
        run=self._run
        if run is not None:
            if key.startswith('factory-submit-') or (task.get('title') or '').startswith('TICKET:'):
                raise ConfigurationError('Run board %s hosts only its own root and stages; tickets belong on the intake board' % run.board_id)
            if is_root(task) and key!='intake-'+run.ticket_id:
                raise ConfigurationError('Run board %s serves ticket %s only; refusing root with key %r' % (run.board_id,run.ticket_id,key))
        elif key.startswith('intake-') and self._registry is not None:
            existing=self._registry.by_ticket(key.removeprefix('intake-'),self._board)
            if existing is not None:
                raise ConfigurationError('Ticket %s already has run board %s (%s); refusing a duplicate root on the intake board' % (existing.ticket_id,existing.board_id,existing.status))
        if key.startswith('factory-submit-'):
            submission=self._store.read_submission(identity,key.removeprefix('factory-submit-'))
            if not submission or submission['cancelled']:raise ConfigurationError('Prepared submission is missing or cancelled')
            # Finalize the submission ticket only after the board commit succeeds.
            self._store.bind_task(identity,task['id'],submission['snapshot_id'],'ticket')
        elif is_root(task):
            if key.startswith('intake-'):
                ticket_board=run.source_identity if run is not None else identity
                snapshot=self._store.snapshot_for_task(ticket_board,key.removeprefix('intake-'))
                if not snapshot:raise ConfigurationError('Intake ticket snapshot is missing')
                self._store.bind_task(identity,task['id'],snapshot.id,'root',source_board=ticket_board if run is not None else None)
            else:self._store.capture_task(identity,task['id'],'direct_root',workflow_selection=intake_selection(task))
        elif task.get('created_by')=='factory-ticket' or (task.get('title') or '').startswith('TICKET:'):
            self._store.capture_task(identity,task['id'],'submission',workflow_selection=intake_selection(task))
        else:
            title=task.get('title') or ''
            matches=[re.match(r'^\[(t_[0-9a-f]+)\]\s',title),re.search(r'\((t_[0-9a-f]+)\)\s*$',title)]
            parents={m[1] for m in matches if m}
            if len(parents)>1:raise ConfigurationError('Ambiguous Factory parent')
            if task.get('creator_task_id'):parents.add(task['creator_task_id'])
            snapshots={s.id:s for pid in parents if (s:=self._store.snapshot_for_task(identity,pid))}
            if len(snapshots)>1:raise ConfigurationError('Conflicting Factory snapshots')
            snapshots = {sid:s for sid,s in snapshots.items() if s.workflow is None}
            if snapshots:self._store.bind_task(identity,task['id'],next(iter(snapshots)),'stage',source_board=source)

        snapshot = self._store.snapshot_for_task(identity, task['id'])
        if snapshot and snapshot.workflow and is_root(task):
            if conn is None:
                raise ConfigurationError('workflow requires transactional creation hooks')
            from .workflow_types import WorkflowBinding
            state.ensure_root(conn, task['id'], WorkflowBinding(snapshot.id, snapshot.workflow))
