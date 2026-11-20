"""Self-contained bundled policy consumer; no core file mutations.

The Factory governs the configured default board and every board in its run-board registry (see board_registry.py). Any other
Hermes board is left alone. A registered board with an inconsistent identity fails closed instead of being treated as unrelated.
"""
WORKFLOW_CONTRACT_VERSION = 1
BOARD_CONTRACT_VERSION = 1

def register(ctx):
    import logging
    from pathlib import Path
    from .factory_dashboard.factory_model_resolver import FactoryModelResolver, factory_root_id
    from .factory_dashboard.model_catalog import ModelCatalog
    from .factory_dashboard.policy_store import PolicyStore
    from .factory_dashboard.board_registry import build_resolver, DEFAULT_BOARD

    log = logging.getLogger('factory-models')
    from .factory_dashboard.hermes_compat import compat_report
    compat = compat_report()
    if not compat['ok']:
        log.error('Hermes lacks patches the Factory needs (%s). Stage creation and the workflow guards will not work: %s.', compat['message'], compat['remedy'])

    def settings():
        keys = ('board_path', 'board_id', 'snapshot_path', 'registry_path', 'boards_root')
        values = {key: ctx.get_config(key) for key in keys}
        values['board_id'] = values['board_id'] or DEFAULT_BOARD
        return values

    def resolver():
        config = settings()
        if not config['board_path']:
            return None
        if not config['snapshot_path']:
            config['snapshot_path'] = str(Path(config['board_path']).parent / 'state' / 'factory' / 'task-settings.db')
        return build_resolver(config)

    def governing(board_path, board):
        """(FactoryBoard, snapshot store) for a Factory board, None for an unrelated one; ConfigurationError for a broken identity."""
        if not ctx.get_config('snapshot_path'):
            return None
        found = resolver()
        factory_board = found.resolve(board_path, board) if found else None
        if factory_board is None:
            return None
        from .factory_dashboard.task_settings_store import TaskSettingsStore
        return factory_board, found.registry, TaskSettingsStore(Path(ctx.get_config('snapshot_path')), create=False)

    def before_create(*, task, board, board_path, conn=None, **kwargs):
        components = governing(board_path, board)
        if components:
            factory_board, registry, store = components
            from .factory_dashboard.factory_creation import FactoryCreation
            creation = FactoryCreation(store, factory_board.db_path, factory_board.board_id,
                                       run=factory_board if factory_board.is_run else None, registry=registry)
            creation.prepare_creation(task, board_path, factory_board.board_id, conn=conn)

    def resolve(*, task, board, board_path, **kwargs):
        components = governing(board_path, board)
        if components:
            factory_board, _registry, store = components
            from .factory_dashboard.frozen_resolver import FrozenFactoryResolver
            from .factory_dashboard.model_policy import ModelSelection
            catalog = ModelCatalog.from_file(Path(ctx.get_config('catalog_path')))
            def validate(settings_, role):
                catalog.validate(ModelSelection(settings_.provider, settings_.model), (role,))
            return FrozenFactoryResolver(store, factory_board.db_path, factory_board.board_id, validate).resolve(task, board_path, factory_board.board_id)
        # Settings follow the invoking profile; do not cache one tenant's home. Legacy policy resolution covers the default board only.
        configured_board = ctx.get_config('board_path')
        configured_id = ctx.get_config('board_id', 'default')
        if not configured_board or Path(board_path).resolve() != Path(configured_board).resolve() or (board or 'default') != configured_id:
            return None
        if factory_root_id(task, board_path) is None:
            return None
        catalog = ModelCatalog.from_file(Path(ctx.get_config('catalog_path')))
        store = PolicyStore(Path(ctx.get_config('policy_path')), create=False)
        resolver_ = FactoryModelResolver(store, configured_board, configured_id,
                                         lambda selection, role: catalog.validate(selection, (role,)))
        return resolver_.resolve(task, board_path, board)

    def before_mutation(**kwargs):
        components = governing(kwargs['board_path'], kwargs['board'])
        if components:
            factory_board, _registry, store = components
            from .factory_dashboard.workflow_guards import WorkflowGuards
            kwargs = dict(kwargs, board=factory_board.board_id)
            return WorkflowGuards(store, factory_board.db_path, factory_board.board_id).before_mutation(**kwargs)

    def reconcile_board(factory_board):
        from contextlib import closing
        from hermes_cli import kanban_db, kanban_db_connect
        from .factory_dashboard.workflow_state import WorkflowState
        from .factory_dashboard.workflow_controller import WorkflowController
        state = WorkflowState()
        controller = WorkflowController(kanban_db, state, Path(ctx.get_config('new_project_root', str(Path.home() / 'factory'))))
        with closing(kanban_db_connect.connect(Path(factory_board.db_path), board=factory_board.board_id)) as conn:
            if not state.exists(conn):
                return
            for root in state.pending_roots(conn):
                controller.reconcile(conn, root)

    def reconcile(*, board=None, dry_run=False, **kwargs):
        # Each board reconciles alone: one board's failure or pause never delays another.
        if dry_run or not ctx.get_config('board_path') or not ctx.get_config('snapshot_path'):
            return
        found = resolver()
        try:
            factory_board = found.for_label(board) if found else None
        except Exception as exc:
            log.warning('factory board %s is not reconcilable: %s', board, exc)
            return
        if factory_board is None or factory_board.status in ('provisioning', 'paused', 'cancelled', 'archived', 'failed'):
            return
        try:
            reconcile_board(factory_board)
        except Exception as exc:
            log.warning('factory reconcile of board %s failed: %s', factory_board.board_id, exc)
            if not factory_board.is_run:
                raise

    def announce():
        """Record, AFTER every hook is registered, that this process runs the run-board-aware plugin: {contract, pid, started}.
        The intake pump creates dedicated boards only when the live gateway (same pid and start time) has written it, so a gateway
        still running older code, a reused pid or a half-loaded plugin never receives a board it would not govern."""
        import json, os, subprocess
        try:
            snapshot = ctx.get_config('snapshot_path')
            if not snapshot:
                return
            started = subprocess.run(['/bin/ps', '-o', 'lstart=', '-p', str(os.getpid())], capture_output=True, text=True, timeout=10).stdout.strip()
            folder = Path(snapshot).parent / 'board-support'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / str(os.getpid())
            temporary = folder / ('.%d.tmp' % os.getpid())
            temporary.write_text(json.dumps(dict(contract=BOARD_CONTRACT_VERSION, pid=os.getpid(), started=started)))
            os.replace(temporary, target)
            for entry in folder.iterdir():
                try:
                    os.kill(int(entry.name), 0)
                except ProcessLookupError:
                    entry.unlink(missing_ok=True)
                except (ValueError, PermissionError):
                    pass
        except Exception as exc:  # never let bookkeeping break plugin loading
            log.debug('board-support announcement failed: %s', exc)

    ctx.register_hook('on_kanban_dispatch_tick', reconcile)
    ctx.register_hook('kanban_task_completed', reconcile)
    ctx.register_hook('before_kanban_task_mutation', before_mutation)
    ctx.register_hook('resolve_kanban_worker_model', resolve)
    ctx.register_hook('before_kanban_task_create', before_create)
    if compat['ok']:
        announce()  # last: only a fully registered plugin on a fully patched Hermes may claim run-board support
