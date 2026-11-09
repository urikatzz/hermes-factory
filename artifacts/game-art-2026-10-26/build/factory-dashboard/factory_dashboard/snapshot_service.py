"""Read-only run evidence and defaults that apply only to newly captured tasks."""
from dataclasses import asdict
import json
from .model_policy import ConfigurationError
from .task_settings import EFFORTS, RoleSettings


class SnapshotService:
    def __init__(self, report_service, store, catalog, board_identity, submissions, intake):
        self._reports = report_service
        self._store = store
        self._catalog = catalog
        self._board = board_identity
        self._submissions = submissions
        self._intake = intake

    def initialize_defaults(self):
        pass  # Only the explicit migration may initialize this store.

    def defaults(self):
        defaults = self._store.read_defaults()
        return {'revision': defaults.revision, 'roles': {k: asdict(v) for k, v in defaults.roles.items()},
                'effort_choices': list(EFFORTS), 'activation': self._store.read_activation(),
                'role_choices': {k: [asdict(v) for v in self._catalog.choices((k,))] for k in defaults.roles}}

    def configuration(self, report=None):
        data = self.defaults()
        return {**data, 'defaults': data['roles'], 'tasks': {}, 'snapshot_mode': True,
                'mode': 'Settings are frozen per task. Defaults apply only to new tasks.' if data['activation']['enabled']
                else 'Read-only preview · snapshot enforcement is not yet active'}

    def report(self):
        report = self._reports.report()
        report['configuration'] = self.configuration()
        for root in report['parents']:
            snapshot = self._store.snapshot_for_task(self._board, root['id'])
            if snapshot:
                root['requested_settings'] = {'snapshot_id': snapshot.id, 'origin': snapshot.origin,
                    'captured_at': snapshot.created_at, 'revision': snapshot.defaults_revision,
                    'roles': {k: asdict(v) for k, v in snapshot.roles.items()}}
        report['submissions'] = []
        for row in self._store.list_submissions(self._board):
            payload = json.loads(row['payload'])
            status = self._submissions.status(row['submission_id'])
            if status['state'] == 'cancelled':
                continue
            report['submissions'].append({**status, 'title': payload.get('title', 'Factory task')})
        return report

    def save_default(self, role, selection, revision, effort):
        if not self._store.read_activation()['enabled']:
            raise ConfigurationError('Defaults are read-only until snapshot enforcement is active')
        self._catalog.validate(selection, (role,))
        self._store.save_default(role, RoleSettings(selection.provider, selection.model, effort), revision)
        return self.defaults()

    def save_override(self, *args):
        raise ConfigurationError('Task settings are immutable. Change defaults for new tasks instead.')

    def save_profile(self, *args):
        raise ConfigurationError('Shared profile editing is retired. Use defaults for new Factory tasks.')

    def projects(self):
        return self._intake.list_projects()

    def preview_submission(self, payload):
        return self._submissions.preview(payload)

    def submit(self, payload):
        return self._submissions.submit(payload)

    def submission_status(self, identity):
        return self._submissions.status(identity)

    def cancel_submission(self, identity):
        return self._submissions.cancel(identity)
