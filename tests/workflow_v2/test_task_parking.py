"""A task that stops parks itself and the tasks that depend on it; every independent task keeps going. Budgets, evidence and acceptance criteria are never touched."""
import copy
import json
import unittest

import test_project_controller as base
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.hermes_compat import HermesUnpatched
from factory_dashboard.project_controller import ProjectController

CODE, NEEDS = base.CODE, base.NEEDS
X = dict(CODE, id='x', title='Wire the scene')
Y = dict(CODE, id='y', title='Needs the scene', dependencies=['x'])
W = dict(CODE, id='w', title='Needs Y', dependencies=['y'])
Z = dict(CODE, id='z', title='Independent work')


class ParkingTests(unittest.TestCase):
    for _name in ('setUp', 'tick', 'only', 'architect', 'plan', 'project', 'block', 'stall', 'used', 'approve', 'approval_phrase'):
        locals()[_name] = getattr(base.ProjectControllerTests, _name)

    def pass_task(self):
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        for row in self.board.ready():
            self.board.complete(row)
        self.tick()

    def stop_for_good(self):
        """The retro that follows a project stop runs and the root settles, which is when a human can resume."""
        self.board.complete(self.only('factory-retro')); self.tick()
        self.assertIn(self.state.read_root(self.conn, self.root)['phase'], ('blocked', 'human_review'))

    def stages(self, task):
        return self.conn.execute("SELECT count(*) FROM factory_workflow_stages WHERE stage_key LIKE ?", ('task-' + task + '%',)).fetchone()[0]

    def park_x(self, tasks=(X, Y, Z)):
        self.plan(tasks=list(tasks))
        row = self.only('developer')
        self.assertIn('Wire the scene', self.board.cards[row['task_id']]['body'])
        self.block(row, reason='AC3 cannot be completed: the scene builder does not compile')
        self.tick()

    def test_a_stopped_task_is_parked_and_the_independent_task_goes_on(self):
        self.park_x()
        project = self.project()
        self.assertNotIn('terminal', project)                                              # the project did not stop
        self.assertEqual(list(project['parked']), ['x'])
        self.assertEqual(project['parked']['x']['phase'], 'blocked')
        self.assertIn('scene builder does not compile', project['parked']['x']['reason'])
        self.assertEqual(project['active_task'], 'z')
        card = self.board.cards[self.only('developer')['task_id']]['body']
        self.assertIn('Independent work', card)                                            # the next card is for z, not for y which depends on x
        self.assertEqual(project['completed'], [])                                         # nothing is marked complete

    def test_dependents_of_a_parked_task_never_run_and_are_not_dispatched_twice(self):
        self.park_x()
        counts = (self.stages('x'), self.stages('y'))
        for _ in range(3):
            self.tick()
        self.assertEqual((self.stages('x'), self.stages('y')), counts)                      # re-reconciling creates no duplicate cards
        self.assertEqual(self.stages('y'), 0)                                              # y waits for x and has no card at all
        self.pass_task()                                                                   # z completes
        self.assertEqual([t['id'] for t in self.project()['completed']], ['z'])
        self.assertEqual(self.stages('y'), 0)

    def test_when_nothing_runnable_is_left_the_exact_blocking_graph_is_reported(self):
        self.park_x(tasks=(X, Y, W, Z))
        self.pass_task()
        project = self.project()
        terminal = project['terminal']
        self.assertEqual(terminal['phase'], 'blocked')
        graph = terminal['graph']
        self.assertEqual((graph['total'], graph['completed']), (4, ['z']))
        self.assertEqual([p['id'] for p in graph['parked']], ['x'])
        self.assertEqual({w['id']: (w['waiting_on'], w['parked_causes']) for w in graph['waiting']}, {'y': (['x'], ['x']), 'w': (['y'], ['x'])})   # w traces back through y to x
        for text in ('No runnable task remains: 1 of 4 tasks are complete', 'Parked, needs a human decision: x', 'Waiting: y needs x (traces back to parked x)',
                     'Waiting: w needs y (traces back to parked x)', 'Nothing was skipped or marked complete'):
            self.assertIn(text, terminal['reason'])
        self.assertEqual([t['id'] for t in project['completed']], ['z'])                      # x, y and w are not complete, and there is no integration
        self.assertNotIn('integration', project)

    def test_parking_keeps_the_work_record_and_every_budget_exactly(self):
        self.plan(tasks=[X, Y, Z])
        before = copy.deepcopy(self.project()['work'])
        self.block(self.only('developer'), reason='cannot compile'); self.tick()
        parked = self.project()['parked']['x']
        for key in ('step', 'cycle', 'charges', 'extra_repairs', 'blocking', 'writer_inputs'):
            self.assertEqual(parked['work'].get(key), before.get(key), key)
        self.assertEqual(self.used(), (0, 0))                                              # no repair or orchestration budget was spent by parking

    def test_a_resume_after_the_stall_restores_the_parked_task_with_its_record_and_budget(self):
        self.park_x()
        recorded = copy.deepcopy(self.project()['parked']['x']['work'])
        self.pass_task()
        self.stop_for_good()
        self.controller.resume(self.conn, self.root, 'The scene builder was repaired by hand', {'task': 'x'})
        project = self.project()
        self.assertNotIn('terminal', project); self.assertNotIn('parked', project)
        self.assertEqual(project['active_task'], 'x')
        self.assertEqual({k: project['work'].get(k) for k in ('cycle', 'charges', 'extra_repairs')}, {k: recorded.get(k) for k in ('cycle', 'charges', 'extra_repairs')})
        self.assertIn('Wire the scene', self.board.cards[self.only('developer')['task_id']]['body'])   # a fresh card for the same task, retried
        self.assertTrue(any(e['kind'] == 'task_unparked' for e in project['orchestration_log']))

    def test_a_plain_resume_of_a_stall_restores_the_first_parked_task(self):
        self.park_x()
        self.pass_task()
        self.stop_for_good()
        self.controller.resume(self.conn, self.root, 'Retry the stopped task after the repair')
        self.assertEqual(self.project()['active_task'], 'x')

    def test_after_the_repaired_task_completes_its_dependents_run_in_order(self):
        self.park_x(tasks=(X, Y, Z))
        self.pass_task()                                                                   # z
        self.stop_for_good()
        self.controller.resume(self.conn, self.root, 'Repaired', {'task': 'x'})
        self.pass_task()                                                                   # x
        self.assertEqual(self.project()['active_task'], 'y')
        self.pass_task()                                                                   # y
        self.only('developer')                                                             # the final integration card
        self.assertEqual(sorted(t['id'] for t in self.project()['completed']), ['x', 'y', 'z'])

    def test_resuming_a_parked_task_that_is_not_parked_is_refused_and_changes_nothing(self):
        self.park_x()
        self.pass_task()
        self.stop_for_good()
        before = self.project()
        with self.assertRaises(ConfigurationError):
            self.controller.resume(self.conn, self.root, 'Retry', {'task': 'y'})
        self.assertEqual(self.project(), before)

    def test_a_stop_with_no_independent_task_keeps_the_whole_project_shape_and_reports_who_waits(self):
        self.plan(tasks=[X, Y])                                                            # y depends on x: nothing independent can run
        self.block(self.only('developer'), reason='AC3 cannot be completed: the scene builder does not compile'); self.tick()
        project = self.project()
        self.assertNotIn('parked', project); self.assertIn('work', project)                # parking would change nothing, so the task's work stays in place
        self.assertEqual(project['terminal']['phase'], 'blocked')
        self.assertIn('the scene builder does not compile', project['terminal']['reason'])
        self.assertIn('Unfinished because of it: y (needs x)', project['terminal']['reason'])
        self.assertEqual([(w['id'], w['parked_causes']) for w in project['terminal']['graph']['waiting']], [('y', ['x'])])
        self.assertEqual([p['id'] for p in project['terminal']['graph']['parked']], ['x'])

    def test_a_single_task_project_stops_exactly_as_before(self):
        self.plan(tasks=[X])
        self.block(self.only('developer'), reason='cannot compile'); self.tick()
        project = self.project()
        self.assertNotIn('parked', project); self.assertNotIn('graph', project['terminal'])
        self.assertEqual(project['terminal']['reason'], 'Stage blocked: cannot compile')

    def test_a_task_is_chosen_by_dependencies_not_only_by_plan_order(self):
        self.plan(tasks=[Y, X, Z])                                                         # y is listed first but needs x
        self.assertEqual(self.project()['active_task'], 'x')

    def test_a_project_level_stop_still_ends_the_run_and_parks_nothing(self):
        self.plan(tasks=[X, Z])
        controller = ProjectController(self.controller)
        root = self.state.read_root(self.conn, self.root); project = self.project()
        controller._terminal(self.conn, root, project, 'blocked', 'Visual capability missing: no model can read images')
        self.assertEqual(project['terminal']['phase'], 'blocked'); self.assertNotIn('parked', project); self.assertEqual(project['mode'], 'retro')

    def test_park_converts_a_stopped_task_in_progress_and_the_project_continues(self):
        self.plan(tasks=[X, Y, Z])
        controller = ProjectController(self.controller)
        root = self.state.read_root(self.conn, self.root); project = self.project()
        project.pop('active_task')                                                         # a project recorded before parking existed
        recorded = copy.deepcopy(project['work'])
        self.conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (self.only('developer')['task_id'],))   # a whole-project stop blocked the card in progress
        project.update(resume_mode='tasks', mode='retro', active_keys=[], terminal=dict(phase='blocked', reason='Stage blocked: AC3 cannot be completed (legacy whole-project stop)'))
        controller._save(self.conn, root, project); self.conn.commit()          # exactly what a whole-project stop of the task in progress used to leave behind
        self.tick(); self.stop_for_good()
        self.controller.resume(self.conn, self.root, 'Park the AC3 task and continue with the independent tasks', {'park': True})
        project = self.project()
        self.assertNotIn('terminal', project)
        self.assertEqual(project['parked']['x']['work'], recorded)
        self.assertEqual(project['parked']['x']['reason'], 'Stage blocked: AC3 cannot be completed (legacy whole-project stop)')
        self.tick()
        self.assertEqual(self.project()['active_task'], 'z')
        self.assertIn('Independent work', self.board.cards[self.only('developer')['task_id']]['body'])

    def test_park_cannot_be_combined_with_a_retry_or_a_grant_and_needs_a_note(self):
        self.park_x()
        self.pass_task()
        self.stop_for_good()
        for decision in ({'park': True, 'retry_stage': True}, {'park': True, 'extra_repairs': 1}, {'park': True, 'task': 'x'}):
            with self.assertRaises(ConfigurationError):
                self.controller.resume(self.conn, self.root, 'note for the decision', decision)
        with self.assertRaises(ConfigurationError):
            self.controller.resume(self.conn, self.root, '  ', {'task': 'x'})

    def test_a_replan_drops_parked_work_of_the_replaced_generation_and_records_it(self):
        self.park_x()
        controller = ProjectController(self.controller)
        root = self.state.read_root(self.conn, self.root); project = self.project()
        self.assertTrue(controller._replan(self.conn, root, project, None, 'The plan changes', ['F1|HIGH|AC1|x|plan change'], []))
        self.assertNotIn('parked', project); self.assertNotIn('active_task', project)
        self.assertTrue(any(e['kind'] == 'parked_dropped_by_replan' and e['tasks'] == ['x'] for e in project['orchestration_log']))


