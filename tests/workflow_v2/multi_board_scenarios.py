"""Multi-board Factory scenarios on a disposable Hermes home with the real plugin, boards and dispatcher.

Run through test_multi_board.py (a subprocess, because Hermes keeps process-global board state). Never launches a model.
"""
from concurrent.futures import ThreadPoolExecutor
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from multi_board_harness import Factory


class Scenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix='factory-multi-board-')
        cls.f = Factory(cls.directory)
        cls.hooks = cls.f.hooks()
        cls.hooks.__enter__()
        cls.f.tickets = {}

    @classmethod
    def tearDownClass(cls):
        cls.hooks.__exit__(None, None, None)
        shutil.rmtree(cls.directory, ignore_errors=True)

    def run_for(self, title, model=None, **kw):
        ticket = self.f.ticket(title, model=model)
        board, root = self.f.start_run(ticket, title, **kw)
        self.f.tick(board.board_id)
        return ticket, board, root

    # ---- dispatch, model routing and snapshots on non-default boards
    def test_01_dispatch_and_model_routing_are_per_board(self):
        ta, a, ra = self.run_for('route alpha', model='a')
        tb, b, rb = self.run_for('route beta', model='b')
        self.assertNotEqual(a.board_id, b.board_id)
        spawned_a, spawned_b = self.f.dispatch(a.board_id), self.f.dispatch(b.board_id)
        self.assertEqual([(s['board'], s['model']) for s in spawned_a], [(a.board_id, 'model-a')])
        self.assertEqual([(s['board'], s['model']) for s in spawned_b], [(b.board_id, 'model-b')])
        with self.f.conn(a.board_id) as conn:
            card = conn.execute("SELECT id FROM tasks WHERE title LIKE 'PLAN%'").fetchone()[0]
            meta = conn.execute('SELECT metadata FROM task_runs WHERE task_id=?', (card,)).fetchone()[0]
        self.assertIn('model-a', meta)
        # The same ticket snapshot, bound under each run board's own identity, is what routed the model.
        sa = self.f.store.snapshot_for_task(a.identity, ra)
        sb = self.f.store.snapshot_for_task(b.identity, rb)
        self.assertNotEqual(sa.id, sb.id)
        self.assertIsNone(self.f.store.snapshot_for_task(b.identity, ra))
        self.assertIsNone(self.f.store.snapshot_for_task(a.identity, rb))

    def test_02_only_registered_boards_are_governed(self):
        from hermes_cli import kanban_db_boards
        kanban_db_boards.create_board('unrelated-board', name='Unrelated')
        path = self.f.kb.kanban_db_path(board='unrelated-board')
        self.assertIsNone(self.f.resolver.resolve(path, 'unrelated-board'))
        with self.f.kbc.connect(path, board='unrelated-board') as conn:
            root = self.f.kb.create_task(conn, title='FACTORY: not ours', body='x', assignee='factory-orchestrator', board='unrelated-board')
            self.assertEqual(self.f.kb.get_task(conn, root).status, 'ready')
            self.assertFalse(self.f.WorkflowState.exists(conn))
        with self.f.kbc.connect(path, board='unrelated-board') as conn:
            self.assertEqual(self.f.kb.get_task(conn, root).status, 'ready')

    # ---- reliability: idempotency, duplicates, partial failure
    def test_03_provisioning_is_idempotent_and_never_duplicates(self):
        ticket = self.f.ticket('idem')
        first = self.f.run_boards.provision(ticket, name='idem')
        with ThreadPoolExecutor(6) as pool:
            boards = list(pool.map(lambda _: self.f.run_boards.provision(ticket, name='idem'), range(6)))
        self.assertEqual({b.board_id for b in boards}, {first.board_id})
        self.assertEqual(len([b for b in self.f.registry.list() if b.ticket_id == ticket]), 1)
        board, root = self.f.start_run(ticket, 'idem')
        again_board, again_root = self.f.start_run(ticket, 'idem')
        self.assertEqual((board.board_id, root), (again_board.board_id, again_root))
        with self.f.conn(board.board_id) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks WHERE title LIKE 'FACTORY:%'").fetchone()[0], 1)

    def test_04_second_root_and_duplicate_intake_roots_are_refused(self):
        ticket, board, root = self.run_for('dup guard')
        errors = self.f.mod('model_policy').ConfigurationError
        with self.f.conn(board.board_id) as conn:
            with self.assertRaisesRegex(errors, 'serves ticket'):
                self.f.kb.create_task(conn, title='FACTORY: sneaky second', body='x', assignee='factory-orchestrator', skills=['software-factory'],
                                      idempotency_key='intake-t_other', board=board.board_id)
            with self.assertRaisesRegex(errors, 'only its own root'):
                self.f.kb.create_task(conn, title='TICKET: nope', body='x', created_by='factory-ticket', board=board.board_id)
        with self.f.conn('default') as conn:
            with self.assertRaisesRegex(errors, 'already has run board'):
                self.f.kb.create_task(conn, title='FACTORY: dup on intake board', body='x', assignee='factory-orchestrator', skills=['software-factory'],
                                      idempotency_key='intake-' + ticket, board='default')

    def test_05_partial_provisioning_failure_recovers_without_a_second_board(self):
        ticket = self.f.ticket('partial')
        boards_module, hermes = self.f.boards_module, self.f.run_boards.hermes

        class Flaky(boards_module.HermesBoards):
            calls = 0
            def connect(self, path, slug):
                Flaky.calls += 1
                if Flaky.calls == 1:
                    raise OSError('simulated disk failure after the board directory was created')
                return super().connect(path, slug)
        flaky = boards_module.RunBoards(self.f.registry, Flaky())
        with self.assertRaisesRegex(boards_module.ProvisionError, 'attempt 1'):
            flaky.provision(ticket, name='partial')
        record = self.f.registry.by_ticket(ticket)
        self.assertEqual((record.status, self.f.registry.error_of(record.board_id)[1]), ('provisioning', 1))
        recovered = flaky.provision(ticket, name='partial')
        self.assertEqual((recovered.board_id, recovered.status), (record.board_id, 'active'))
        self.assertEqual(len([b for b in self.f.registry.list() if b.ticket_id == ticket]), 1)

    def test_06_exhausted_provisioning_fails_closed_with_diagnostics_then_can_be_reset(self):
        ticket = self.f.ticket('doomed')
        boards_module = self.f.boards_module

        class Broken(boards_module.HermesBoards):
            def create(self, *a):
                raise OSError('read-only filesystem')
        broken = boards_module.RunBoards(self.f.registry, Broken())
        for _ in range(self.f.registry_module.MAX_PROVISION_ATTEMPTS):
            with self.assertRaises(boards_module.ProvisionError):
                broken.provision(ticket, name='doomed')
        record = self.f.registry.by_ticket(ticket)
        self.assertEqual(record.status, 'failed')
        with self.assertRaisesRegex(boards_module.ProvisionError, 'read-only filesystem.*reset'):
            self.f.run_boards.provision(ticket, name='doomed')
        # Hooks refuse to treat a failed board as anything but a hard error, with an actionable message.
        with self.assertRaisesRegex(self.f.mod('model_policy').ConfigurationError, 'failed.*reset'):
            self.f.resolver.resolve(record.db_path, record.board_id)
        # Unrelated runs are unaffected, and an operator reset restores the failed one.
        _, other, _ = self.run_for('doomed neighbour')
        self.assertEqual(other.status, 'active')
        self.f.registry.reset_failed(record.board_id)
        self.assertEqual(self.f.run_boards.provision(ticket, name='doomed').status, 'active')

    def test_07_cross_board_contamination_is_refused(self):
        ta, a, ra = self.run_for('contam a', model='a')
        tb, b, rb = self.run_for('contam b', model='b')
        errors = self.f.mod('model_policy').ConfigurationError
        # A path/label mixup that names another registered board never resolves.
        with self.assertRaisesRegex(errors, 'cross-board'):
            self.f.resolver.resolve(a.db_path, b.board_id)
        # An unregistered database claiming a registered label is an identity error.
        from hermes_cli import kanban_db_boards
        kanban_db_boards.create_board('impostor')
        with self.assertRaisesRegex(errors, 'wrong board'):
            self.f.resolver.resolve(self.f.kb.kanban_db_path(board='impostor'), a.board_id)
        # A snapshot cannot be bound across boards unless the registered ticket board is named.
        from factory_dashboard.model_policy import ConfigurationError as StoreError
        with self.assertRaisesRegex(StoreError, 'different board'):
            self.f.store.bind_task(a.identity, 't_forged', self.f.store.snapshot_for_task(b.identity, rb).id, 'stage')
        # Stage cards of one board never exist on the other.
        with self.f.conn(a.board_id) as ca, self.f.conn(b.board_id) as cb:
            ids_a = {r[0] for r in ca.execute('SELECT id FROM tasks')}
            ids_b = {r[0] for r in cb.execute('SELECT id FROM tasks')}
        self.assertFalse(ids_a & ids_b)

    def test_08_project_directory_and_branch_are_exclusive_between_live_runs(self):
        t1, t2, t3 = (self.f.ticket('excl %d' % i) for i in range(3))
        errors = self.f.mod('model_policy').ConfigurationError
        self.f.run_boards.provision(t1, project_id='repo', project_dir='/work/repo-1', branch='feature/x')
        with self.assertRaisesRegex(errors, 'Project directory'):
            self.f.run_boards.provision(t2, project_id='repo', project_dir='/work/repo-1', branch='feature/y')
        with self.assertRaisesRegex(errors, 'Branch feature/x'):
            self.f.run_boards.provision(t2, project_id='repo', project_dir='/work/repo-2', branch='feature/x')
        self.assertEqual(self.f.run_boards.provision(t3, project_id='repo', project_dir='/work/repo-3', branch='feature/z').status, 'active')

    # ---- simultaneous runs, approvals, repair
    def test_09_two_runs_execute_simultaneously_while_a_third_awaits_approval(self):
        _, a, ra = self.run_for('simul a', model='a')
        _, b, rb = self.run_for('simul b', model='b')
        _, c, rc = self.run_for('approval c')
        with self.f.conn(c.board_id) as conn:
            self.f.drive(c.board_id, rc, only_until=lambda _conn: True)  # first stage only
            root = self.f.WorkflowState().read_root(conn, rc)
            with conn:
                self.f.WorkflowController(self.f.kb, self.f.WorkflowState(), self.f.home)._stop(conn, root, 'human_review', 'Awaiting human approval')
        barrier = threading.Barrier(2)
        def run(board, root):
            barrier.wait()
            return self.f.drive(board, root)
        with ThreadPoolExecutor(2) as pool:
            done = list(pool.map(lambda args: run(*args), [(a.board_id, ra), (b.board_id, rb)]))
        self.assertTrue(all(n > 5 for n in done), done)
        self.assertEqual(self.f.root_status(a.board_id, ra), 'done')
        self.assertEqual(self.f.root_status(b.board_id, rb), 'done')
        # The approval-gated run did not move, and says so in its summary; the finished ones do not claim to be waiting.
        self.f.tick(c.board_id)
        self.assertEqual(self.f.phase(c.board_id, rc), 'human_review')
        self.assertTrue(self.f.run_boards.summary(self.f.registry.get(c.board_id))['awaiting'])
        self.assertFalse(self.f.run_boards.summary(self.f.registry.get(a.board_id))['awaiting'])
        # Each run kept its own models.
        self.assertEqual(self.f.store.snapshot_for_task(a.identity, ra).roles['developer'].model, 'model-a')
        self.assertEqual(self.f.store.snapshot_for_task(b.identity, rb).roles['developer'].model, 'model-b')

    def test_10_a_failed_run_is_repaired_while_another_keeps_running(self):
        _, bad, rbad = self.run_for('repair bad')
        _, good, rgood = self.run_for('repair good')
        controller = self.f.WorkflowController(self.f.kb, self.f.WorkflowState(), self.f.home / 'projects')
        scope = self.f.mod('workflow_guards').controller_scope
        with self.f.conn(bad.board_id) as conn:
            card = conn.execute("SELECT id FROM tasks WHERE title LIKE 'PLAN%'").fetchone()[0]
            task = self.f.kb.claim_task(conn, card)
            with scope(conn, rbad):  # an infrastructure failure the controller must not retry blindly
                self.f.kb.block_task(conn, card, reason='infra: tool unavailable', kind='needs_input', expected_run_id=task.current_run_id)
            controller.reconcile(conn, rbad)
        self.f.drive(bad.board_id, rbad)  # the controller's own retry completes, then the project stops for a human
        self.assertNotEqual(self.f.root_status(bad.board_id, rbad), 'done')
        stopped = self.f.run_boards.summary(self.f.registry.get(bad.board_id))
        self.assertTrue(stopped['needs_intervention'])
        self.assertFalse(stopped['awaiting'])  # a failure needing repair is not an approval request
        # The neighbour finishes while the failed run is stopped.
        self.assertGreater(self.f.drive(good.board_id, rgood), 5)
        with self.f.conn(good.board_id) as conn:
            good_events = conn.execute('SELECT COUNT(*) FROM task_events').fetchone()[0]
            good_snapshot = self.f.WorkflowState().read_root(conn, rgood)['snapshot_id']
        # Human repair decision on the failed run only, through the real resume path.
        with self.f.conn(bad.board_id) as conn:
            controller.resume(conn, rbad, 'tool restored')
        self.f.drive(bad.board_id, rbad)
        self.assertEqual(self.f.root_status(bad.board_id, rbad), 'done')
        self.assertEqual(self.f.phase(bad.board_id, rbad), 'delivered')
        with self.f.conn(good.board_id) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM task_events').fetchone()[0], good_events)
            self.assertEqual(self.f.WorkflowState().read_root(conn, rgood)['snapshot_id'], good_snapshot)
        self.assertEqual(self.f.root_status(good.board_id, rgood), 'done')

    def test_11_pause_resume_and_archive_are_board_scoped(self):
        _, p, rp = self.run_for('pause p')
        _, q, rq = self.run_for('pause q')
        parked = self.f.run_boards.pause(p.board_id, 'maintenance window')
        self.assertTrue(parked)
        self.assertEqual(self.f.registry.get(p.board_id).status, 'paused')
        self.assertEqual(self.f.dispatch(p.board_id), [])  # nothing dispatchable while paused
        self.f.tick(p.board_id)  # a paused board is not reconciled
        self.assertGreater(len(self.f.dispatch(q.board_id)) + 1, 0)  # the neighbour still dispatches
        restored = self.f.run_boards.resume(p.board_id)
        self.assertEqual(sorted(restored), sorted(parked))
        self.assertEqual(self.f.registry.get(p.board_id).status, 'active')
        self.assertEqual(len(self.f.dispatch(p.board_id)), 1)
        # A run in progress refuses archive; a cancelled one archives, disappears from the active list and stays readable.
        with self.assertRaisesRegex(self.f.mod('model_policy').ConfigurationError, 'in progress'):
            self.f.run_boards.archive(q.board_id)
        self.f.run_boards.cancel(q.board_id, 'not needed')
        self.f.run_boards.archive(q.board_id)
        self.assertNotIn(q.board_id, [b.board_id for b in self.f.resolver.governed()[1:]])
        history = self.f.run_boards.summary(self.f.registry.get(q.board_id))
        self.assertTrue(history['available'])
        self.assertEqual(history['status'], 'archived')

    # ---- gateway restart and recovery
    def test_12_gateway_restart_recovers_every_registered_active_run(self):
        runs = [self.run_for('restart %d' % i) for i in range(2)]
        for _, board, root in runs:
            self.f.drive(board.board_id, root, only_until=lambda _conn: True)
        # Simulate a gateway restart: all in-memory plugin, resolver and registry objects are discarded and rebuilt.
        self.f.load_plugin()
        self.f.hooks_context = self.f.hooks()
        active = [b for b in self.f.resolver.governed(running_only=True) if b.is_run and b.root_id in {r for _, _, r in runs}]
        self.assertEqual(len(active), 2)
        for board in active:
            self.f.tick(board.board_id)
        for _, board, root in runs:
            self.f.drive(board.board_id, root)
            self.assertEqual(self.f.root_status(board.board_id, root), 'done')

    # ---- compatibility with workflows that already exist on the default board
    def test_13_default_board_workflows_are_unchanged(self):
        with self.f.conn('default') as conn:
            root = self.f.kb.create_task(conn, title='FACTORY: legacy default', body='TYPE: feature\nPROJECT_MODE: new\nPROJECT_DIR: auto\nREQUEST: legacy',
                                         assignee='factory-orchestrator', skills=['software-factory'])
            self.assertEqual(self.f.kb.get_task(conn, root).status, 'blocked')
        self.f.tick('default')
        self.assertGreater(self.f.drive('default', root), 5)
        self.assertEqual(self.f.root_status('default', root), 'done')
        # The default board is never in the registry and keeps its legacy identity.
        self.assertIsNone(self.f.registry.by_path(self.f.default_path))
        self.assertEqual(self.f.resolver.resolve(self.f.default_path, 'default').kind, 'default')
        # Another board's default-label ticks never touch it.
        self.assertEqual(self.f.dispatch('default'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
