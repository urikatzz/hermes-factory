"""Workflow selection inside the same transaction as immutable model capture."""
from .model_policy import ConfigurationError
from .policy_store import RevisionConflict


class WorkflowCapture:
    def __init__(self, store, templates):
        self._store = store
        self._templates = templates
    def initialize(self):
        self._templates.initialize()
        with self._store._connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_activation(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL)')
            conn.execute('INSERT OR IGNORE INTO factory_workflow_activation VALUES(1,0)')

    def set_enabled(self, enabled):
        with self._store._connect() as conn:
            conn.execute('UPDATE factory_workflow_activation SET enabled=? WHERE id=1', (int(enabled),))

    @staticmethod
    def enabled(conn):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='factory_workflow_activation'").fetchone():
            return False
        return bool(conn.execute('SELECT enabled FROM factory_workflow_activation WHERE id=1').fetchone()[0])

    def preview(self, payload, conn=None):
        if conn is None:
            with self._store._connect() as c:
                return self.preview(payload, c)
        mapping = self._templates.defaults(conn)
        revision = payload.get('workflow_defaults_revision')
        if revision is not None and (type(revision) is not int or revision != mapping['revision']):
            raise RevisionConflict('Workflow defaults changed; refresh the preview')
        kind = payload.get('type', 'feature')
        if kind not in mapping['templates']:
            raise ConfigurationError('Unsupported task type')
        selected = payload.get('workflow_id')
        if bool(selected) != ('workflow_revision' in payload):
            raise ConfigurationError('Select both a workflow and its revision')
        definition = self._templates.get(selected or mapping['templates'][kind], conn=conn, active=True)
        if selected and (type(payload['workflow_revision']) is not int or payload['workflow_revision'] != definition.revision):
            raise RevisionConflict('Workflow changed; refresh the preview')
        roles = self._store._defaults(conn).roles
        stages = [definition.prepare, definition.implement, definition.verify, definition.repair, *definition.reviewers]
        if any(stage.profile not in roles for stage in stages):
            raise ConfigurationError('Workflow requires a profile without model settings')
        return definition

    def capture_submission(self, board, payload):
        return self._store.prepare_submission(board, payload)


def intake_selection(task):
    """Only the envelope selects a workflow; REQUEST remains opaque user text."""
    import json
    body = task.get('body') or ''
    if body.startswith(('FACTORY_TICKET v2\n', 'FACTORY_TICKET v3\n')):
        try:
            fields = json.loads(body.split('\n', 1)[1])
        except ValueError as exc:
            raise ConfigurationError('Invalid structured Factory ticket') from exc
        if not isinstance(fields, dict):
            raise ConfigurationError('Invalid structured Factory ticket')
        selection = {'type': fields.get('TYPE', 'feature')}
        if 'WORKFLOW' in fields:
            workflow = fields['WORKFLOW']
            if not isinstance(workflow, dict) or set(workflow) != {'id', 'revision'}:
                raise ConfigurationError('Invalid workflow selection')
            selection.update(workflow_id=workflow['id'], workflow_revision=workflow['revision'])
        return selection
    # Legacy control headers stop at the request block, including direct roots.
    selection = {'type': 'feature'}
    for line in body.splitlines():
        if line.startswith('REQUEST:'):
            break
        if line.startswith('TYPE:'):
            selection['type'] = line.partition(':')[2].strip()
    return selection
