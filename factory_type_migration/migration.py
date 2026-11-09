"""Add a task type's roles, catalog entries, template and type default; reverse it. Every step is idempotent.

The dashboard source given to Migration must already contain the task type and its profiles; the template document
comes from that source's _preset(task_type), so the migration and fresh installs agree.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from dataclasses import dataclass

ALLOWED_PROVIDERS = ('anthropic', 'openai-codex', 'openrouter')


@dataclass(frozen=True)
class TypeSpec:
    task_type: str          # 'art'
    template_name: str      # 'Game Art'
    roles: dict             # role -> {'provider','model','effort'}
    choices_from: dict      # role -> existing role whose catalog choices it inherits
    schema: str             # 'factory-game-art' -> receipts f'{schema}-migration/v1', f'{schema}-rollback/v1'


def load_source(dashboard_source, spec):
    source = Path(dashboard_source).resolve(strict=True)
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from factory_dashboard import workflow_types
    if not Path(workflow_types.__file__).resolve().is_relative_to(source):
        raise ValueError(f'factory_dashboard is already loaded from {workflow_types.__file__}, not {source}')
    if spec.task_type not in workflow_types.TASK_TYPES or not set(spec.roles) <= set(workflow_types.CAPABILITIES):
        raise ValueError(f'{source} lacks the {spec.task_type} task type and roles; install the {spec.template_name} source edits first')
    from factory_dashboard.model_catalog import ModelCatalog
    from factory_dashboard.task_settings import RoleSettings
    from factory_dashboard.task_settings_store import TaskSettingsStore, encode
    from factory_dashboard.workflow_templates import WorkflowTemplates, _preset
    return SimpleNamespace(ModelCatalog=ModelCatalog, RoleSettings=RoleSettings, TaskSettingsStore=TaskSettingsStore,
                           encode=encode, WorkflowTemplates=WorkflowTemplates, preset=_preset)


def catalog_changes(catalog, spec):
    """Catalog entries for new roles: their default first, then the source role's choices minus Copilot."""
    changes = {}
    for role, settings in spec.roles.items():
        if role in catalog['profiles']:
            continue
        default = {'provider': settings['provider'], 'model': settings['model']}
        source = catalog['profiles'].get(spec.choices_from[role], {}).get('models', [])
        models = [dict(default, compatible=True)] + [
            dict(item) for item in source
            if item.get('provider') in ALLOWED_PROVIDERS and (item['provider'], item['model']) != tuple(default.values())]
        changes[role] = {'default': default, 'models': models}
    return changes


def profiles(document):
    return ({document[key]['profile'] for key in ('prepare', 'implement', 'verify', 'repair')}
            | {stage['profile'] for stage in document['reviewers']})


