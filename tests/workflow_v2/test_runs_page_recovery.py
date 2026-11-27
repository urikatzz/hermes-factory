"""The Runs page: per-card reasons, attempts already replaced by a later success, and recovery decisions applied through the resume script."""
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock

from factory_dashboard import run_boards
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.runs_service import RunsService


class CardDescriptionTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE factory_workflow_stages (task_id TEXT, stage_key TEXT);
            CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id TEXT, outcome TEXT, summary TEXT, error TEXT);
            INSERT INTO factory_workflow_stages VALUES ('old', 'task-style-bible.g16-repair-artist'), ('live', 'task-hud.g16-implement'), ('proj', 'project-retro-3');
            INSERT INTO task_runs (task_id, outcome, summary, error) VALUES ('old', 'blocked', 'first try', NULL), ('old', 'crashed', NULL, 'provider rejected key'),
                                                                          ('live', 'blocked', 'needs a decision on L9', NULL);''')

    def describe(self, card_id):
        return run_boards._describe_card(self.conn, dict(id=card_id, result=None), {'style-bible'})

    def test_plan_task_comes_from_the_stage_key(self):
        self.assertEqual(run_boards._plan_task('task-style-bible.g16-repair-artist'), 'style-bible')
        self.assertEqual(run_boards._plan_task('project-retro-3'), '')
        self.assertEqual(run_boards._plan_task(''), '')

    def test_an_attempt_whose_task_later_completed_is_marked_replaced_with_its_latest_reason(self):
        card = self.describe('old')
        self.assertTrue(card['superseded'])
        self.assertEqual((card['outcome'], card['reason']), ('crashed', 'provider rejected key'))

    def test_a_card_of_an_unfinished_task_still_needs_attention(self):
        card = self.describe('live')
        self.assertFalse(card['superseded'])
        self.assertEqual(card['reason'], 'needs a decision on L9')

    def test_project_level_and_unknown_cards_are_never_hidden_as_replaced(self):
        self.assertFalse(self.describe('proj')['superseded'])
        self.assertEqual(self.describe('missing')['reason'], '')


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        record = SimpleNamespace(status='active', root_id='t_root', db_path=Path('/boards/run-x/kanban.db'))
        self.registry = mock.Mock()
        self.registry.get.side_effect = lambda b: record if b == 'run-x' else None
        resolver = SimpleNamespace(registry=self.registry)
        self.record = record
        self.service = RunsService(resolver, '/home/h', cli_python='/venv/python', cli_script='/scripts/factory_boards.py')

    def run_ok(self, body):
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            if '--decision-file' in command:
                calls.append(json.loads(Path(command[command.index('--decision-file') + 1]).read_text()))
            return subprocess.CompletedProcess(command, 0, 't_root: project\n', '')
        with mock.patch('factory_dashboard.runs_service.subprocess.run', side_effect=fake):
            result = self.service.recover('run-x', body)
        return result, calls

    def test_a_retry_goes_through_the_resume_script_for_that_board_and_root(self):
        result, calls = self.run_ok({'action': 'retry_stage', 'note': 'patches are back, retry the step'})
        command = calls[0]
        self.assertEqual(command[:2], ['/venv/python', '/scripts/resume_factory_workflow.py'])
        for flag, value in (('--board', 'run-x'), ('--root', 't_root'), ('--board-db', '/boards/run-x/kanban.db'), ('--note', 'patches are back, retry the step')):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn('--retry-stage', command)
        self.assertEqual(result['result'], 't_root: project')

    def test_resuming_a_parked_task_names_it_and_extra_repairs_use_a_decision_file(self):
        _, calls = self.run_ok({'action': 'resume_task', 'task': 'scene-env-wiring', 'note': 'resume the parked wiring task'})
        self.assertEqual(calls[0][calls[0].index('--task') + 1], 'scene-env-wiring')
        _, calls = self.run_ok({'action': 'extra_repairs', 'count': 2, 'note': 'two more rounds for the art'})
        self.assertEqual(calls[1], {'extra_repairs': 2})

    def test_bad_requests_are_refused_before_anything_runs(self):
        with mock.patch('factory_dashboard.runs_service.subprocess.run') as run:
            for board, body in (('run-x', {'action': 'unblock', 'note': 'just unblock the card'}),
                                ('run-x', {'action': 'retry_stage', 'note': 'short'}),
                                ('default', {'action': 'retry_stage', 'note': 'the default board has no run'}),
                                ('run-x', {'action': 'resume_task', 'task': 'a; rm', 'note': 'bad task name here'}),
                                ('run-x', {'action': 'extra_repairs', 'count': 5, 'note': 'too many repairs asked'})):
                with self.assertRaises(ConfigurationError):
                    self.service.recover(board, body)
            self.record.status = 'paused'
            with self.assertRaises(ConfigurationError):
                self.service.recover('run-x', {'action': 'resume', 'note': 'paused boards resume first'})
            run.assert_not_called()

    def test_a_failed_resume_reports_the_scripts_own_reason(self):
        failed = subprocess.CompletedProcess([], 2, '', 'Traceback...\nConfigurationError: stage retry budget exhausted for task-x:0')
        with mock.patch('factory_dashboard.runs_service.subprocess.run', return_value=failed):
            with self.assertRaisesRegex(ConfigurationError, 'budget exhausted'):
                self.service.recover('run-x', {'action': 'retry_stage', 'note': 'one more try please'})


class ArchiveReplacedTest(unittest.TestCase):
    def setUp(self):
        self.board = SimpleNamespace(board_id='run-x', status='active', root_id='t_root', db_path=Path('/boards/run-x/kanban.db'))
        registry = mock.Mock()
        registry.get.side_effect = lambda b: self.board if b == 'run-x' else None
        self.kb = mock.Mock()
        self.kb.archive_task.return_value = True
        hermes = mock.Mock()
        hermes.board_api.return_value = self.kb
        hermes.connect.return_value = mock.MagicMock()
        self.boards = run_boards.RunBoards(registry, hermes=hermes)
        blockers = [dict(id='old1', superseded=True), dict(id='old2', superseded=True), dict(id='live', superseded=False), dict(id='t_root', superseded=False)]
        mock.patch.object(self.boards, 'summary', return_value=dict(blockers=blockers)).start()
        self.scope = mock.patch.object(self.boards, '_scoped', return_value=mock.MagicMock()).start()
        self.addCleanup(mock.patch.stopall)

    def test_replaced_attempts_are_archived_inside_the_controller_scope(self):
        self.assertEqual(self.boards.archive_replaced('run-x', ['old1', 'old2', 'old1']), ['old1', 'old2'])
        self.assertEqual([c.args[1] for c in self.kb.archive_task.call_args_list], ['old1', 'old2'])
        self.scope.assert_called_once()

    def test_a_card_that_still_matters_refuses_the_whole_request(self):
        for cards in (['old1', 'live'], ['t_root'], ['unknown'], []):
            with self.assertRaises(ConfigurationError):
                self.boards.archive_replaced('run-x', cards)
        self.kb.archive_task.assert_not_called()

    def test_only_a_running_or_paused_run_can_be_tidied(self):
        self.board.status = 'archived'
        with self.assertRaises(ConfigurationError):
            self.boards.archive_replaced('run-x', ['old1'])
        self.kb.archive_task.assert_not_called()


if __name__ == '__main__':
    unittest.main()
