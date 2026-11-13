"""Dashboard operations for future workflows and read-only captured definitions."""
from dataclasses import asdict
from .model_policy import ConfigurationError
from .workflow_types import CAPABILITIES


class WorkflowService:
    def __init__(self, templates, capture, store, readiness):
        self._templates=templates
        self._capture=capture
        self._store=store
        self._readiness=readiness

    def list(self):
        with self._store._connect() as conn:
            enabled=self._capture.enabled(conn)
        readiness=self._readiness()
        return dict(templates=self._templates.list(True),defaults=self._templates.defaults(),capabilities=CAPABILITIES,
                    enabled=enabled and readiness.get('ready',False),readiness=readiness)

    def require_execution(self,payload):
        with self._store._connect() as conn:
            active=self._capture.enabled(conn)
        explicit=any(k in payload for k in ('workflow_id','workflow_revision','workflow_defaults_revision'))
        if explicit and not active:
            raise ConfigurationError('Workflow execution is not enabled; reload settings')
        if active and not self._readiness().get('ready',False):
            raise ConfigurationError('Workflow enforcement is unavailable; new submissions are disabled')

    def get(self, template_id, revision=None):
        return asdict(self._templates.get(template_id,revision))

    def save(self, document, expected_revision):
        available=self._store.read_defaults().roles
        if document.get('execution_version', 1) == 2:
            from .project_policy import V2_PROFILES
            if set(V2_PROFILES) - available.keys():
                raise ConfigurationError('Project workflow profiles are not configured')
        stages=[document.get(k,{}) for k in ('prepare','implement','verify','repair')]+list(document.get('reviewers',[]))
        if any(not isinstance(s,dict) or s.get('profile') not in available for s in stages):
            raise ConfigurationError('Workflow profile has no configured model settings')
        return asdict(self._templates.save(document,expected_revision))

    def archive(self, template_id, revision):
        self._templates.archive(template_id,revision)
        return self.list()

    def restore(self, template_id, revision):
        self._templates.restore(template_id,revision)
        return self.list()

    def set_default(self, task_type, template_id, revision):
        return self._templates.set_type_default(task_type,template_id,revision)

    def preview(self, payload):
        if set(payload)-{'type','workflow_id','workflow_revision','workflow_defaults_revision'}:
            raise ConfigurationError('Invalid workflow preview fields')
        return dict(workflow=asdict(self._capture.preview(payload)),defaults=self._templates.defaults())


class WorkflowDashboard:
    def __init__(self, dashboard, workflows, store, board_identity, read_state):
        self._dashboard=dashboard
        self.workflows=workflows
        self._store=store
        self._board=board_identity
        self._read_state=read_state

    def __getattr__(self, name):
        return getattr(self._dashboard,name)

    def preview_submission(self,payload):
        self.workflows.require_execution(payload)
        return self._dashboard.preview_submission(payload)

    def submit(self,payload):
        record=self._store.read_submission(self._board,payload.get('submission_id'))
        queued=record and self._dashboard.submission_status(payload['submission_id']).get('ticket_id')
        if not queued:
            self.workflows.require_execution(payload)
        return self._dashboard.submit(payload)

    def report(self):
        report=self._dashboard.report()
        report['configuration']['workflow_templates']=True
        for root in report['parents']:
            snapshot=self._store.snapshot_for_task(self._board,root['id'])
            root['workflow']=dict(label='Legacy workflow',legacy=True)
            if snapshot and snapshot.workflow:
                definition=asdict(snapshot.workflow)
                root['workflow']=dict(legacy=False,definition=definition,state=self._read_state(root['id']))
        return report