if __name__ == '__main__':
    unittest.main()


class MissingPatchTests(ParkingTests):
    """A resume continues only where the Factory stopped: never on a Hermes whose creation hook would leave a card the controller does not track."""
    def test_a_resume_is_refused_while_hermes_lacks_the_factory_patches(self):
        from unittest import mock
        self.park_x(); self.pass_task(); self.stop_for_good()
        before = (self.project(), self.stages('x'))
        report = dict(ok=False, message='hook names Hermes does not know: before_kanban_task_create')
        with mock.patch('factory_dashboard.hermes_compat.compat_report', return_value=report):
            with self.assertRaisesRegex(HermesUnpatched, 'Cannot resume: Hermes lacks patches'):
                self.controller.resume(self.conn, self.root, 'Repaired by hand', {'task': 'x'})
        self.assertEqual((self.project(), self.stages('x')), before)                       # nothing moved

    def test_a_card_that_was_not_registered_as_a_stage_is_rolled_back(self):
        from unittest import mock
        self.park_x(); self.pass_task(); self.stop_for_good()
        before = self.project()
        with mock.patch('board_fixture.WorkflowState.register_stage', lambda *a, **k: None):
            with self.assertRaisesRegex(HermesUnpatched, 'not registered: Hermes is missing the Factory patches'):
                self.controller.resume(self.conn, self.root, 'Repaired by hand', {'task': 'x'})
        self.assertEqual(self.project(), before)

    def test_reconcile_moves_nothing_while_hermes_lacks_the_factory_patches(self):
        from unittest import mock
        self.plan(tasks=[X, Y, Z])
        self.board.complete(self.only('developer'))                                     # finished evidence waiting to be judged
        before = (self.project(), self.stages('x'))
        with mock.patch('factory_dashboard.hermes_compat.compat_report', return_value=dict(ok=False, message='missing')):
            self.tick()
        self.assertEqual((self.project(), self.stages('x')), before)
        self.tick()                                                                     # patched again: the controller picks up where it stopped
        self.assertNotEqual(self.project(), before[0])
