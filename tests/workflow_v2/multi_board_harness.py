"""A disposable Hermes home with the real bundled Factory plugin, real boards and a real dispatcher; never launches a model."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from contextlib import ExitStack
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'runtime/factory-dashboard'))
sys.path.insert(0, str(REPO / 'scripts'))
sys.path.append(str(Path.home() / '.hermes/hermes-agent'))

MODELS = {'a': ('test', 'model-a'), 'b': ('test', 'model-b')}


class Factory:
    def __init__(self, directory, default_model='a'):
        self.home = Path(directory).resolve()
        os.environ['HERMES_HOME'] = str(self.home)
        os.environ['HERMES_KANBAN_HOME'] = str(self.home)
        os.environ['HERMES_RUNTIME_DIR'] = str(self.home / 'runtime')
        for pin in ('HERMES_KANBAN_DB', 'HERMES_KANBAN_BOARD', 'HERMES_KANBAN_WORKSPACES_ROOT'):
            os.environ.pop(pin, None)
        from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, plugins
        self.kb, self.kbc, self.plugins = kb, kbc, plugins
        from factory_dashboard.task_settings_store import TaskSettingsStore
        from factory_dashboard.task_settings import RoleSettings
        from factory_dashboard.workflow_capture import WorkflowCapture
        from factory_dashboard.workflow_templates import WorkflowTemplates
        from factory_dashboard.project_policy import V2_PROFILES
        from install_project_workflows import activate_templates
        self.RoleSettings, self.profiles = RoleSettings, V2_PROFILES
        (self.home / 'state/factory').mkdir(parents=True)
        for profile in V2_PROFILES:
            (self.home / 'profiles' / profile).mkdir(parents=True)
            (self.home / 'profiles' / profile / 'config.yaml').write_text('model: {}\n')
        self.store = TaskSettingsStore(self.home / 'state/factory/task-settings.db')
        provider, model = MODELS[default_model]
        self.store.seed_defaults({p: RoleSettings(provider, model, 'high') for p in V2_PROFILES})
        capture = WorkflowCapture(self.store, WorkflowTemplates(self.store))
        capture.initialize(); capture.set_enabled(True)
        activate_templates(self.store)
        catalog = {'profiles': {p: {'default': dict(provider='test', model='model-a'),
                                    'models': [dict(provider='test', model='model-a'), dict(provider='test', model='model-b')]} for p in V2_PROFILES}}
        (self.home / 'state/factory/model-catalog.json').write_text(json.dumps(catalog))
        self.default_path = kb.init_db(board='default')
        self.settings = dict(board_path=str(self.default_path), board_id='default', snapshot_path=str(self.store.path),
                             catalog_path=str(self.home / 'state/factory/model-catalog.json'), new_project_root=str(self.home / 'projects'))
        self.load_plugin()

    # ---- plugin lifecycle (a "gateway restart" is a second load_plugin with all in-memory state discarded)
    def load_plugin(self):
        bundle_spec = importlib.util.spec_from_file_location('multi_bundle_builder', REPO / 'runtime/factory-dashboard/scripts/bundle_factory_plugin.py')
        bundler = importlib.util.module_from_spec(bundle_spec); bundle_spec.loader.exec_module(bundler)
        self.generation = getattr(self, 'generation', 0) + 1
        out = bundler.bundle_plugin(self.home / ('bundle%d' % self.generation))
        name = 'factory_models_plugin_%d' % self.generation
        spec = importlib.util.spec_from_file_location(name, out / '__init__.py', submodule_search_locations=[str(out)])
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
        self.package = name
        self.callbacks = {}
        settings, callbacks = self.settings, self.callbacks

        class Context:
            def get_config(self, key, default=None): return settings.get(key, default)
            def register_hook(self, hook, callback): callbacks[hook] = callback
        module.register(Context())
        self.module = module
        mod = lambda path: importlib.import_module('%s.factory_dashboard.%s' % (name, path))
        self.mod = mod
        self.WorkflowController = mod('workflow_controller').WorkflowController
        self.WorkflowState = mod('workflow_state').WorkflowState
        self.registry_module = mod('board_registry')
        self.boards_module = mod('run_boards')
        self.resolver = self.registry_module.build_resolver(self.settings, create=True)
        self.registry = self.resolver.registry
        self.run_boards = self.boards_module.RunBoards(self.registry)

    def hooks(self):
        stack = ExitStack()
        stack.enter_context(patch.object(self.plugins, 'has_hook', lambda hook: hook in self.callbacks))
        stack.enter_context(patch.object(self.plugins, 'iter_hook_callbacks', lambda hook: [self.callbacks[hook]] if hook in self.callbacks else []))
        stack.enter_context(patch.object(self.kb, '_fire_task_hook'))
        return stack

    # ---- boards and cards
    def conn(self, board):
        path = self.default_path if board == 'default' else self.registry.get(board).db_path
        return self.kbc.connect(path, board=board)

    def ticket(self, title, kind='feature', model=None):
        """A triage ticket on the intake board; it captures the current defaults as its immutable snapshot."""
        if model:
            defaults = self.store.read_defaults()
            for role in self.profiles:
                defaults = self.store.save_default(role, self.RoleSettings(*MODELS[model], 'high'), defaults.revision)
        body = 'FACTORY_TICKET v2\n' + json.dumps({'PROJECT': 'new', 'TYPE': kind, 'ACCEPTANCE': 'none', 'REQUEST': title})
        with self.conn('default') as conn:
            return self.kb.create_task(conn, title='TICKET: ' + title, body=body, triage=True, created_by='factory-ticket', board='default')

    def start_run(self, ticket, title, project_dir='', branch=''):
        """What the intake pump does: provision the ticket's board, create its root there, bind it, close the ticket."""
        board = self.run_boards.provision(ticket, name=title, project_id='proj', project_dir=project_dir, branch=branch)
        with self.conn(board.board_id) as conn:
            root = self.kb.create_task(conn, title='FACTORY: ' + title, body='TYPE: feature\nPROJECT_MODE: new\nPROJECT_DIR: auto\nREQUEST: ' + title,
                                       assignee='factory-orchestrator', skills=['software-factory'], created_by='factory-intake',
                                       idempotency_key='intake-' + ticket, board=board.board_id)
        self.run_boards.bind_root(board, root)
        return self.registry.get(board.board_id), root

    def tick(self, board):
        self.callbacks['on_kanban_dispatch_tick'](board=board, dry_run=False)

    def dispatch(self, board, spawn=None):
        """One real dispatcher pass over a board; the fake spawn records what the real dispatcher decided."""
        spawned = []
        def fake_spawn(task, workspace, board=None):
            spawned.append(dict(task=task.id, board=board, assignee=task.assignee, model=task.model_override, provider=task.provider_override))
            return None
        with self.conn(board) as conn:
            from hermes_cli import kanban_db_dispatch
            kanban_db_dispatch.dispatch_once(conn, spawn_fn=spawn or fake_spawn, board=board, max_spawn=8)
        return spawned

    def drive(self, board, root, max_rounds=24, only_until=None):
        """Complete every runnable stage with synthetic passing evidence (same contract as native_smoke); returns stages completed."""
        kb = self.kb
        completed = 0
        with self.conn(board) as conn:
            controller = self.WorkflowController(kb, self.WorkflowState(), self.home / 'projects')
            for _ in range(max_rounds):
                stages = [dict(r) for r in conn.execute(
                    "SELECT s.* FROM factory_workflow_stages s JOIN tasks t ON t.id=s.task_id WHERE s.root_id=? AND t.status IN ('ready','running') ORDER BY t.created_at,s.stage_key", (root,))]
                for stage in stages:
                    task = kb.get_task(conn, stage['task_id'])
                    task = kb.claim_task(conn, task.id) if task.status == 'ready' else task
                    assert task is not None
                    kb._append_event(conn, task.id, 'worker_registered', {'synthetic_test': True}, run_id=task.current_run_id)
                    kind = stage['kind']
                    verdict = {'prepare': 'DONE', 'implement': 'DONE', 'verify': 'PASS', 'review': 'NO_BLOCKING_FINDINGS', 'repair': 'DONE'}[kind]
                    manifest = 'none' if kind == 'prepare' else 'abcdef123456'
                    artifacts = []
                    def retain(name, data):
                        aid = kb.store_attachment_bytes(conn, task.id, name, data, uploaded_by='synthetic-test')
                        artifacts.append(kb.get_attachment(conn, aid).stored_path)
                    if kind == 'prepare':
                        retain('RETRO.md' if stage['profile'] == 'factory-retro' else 'PLAN-REVIEW.md' if stage['stage_key'] == 'project-plan-review' else 'PLAN.md', b'AC1: Test behavior\n')
                    if stage['profile'] == 'architect':
                        retain('project-plan.json', json.dumps(dict(tasks=[dict(id='code', title='Native small task', owner='developer', dependencies=[], acceptance={'AC1': 'Test behavior'}, needs=dict(art=False, audio=False, ui=False, ux=False))])).encode())
                    if kind in ('review', 'verify'):
                        retain('report.md', b'Synthetic passing report, not a model evaluation.\n')
                    if kind == 'verify':
                        retain('src-' + manifest + '.tgz', b'synthetic snapshot identity fixture')
                    metadata = dict(contract='factory-worker/v2', workflow_contract='factory-workflow/v1', root=root, stage_key=stage['stage_key'], stage=kind.upper(),
                                    cycle=stage['cycle'] + 1, verdict=verdict, manifest_sha12=manifest, artifacts=artifacts, ac_ids=['AC1'], ac_results={'AC1': 'pass'},
                                    release_audit='PASS', publish_commands=['git status'], checks_failed=0, findings=[])
                    if stage['profile'] == 'factory-orchestrator':
                        metadata['project_scope'] = dict(art=False, audio=False, ui=False, ux=False)
                    summary = 'VERDICT=%s STAGE=%s CYCLE=%d MANIFEST=%s' % (verdict, kind.upper(), stage['cycle'] + 1, manifest)
                    assert kb.complete_task(conn, task.id, result='Synthetic test completion', summary=summary, metadata=metadata,
                                            expected_run_id=task.current_run_id, fire_lifecycle_hook=False)
                    completed += 1
                    if only_until and only_until(conn):
                        return completed
                controller.reconcile(conn, root)
                if kb.get_task(conn, root).status == 'done':
                    break
        return completed

    def root_status(self, board, root):
        with self.conn(board) as conn:
            return self.kb.get_task(conn, root).status

    def phase(self, board, root):
        with self.conn(board) as conn:
            state = self.WorkflowState().read_root(conn, root)
            return state['phase'] if state else None

    def install_for_cli(self):
        """Install the bundled plugin and its settings into this home, so scripts/factory_boards.py and the dashboard see what production does."""
        import yaml
        bundle_spec = importlib.util.spec_from_file_location('multi_bundle_installer', REPO / 'runtime/factory-dashboard/scripts/bundle_factory_plugin.py')
        bundler = importlib.util.module_from_spec(bundle_spec); bundle_spec.loader.exec_module(bundler)
        bundler.bundle_plugin(self.home / 'plugins' / 'factory-models')
        config = {'plugins': {'enabled': ['factory-models'], 'entries': {'factory-models': {'enabled': True, 'settings': dict(self.settings)}}}}
        (self.home / 'config.yaml').write_text(yaml.safe_dump(config))

    def cli(self, *args):
        import subprocess
        env = dict(os.environ, HERMES_HOME=str(self.home), HERMES_KANBAN_HOME=str(self.home))
        return subprocess.run([sys.executable, str(REPO / 'runtime/factory-dashboard/scripts/factory_boards.py'), '--hermes-source',
                               str(Path.home() / '.hermes/hermes-agent'), *args], capture_output=True, text=True, env=env, timeout=300)
