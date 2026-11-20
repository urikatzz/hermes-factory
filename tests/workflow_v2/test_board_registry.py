import tempfile
import unittest
from pathlib import Path

from factory_dashboard.board_registry import BoardRegistry, BoardResolver, build_resolver, run_board_slug, MAX_PROVISION_ATTEMPTS
from factory_dashboard.model_policy import ConfigurationError


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.dir, ignore_errors=True))
        self.default = self.dir / 'kanban.db'
        self.default.touch()
        self.registry = BoardRegistry(self.dir / 'state/board-registry.db', self.dir / 'kanban/boards', self.default)
        self.resolver = BoardResolver(self.registry)

    def test_begin_is_idempotent_and_keyed_by_ticket(self):
        first = self.registry.begin('t_1', name='one')
        again = self.registry.begin('t_1', name='renamed')
        self.assertEqual((first.board_id, first.db_path), (again.board_id, again.db_path))
        self.assertEqual(again.name, 'one')
        self.assertEqual(first.board_id, run_board_slug('t_1'))
        self.assertEqual(first.db_path, (self.dir / 'kanban/boards/run-t_1/kanban.db').resolve())

    def test_bad_ticket_ids_cannot_name_a_board(self):
        for bad in ('', 'T 1', '../escape', 'x' * 80):
            with self.assertRaises(ConfigurationError):
                self.registry.begin(bad)

    def test_default_board_is_governed_without_registry_entries_and_unrelated_boards_are_not(self):
        self.assertEqual(self.resolver.resolve(self.default, 'default').kind, 'default')
        self.assertIsNone(self.resolver.resolve(self.default, 'other-label'))
        self.assertIsNone(self.resolver.resolve(self.dir / 'kanban/boards/foo/kanban.db', 'foo'))

    def test_registered_run_board_resolves_by_path_and_checks_labels(self):
        board = self.registry.mark_active(self.registry.begin('t_2').board_id)
        self.registry.begin('t_3')
        found = self.resolver.resolve(board.db_path, board.board_id)
        self.assertEqual((found.kind, found.ticket_id, found.source_board_id), ('run', 't_2', 'default'))
        self.assertEqual(self.resolver.resolve(board.db_path, None).board_id, board.board_id)  # label defaults are tolerated
        with self.assertRaisesRegex(ConfigurationError, 'cross-board'):
            self.resolver.resolve(board.db_path, run_board_slug('t_3'))
        with self.assertRaisesRegex(ConfigurationError, 'wrong board'):
            self.resolver.resolve(self.dir / 'elsewhere/kanban.db', board.board_id)

    def test_failed_board_fails_closed_after_the_attempt_budget(self):
        board = self.registry.begin('t_4')
        for _ in range(MAX_PROVISION_ATTEMPTS):
            board = self.registry.record_failure(board.board_id, 'disk full')
        self.assertEqual(board.status, 'failed')
        with self.assertRaisesRegex(ConfigurationError, 'disk full.*reset'):
            self.resolver.resolve(board.db_path, board.board_id)
        with self.assertRaises(ConfigurationError):
            self.registry.mark_active(board.board_id)
        self.assertEqual(self.registry.reset_failed(board.board_id).status, 'provisioning')

    def test_a_board_registered_at_the_wrong_path_is_rejected(self):
        board = self.registry.begin('t_5')
        with self.registry._txn() as conn:
            conn.execute('UPDATE factory_boards SET db_path=? WHERE board_id=?', (str(self.dir / 'tampered/kanban.db'), board.board_id))
        with self.assertRaisesRegex(ConfigurationError, 'expected'):
            self.resolver.resolve(self.dir / 'tampered/kanban.db', board.board_id)

    def test_root_binding_is_single_and_exclusive_paths_are_enforced(self):
        board = self.registry.begin('t_6', project_id='p', project_dir='/w/a', branch='b1')
        self.registry.set_root(board.board_id, 't_root')
        self.registry.set_root(board.board_id, 't_root')
        with self.assertRaisesRegex(ConfigurationError, 'already owns'):
            self.registry.set_root(board.board_id, 't_other')
        with self.assertRaisesRegex(ConfigurationError, 'directory'):
            self.registry.begin('t_7', project_id='p', project_dir='/w/a')
        with self.assertRaisesRegex(ConfigurationError, 'Branch'):
            self.registry.begin('t_8', project_id='p', project_dir='/w/c', branch='b1')
        self.registry.set_status(board.board_id, 'cancelled')
        self.assertEqual(self.registry.begin('t_9', project_id='p', project_dir='/w/a', branch='b1').status, 'provisioning')  # released once the run ends

    def test_a_retry_must_describe_the_same_reservation(self):
        self.registry.begin('t_10', project_id='p', project_dir='/w/one', branch='feature/a')
        self.assertEqual(self.registry.begin('t_10').branch, 'feature/a')  # a bare retry reuses it
        with self.assertRaisesRegex(ConfigurationError, 'reserved branch'):
            self.registry.begin('t_10', project_id='p', project_dir='/w/one', branch='feature/a-2')
        with self.assertRaisesRegex(ConfigurationError, 'reserved project_dir'):
            self.registry.begin('t_10', project_dir='/w/other')

    def test_build_resolver_without_a_registry_governs_only_the_default_board(self):
        config = dict(board_path=str(self.default), snapshot_path=str(self.dir / 'other/task-settings.db'))
        resolver = build_resolver(config)
        self.assertEqual(resolver.resolve(self.default, 'default').kind, 'default')
        self.assertIsNone(resolver.resolve(self.dir / 'kanban/boards/run-t_1/kanban.db', 'run-t_1'))
        self.assertEqual(len(resolver.governed()), 1)
        self.assertFalse((self.dir / 'other').exists())  # resolution never creates the registry


if __name__ == '__main__':
    unittest.main()
