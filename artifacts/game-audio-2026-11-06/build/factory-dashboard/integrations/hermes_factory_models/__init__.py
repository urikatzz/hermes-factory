"""Self-contained bundled policy consumer; no core file mutations."""
WORKFLOW_CONTRACT_VERSION = 1

def register(ctx):
    from pathlib import Path
    from .factory_dashboard.factory_model_resolver import FactoryModelResolver, factory_root_id
    from .factory_dashboard.model_catalog import ModelCatalog
    from .factory_dashboard.policy_store import PolicyStore

    def snapshot_components(board_path, board):
        configured_board = ctx.get_config('board_path')
        configured_id = ctx.get_config('board_id', 'default')
        snapshot_path = ctx.get_config('snapshot_path')
        if not snapshot_path or not configured_board:
            return None
        if Path(board_path).resolve() != Path(configured_board).resolve() or (board or 'default') != configured_id:
            return None
        from .factory_dashboard.task_settings_store import TaskSettingsStore
        return TaskSettingsStore(Path(snapshot_path), create=False), configured_board, configured_id

    def before_create(*, task, board, board_path, conn=None, **kwargs):
        components = snapshot_components(board_path, board)
        if components:
            from .factory_dashboard.factory_creation import FactoryCreation
            FactoryCreation(*components).prepare_creation(task, board_path, board, conn=conn)

    def resolve(*, task, board, board_path, **kwargs):
        components = snapshot_components(board_path, board)
        if components:
            from .factory_dashboard.frozen_resolver import FrozenFactoryResolver
            from .factory_dashboard.model_policy import ModelSelection
            catalog = ModelCatalog.from_file(Path(ctx.get_config('catalog_path')))
            def validate(settings, role):
                catalog.validate(ModelSelection(settings.provider, settings.model), (role,))
            return FrozenFactoryResolver(*components, validate).resolve(task, board_path, board)
        # Settings follow the invoking profile; do not cache one tenant's home.
        configured_board = ctx.get_config('board_path')
        configured_id = ctx.get_config('board_id', 'default')
        if not configured_board or Path(board_path).resolve() != Path(configured_board).resolve() or (board or 'default') != configured_id:
            return None
        if factory_root_id(task, board_path) is None:
            return None
        catalog = ModelCatalog.from_file(Path(ctx.get_config('catalog_path')))
        store = PolicyStore(Path(ctx.get_config('policy_path')), create=False)
        resolver = FactoryModelResolver(store, configured_board, configured_id,
                                        lambda selection, role: catalog.validate(selection, (role,)))
        return resolver.resolve(task, board_path, board)

    def before_mutation(**kwargs):
        components = snapshot_components(kwargs['board_path'], kwargs['board'])
        if components:
            from .factory_dashboard.workflow_guards import WorkflowGuards
            return WorkflowGuards(*components).before_mutation(**kwargs)

    def reconcile(*, board=None, dry_run=False, **kwargs):
        if dry_run or (board or 'default') != ctx.get_config('board_id', 'default'):
            return
        configured = ctx.get_config('board_path')
        if not configured or not ctx.get_config('snapshot_path'):
            return
        from contextlib import closing
        from hermes_cli import kanban_db, kanban_db_connect
        from .factory_dashboard.workflow_state import WorkflowState
        from .factory_dashboard.workflow_controller import WorkflowController
        state = WorkflowState()
        controller = WorkflowController(kanban_db, state, Path(ctx.get_config('new_project_root', str(Path.home() / 'factory'))))
        with closing(kanban_db_connect.connect(Path(configured), board=board)) as conn:
            if not state.exists(conn):
                return
            roots = state.pending_roots(conn)
            for root in roots:
                controller.reconcile(conn, root)

    ctx.register_hook('on_kanban_dispatch_tick', reconcile)
    ctx.register_hook('kanban_task_completed', reconcile)
    ctx.register_hook('before_kanban_task_mutation', before_mutation)
    ctx.register_hook('resolve_kanban_worker_model', resolve)
    ctx.register_hook('before_kanban_task_create', before_create)
