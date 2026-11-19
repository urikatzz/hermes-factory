"""A refused command is an incident to record, not automatically a blocked task.

The controller decides from verified acceptance criteria and from *unresolved required* tools; it never trusts
free text and never silently ignores malformed incident evidence.
"""
import json
import tempfile
import unittest

from board_fixture import Board
from factory_dashboard.tool_incidents import tool_blockers, validate_tool_incidents
from factory_dashboard.workflow_controller import WorkflowController
from factory_dashboard.workflow_gate import evaluate_cycle
from factory_dashboard.workflow_handoffs import StageResult, normalize_handoff
from factory_dashboard.workflow_state import WorkflowState
from factory_dashboard.workflow_templates import _preset


def incident(**overrides):
    return {**dict(command='rm -rf scratch', reason='safety_guard', required=False, resolved=True,
                   alternative='fw.py clean', affected_criteria=[]), **overrides}


class ToolBlockerTests(unittest.TestCase):
    def test_optional_tool_rejected_continues(self):
        data = dict(tool_incidents=[incident(required=False, resolved=False, alternative='')])
        self.assertEqual(tool_blockers(data), [])

    def test_required_tool_rejected_with_working_alternative_continues(self):
        data = dict(tool_incidents=[incident(required=True, resolved=True, alternative='fw.py clean')])
        self.assertEqual(tool_blockers(data), [])

    def test_required_tool_unavailable_without_alternative_blocks(self):
        data = dict(tool_incidents=[incident(command='unity', required=True, resolved=False, alternative='', affected_criteria=['AC2'])])
        self.assertEqual(len(tool_blockers(data)), 1)
        self.assertIn('unity', tool_blockers(data)[0])

    def test_optional_tool_that_threatens_a_criterion_still_blocks_when_unresolved(self):
        data = dict(tool_incidents=[incident(required=False, resolved=False, alternative='', affected_criteria=['AC1'])])
        self.assertEqual(len(tool_blockers(data)), 1)

    def test_legacy_blocked_tools_without_incidents_still_block(self):
        self.assertEqual(len(tool_blockers(dict(blocked_tools=[dict(cmd='blender', block='missing', needed_for='AC1', attempts=1)]))), 1)
        self.assertEqual(tool_blockers(dict(blocked_tools=[])), [])
        self.assertEqual(tool_blockers({}), [])

    def test_structured_incidents_account_for_legacy_blocked_tools(self):
        data = dict(blocked_tools=[dict(cmd='rm -rf scratch', block='guard', needed_for='none', attempts=1)], tool_incidents=[incident()])
        self.assertIsNone(validate_tool_incidents(data, {'AC1'}))
        self.assertEqual(tool_blockers(data), [])

    def test_blocked_tool_missing_from_incidents_is_malformed_not_ignored(self):
        data = dict(blocked_tools=[dict(cmd='unity', block='missing', needed_for='AC2', attempts=1)], tool_incidents=[incident()])
        self.assertIn('not accounted', validate_tool_incidents(data, {'AC1'}))


class ValidationTests(unittest.TestCase):
    def check(self, **overrides):
        return validate_tool_incidents(dict(tool_incidents=[incident(**overrides)]), {'AC1', 'AC2'})

    def test_well_formed_incident_is_valid(self):
        self.assertIsNone(self.check())
        self.assertIsNone(validate_tool_incidents({}, {'AC1'}))
        self.assertIsNone(validate_tool_incidents(dict(tool_incidents=[]), {'AC1'}))

    def test_malformed_incidents_are_rejected(self):
        for bad in (dict(command=''), dict(command=7), dict(reason=''), dict(required='yes'), dict(resolved=1),
                    dict(alternative=None), dict(affected_criteria='AC1'), dict(affected_criteria=['nope']),
                    dict(affected_criteria=['AC9']), dict(resolved=True, alternative='')):
            with self.subTest(bad=bad):
                self.assertIsNotNone(self.check(**bad))

    def test_missing_fields_and_wrong_container_are_rejected(self):
        self.assertIsNotNone(validate_tool_incidents(dict(tool_incidents={'command': 'x'}), {'AC1'}))
        self.assertIsNotNone(validate_tool_incidents(dict(tool_incidents=['rm']), {'AC1'}))
        self.assertIsNotNone(validate_tool_incidents(dict(tool_incidents=[{'command': 'x'}]), {'AC1'}))
        self.assertIsNotNone(validate_tool_incidents(dict(blocked_tools='oops', tool_incidents=[]), {'AC1'}))
        # Without structured incidents the legacy meaning is unchanged: valid evidence that still blocks.
        self.assertIsNone(validate_tool_incidents(dict(blocked_tools='oops'), {'AC1'}))
        self.assertEqual(len(tool_blockers(dict(blocked_tools='oops'))), 1)


