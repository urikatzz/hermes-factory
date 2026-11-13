"""Application operations shared by HTTP and integration tests."""
from dataclasses import asdict
from .model_policy import ConfigurationError, ModelPolicy
from .policy_store import RevisionConflict


class LiveService:
    def __init__(self, collector, builder, policy_store, model_catalog, board_identity):
        self._collector = collector
        self._builder = builder
        self._store = policy_store
        self._catalog = model_catalog
        self._board = board_identity

    def initialize_defaults(self):
        for role, selection in self._catalog.defaults().items():
            current = self._store.read()
            if role not in current.defaults:
                self._store.set_default(role, selection, current.revision)

    def _report(self):
        return self._builder.build(self._collector.collect())

    @staticmethod
    def _roles(root):
        return tuple(sorted({t['assignee'] for t in [root, *root.get('stages', [])] if t.get('assignee')}))

    def _root(self, root_id, report):
        for root in report['parents']:
            if root['id'] == root_id and root['status'] != 'archived':
                return root
        raise ConfigurationError('Task does not exist or is archived')

    def configuration(self, report=None):
        report = report if report is not None else self._report()
        snapshot = self._store.read()
        tasks = {}
        for root in report['parents']:
            roles = self._roles(root)
            entry = {'roles': roles, 'override': asdict(snapshot.overrides[self._board,root['id']]) if (self._board,root['id']) in snapshot.overrides else None,
                     'effective': {}, 'choices': [], 'editable': root['status'] != 'archived'}
            try:
                entry['choices'] = [asdict(x) for x in self._catalog.choices(roles)]
                entry['effective'] = {role: asdict(ModelPolicy.resolve(snapshot,self._board,root['id'],role)) for role in roles}
            except ConfigurationError as error:
                entry['error'] = str(error)
                entry['editable'] = False
            tasks[root['id']] = entry
        return {'revision': snapshot.revision, 'defaults': {role:asdict(x) for role,x in snapshot.defaults.items()},
                'role_choices': {role:[asdict(x) for x in self._catalog.choices((role,))] for role in self._catalog.defaults()},
                'tasks': tasks, 'mode': 'Preview configuration — live scheduler activation is separate'}

    def report(self):
        report = self._report()
        report['configuration'] = self.configuration(report)
        return report

    def save_default(self, role, selection, revision):
        report = self._report()
        self._catalog.validate(selection, (role,))
        self._store.set_default(role, selection, revision)
        return self.configuration(report)

    def save_override(self, root_id, selection, revision):
        report = self._report()
        root = self._root(root_id, report)
        if selection is not None:
            self._catalog.validate(selection, self._roles(root))
        self._store.set_override(self._board, root_id, selection, revision)
        return self.configuration(report)
