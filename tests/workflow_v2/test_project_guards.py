import json
import tempfile
import unittest
from pathlib import Path

from board_fixture import Board
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.workflow_controller import WorkflowController
from factory_dashboard.workflow_guards import WorkflowGuards
from factory_dashboard.workflow_state import WorkflowState
from factory_dashboard.workflow_templates import _preset


class ProjectGuardTests(unittest.TestCase):
    def test_active_project_stage_can_claim_but_inactive_stage_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            board = Board(directory)
            self.addCleanup(board.conn.close)
            conn = board.conn
            state = WorkflowState();state.initialize(conn)
            root = board.create_task(conn, title='FACTORY: guarded', body='PROJECT_DIR: '+directory, assignee='factory-orchestrator')
            definition = {**_preset('feature'), 'execution_version': 2}
            conn.execute('INSERT INTO factory_workflow_roots(root_id,snapshot_id,definition,phase) VALUES(?,?,?,?)', (root,'s',json.dumps(definition),'preparing'))
            WorkflowController(board,state,directory).reconcile(conn,root)
            stage = board.ready()[0]
            guards = WorkflowGuards(None,Path(directory)/'board.db','default')
            guards._check(conn,'claim_task',stage['task_id'],{})
            document = json.loads(conn.execute('SELECT document FROM factory_project_execution').fetchone()[0])
            document['active_keys'] = []
            conn.execute('UPDATE factory_project_execution SET document=?',(json.dumps(document),))
            with self.assertRaisesRegex(ConfigurationError,'current'):
                guards._check(conn,'claim_task',stage['task_id'],{})


if __name__ == '__main__': unittest.main()