def result(kind='verify', **metadata):
    base = dict(verdict='PASS' if kind == 'verify' else 'NO_BLOCKING_FINDINGS', manifest_sha12='abcdef123456', source_profile='verifier',
                ac_ids=['AC1'], ac_results={'AC1': 'pass'}, release_audit='PASS', findings=[], failed_checks=[], checks_failed=0)
    return StageResult(True, '', kind, 1, {**base, **metadata})


WRITER = result('implement', verdict='DONE', ac_ids=['AC1'])


class GateTests(unittest.TestCase):
    def decide(self, **metadata):
        return evaluate_cycle(WRITER, [result(**metadata)], None, 2, 0, {}).decision

    def test_pass_with_resolved_incident_passes(self):
        self.assertEqual(self.decide(tool_incidents=[incident()], blocked_tools=[dict(cmd='rm -rf scratch')]), 'pass')

    def test_unresolved_required_tool_needs_a_human(self):
        self.assertEqual(self.decide(tool_incidents=[incident(required=True, resolved=False, alternative='', affected_criteria=['AC1'])]), 'human_review')

    def test_failed_acceptance_criterion_fails_verification_even_with_resolved_incidents(self):
        self.assertEqual(self.decide(verdict='FAIL', ac_results={'AC1': 'fail'}, tool_incidents=[incident()]), 'repair')

    def test_legacy_blocked_tools_still_escalate(self):
        self.assertEqual(self.decide(blocked_tools=[dict(cmd='blender', needed_for='AC1')]), 'human_review')


class HandoffTests(unittest.TestCase):
    """normalize_handoff must reject malformed incident evidence instead of passing it to the controller."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.board = Board(self.temp.name)
        self.addCleanup(self.board.conn.close)
        self.conn = self.board.conn
        state = WorkflowState()
        state.initialize(self.conn)
        definition = {**_preset('feature'), 'execution_version': 2}
        self.root = self.board.create_task(self.conn, title='FACTORY: t', body='PROJECT_DIR: ' + self.temp.name, assignee='factory-orchestrator')
        self.conn.execute('INSERT INTO factory_workflow_roots(root_id,snapshot_id,definition,phase) VALUES(?,?,?,?)', (self.root, 's', json.dumps(definition), 'preparing'))
        self.conn.commit()

    def normalized(self, **overrides):
        # Reuse the board fixture's completion so every other handoff field is valid.
        WorkflowController(self.board, WorkflowState(), self.temp.name).reconcile(self.conn, self.root)
        stage = self.board.ready()[0]
        self.board.complete(stage, **overrides)
        stage = dict(self.conn.execute('SELECT * FROM factory_workflow_stages WHERE task_id=?', (stage['task_id'],)).fetchone())
        run = dict(self.conn.execute('SELECT * FROM task_runs WHERE task_id=?', (stage['task_id'],)).fetchone())
        run['metadata'] = json.loads(run['metadata'])
        task = dict(self.conn.execute('SELECT id,status,current_run_id FROM tasks WHERE id=?', (stage['task_id'],)).fetchone())
        return normalize_handoff(task, run, stage)

    def test_unreadable_incident_evidence_is_invalid_for_every_stage_kind(self):
        res = self.normalized(tool_incidents=[{'command': 'x'}])
        self.assertFalse(res.valid)
        self.assertIn('tool incident', res.reason.lower())


if __name__ == '__main__':
    unittest.main()