def write_atomic(path, text):
    path = Path(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def write_receipt(path, result):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')


class Migration:
    def __init__(self, spec, dashboard_source, settings_db, catalog_path):
        self.spec = spec
        self.m = load_source(dashboard_source, spec)
        self.store = self.m.TaskSettingsStore(settings_db, create=False)
        self.templates = self.m.WorkflowTemplates(self.store)
        self.catalog_path = Path(catalog_path)

    def _catalog(self):
        return json.loads(self.catalog_path.read_text())

    def _existing(self):
        return [doc for doc in self.templates.list() if doc['task_type'] == self.spec.task_type and doc['name'] == self.spec.template_name]

    def preview(self):
        defaults, mapping, existing = self.store.read_defaults(), self.templates.defaults(), self._existing()
        return {'catalog_add': sorted(catalog_changes(self._catalog(), self.spec)),
                'roles_add': sorted(role for role in self.spec.roles if role not in defaults.roles),
                'defaults_revision': defaults.revision,
                'template': existing[0]['template_id'] if existing else None,
                'type_default': mapping['templates'].get(self.spec.task_type)}

    def apply(self):
        receipt = {'schema': f'{self.spec.schema}-migration/v1', 'catalog_added': [], 'roles_added': [],
                   'template_created': None, 'type_default_set': None}
        # 1. Catalog first: the dashboard and the launch resolver validate every captured role against it.
        catalog = self._catalog()
        added = catalog_changes(catalog, self.spec)
        if added:
            catalog['profiles'].update(added)
            self.m.ModelCatalog(catalog)
            write_atomic(self.catalog_path, json.dumps(catalog, indent=2) + '\n')
            receipt['catalog_added'] = sorted(added)
        # 2. Role defaults, in one revision (save_default rejects unknown roles, so this is the only way in).
        receipt['roles_added'] = self._add_roles()
        # 3. The template, from the source preset, then 4. the type default.
        existing = self._existing()
        if existing:
            template_id = existing[0]['template_id']
        else:
            document = self.m.preset(self.spec.task_type)
            document.pop('template_id')
            document.pop('revision')
            template_id = self.templates.save(document, 0).template_id
            receipt['template_created'] = template_id
        mapping = self.templates.defaults()
        if self.spec.task_type not in mapping['templates']:
            self.templates.set_type_default(self.spec.task_type, template_id, mapping['revision'])
            receipt['type_default_set'] = template_id
        receipt['defaults_revision'] = self.store.read_defaults().revision
        return receipt

    def _add_roles(self):
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT revision, roles FROM factory_defaults WHERE id=1').fetchone()
            roles = json.loads(row['roles'])
            if not roles:
                raise ValueError('Factory defaults are not initialized; run the settings migration first')
            added = [role for role in self.spec.roles if role not in roles]
            for role in added:
                self.m.RoleSettings(**self.spec.roles[role])
                roles[role] = dict(self.spec.roles[role])
            if added:
                conn.execute('UPDATE factory_defaults SET revision=revision+1, roles=? WHERE id=1 AND revision=?',
                             (self.m.encode(roles), row['revision']))
            return added

    def rollback(self, purge=False):
        """Remove the type default and archive the template. Role rows and catalog entries stay (unused)."""
        result = {'schema': f'{self.spec.schema}-rollback/v1', 'type_default_removed': None, 'archived': [], 'purged': []}
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            mapping = self.templates.defaults(conn)
            if self.spec.task_type in mapping['templates']:
                templates = dict(mapping['templates'])
                result['type_default_removed'] = templates.pop(self.spec.task_type)
                conn.execute('UPDATE factory_workflow_defaults SET revision=revision+1, templates=? WHERE id=1 AND revision=?',
                             (self.m.encode(templates), mapping['revision']))
        for document in self._existing():
            self.templates.archive(document['template_id'], document['revision'])
            result['archived'].append(document['template_id'])
        if purge:
            result['purged'] = self._purge()
        return result

    def _purge(self):
        """Delete the type's template rows so older source can load the template list again; refused once used."""
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute('SELECT template_id, document FROM factory_workflow_revisions').fetchall()
            heads = conn.execute('SELECT r.template_id, r.document FROM factory_workflow_templates t '
                                 'JOIN factory_workflow_revisions r ON r.template_id=t.id AND r.revision=t.revision')
            # Only templates whose HEAD revision is this type; one that merely has an older revision of it stays.
            matching = {row['template_id'] for row in heads if json.loads(row['document'])['task_type'] == self.spec.task_type}
            blockers = []
            for row in rows:
                document = json.loads(row['document'])
                used = profiles(document) & set(self.spec.roles)
                if row['template_id'] not in matching and used:
                    blockers.append(f"template {document['name']!r} revision {document['revision']} uses {sorted(used)}")
            if conn.execute('SELECT 1 FROM factory_snapshots WHERE document LIKE ? LIMIT 1',
                            (f'%"task_type":"{self.spec.task_type}"%',)).fetchone():
                blockers.append(f'a captured task snapshot uses an {self.spec.task_type} workflow')
            if self.spec.task_type in self.templates.defaults(conn)['templates']:
                blockers.append(f'{self.spec.task_type} is still a type default')
            if blockers:
                raise ValueError('cannot purge: ' + '; '.join(blockers))
            for template_id in sorted(matching):
                conn.execute('DELETE FROM factory_workflow_revisions WHERE template_id=?', (template_id,))
                conn.execute('DELETE FROM factory_workflow_templates WHERE id=?', (template_id,))
            return sorted(matching)
