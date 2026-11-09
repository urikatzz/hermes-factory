"""Validated task submissions with durable recovery, independent of presentation."""
from dataclasses import asdict
import uuid
from .model_policy import ConfigurationError
from .policy_store import RevisionConflict
from .workflow_types import TASK_TYPES

class TaskSubmissionService:
    def __init__(self,store,adapter,board,validate_roles):
        self._store=store;self._adapter=adapter;self._board=board;self._validate_roles=validate_roles

    def _validate(self,payload):
        keys={'submission_id','defaults_revision','title','project','type','prompt','acceptance'}
        if not keys <= set(payload) or set(payload) - keys - {'workflow_id','workflow_revision','workflow_defaults_revision'}:raise ConfigurationError('Invalid submission fields')
        try:
            if str(uuid.UUID(payload['submission_id']))!=payload['submission_id']:raise ValueError()
        except (ValueError,TypeError,AttributeError):raise ConfigurationError('Invalid submission identity')
        for key in ('title','project','type','prompt','acceptance'):
            if not isinstance(payload[key],str) or '\x00' in payload[key]:raise ConfigurationError('Invalid task text')
        if not payload['title'].strip() or len(payload['title'])>200 or any(x in payload['title'] for x in '\r\n'):raise ConfigurationError('Title must be one line, 1–200 characters')
        if not payload['prompt'].strip() or len(payload['prompt'])+len(payload['acceptance'])>12000:raise ConfigurationError('Request and acceptance must total 1–12,000 characters')
        if payload['type'] not in TASK_TYPES:raise ConfigurationError('Invalid task type')
        if payload['project'] not in {p['id'] for p in self._adapter.list_projects()}:raise ConfigurationError('Project is no longer available')

    def preview(self,payload):
        self._validate(payload);defaults=self._store.read_defaults()
        if type(payload['defaults_revision']) is not int or payload['defaults_revision']!=defaults.revision:raise RevisionConflict('Defaults changed; review settings again')
        self._validate_roles(defaults.roles)
        result = {'revision':defaults.revision,'roles':{k:asdict(v) for k,v in defaults.roles.items()}}
        from .workflow_capture import WorkflowCapture
        from .workflow_templates import WorkflowTemplates
        with self._store._connect() as conn:
            if WorkflowCapture.enabled(conn):
                templates = WorkflowTemplates(self._store)
                result['workflow'] = asdict(WorkflowCapture(self._store, templates).preview(payload, conn))
                result['workflow_defaults_revision'] = templates.defaults(conn)['revision']
        return result

    def submit(self,payload):
        if not self._store.read_activation()['enabled']:raise ConfigurationError('Task submission is disabled until snapshot enforcement is active')
        existing=self._store.read_submission(self._board,payload.get('submission_id'))
        if not existing:self.preview(payload)
        record=self._store.prepare_submission(self._board,payload)
        ticket=self._adapter.lookup_ticket(payload['submission_id'])
        if not ticket:
            try:ticket=self._adapter.create_ticket(payload,payload['submission_id'])
            except Exception:
                ticket=self._adapter.lookup_ticket(payload['submission_id'])
                if not ticket:raise
        self._store.bind_task(self._board,ticket,record['snapshot_id'],'ticket',payload['submission_id'])
        return {'submission_id':payload['submission_id'],'ticket_id':ticket,'snapshot_id':record['snapshot_id'],'state':'queued'}

    def cancel(self, identity):
        record = self._store.read_submission(self._board, identity)
        if not record:
            raise ConfigurationError('Submission not found')
        ticket = self._adapter.cancel_unqueued(identity, lambda: self._store.cancel_submission(self._board, identity))
        if ticket:
            self._store.bind_task(self._board, ticket, record['snapshot_id'], 'ticket', identity)
        return self.status(identity)

    def status(self,identity):
        record=self._store.read_submission(self._board,identity)
        if not record:raise ConfigurationError('Submission not found')
        ticket=self._adapter.lookup_ticket(identity)
        root=self._adapter.lookup_root(ticket) if ticket else None
        return {'submission_id':identity,'ticket_id':ticket,'root_id':root,'snapshot_id':record['snapshot_id'],'state':'created' if root else 'queued' if ticket else 'cancelled' if record['cancelled'] else 'prepared'}
