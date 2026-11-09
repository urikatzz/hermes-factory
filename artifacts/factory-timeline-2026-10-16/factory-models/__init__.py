"""Self-contained bundled policy consumer; no core file mutations."""
def register(ctx):
    from pathlib import Path
    from .factory_dashboard.factory_model_resolver import FactoryModelResolver, factory_root_id
    from .factory_dashboard.model_catalog import ModelCatalog
    from .factory_dashboard.policy_store import PolicyStore

    def resolve(*, task, board, board_path, **kwargs):
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

    ctx.register_hook('resolve_kanban_worker_model', resolve)
