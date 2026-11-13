from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from board_fixture import Board
from factory_dashboard.workflow_controller import WorkflowController
from factory_dashboard.workflow_state import WorkflowState
from factory_dashboard.workflow_templates import _preset


class ProjectControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.board = Board(self.temp.name)
        self.addCleanup(self.board.conn.close)
        self.conn = self.board.conn
        self.state = WorkflowState()
        self.state.initialize(self.conn)
        self.definition = {**_preset('feature'), 'execution_version': 2, 'max_repairs': 2}
        self.root = self.board.create_task(self.conn, title='FACTORY: test', body='PROJECT_MODE: existing\nPROJECT_DIR: '+self.temp.name+'\nREQUEST: Build a game', assignee='factory-orchestrator')
        self.conn.execute('INSERT INTO factory_workflow_roots(root_id,snapshot_id,definition,phase) VALUES(?,?,?,?)',
                          (self.root, 'snapshot', json.dumps(self.definition), 'preparing'))
        self.conn.commit()
        self.controller = WorkflowController(self.board, self.state, self.temp.name)

    def tick(self):
        return self.controller.reconcile(self.conn, self.root)

    def only(self, profile):
        rows = self.board.ready()
        self.assertEqual([r['profile'] for r in rows], [profile])
        return rows[0]

    def plan(self, art=False, audio=False, tasks=None):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=dict(art=art, audio=audio, ui=False, ux=False))
        self.tick()
        for profile in [*(['art-director'] if art else []), *(['audio-director'] if audio else [])]:
            self.board.complete(self.only(profile))
            self.tick()
        stage = self.only('architect')
        plan = Path(self.temp.name) / 'project-plan.json'
        plan.write_text(json.dumps(dict(tasks=tasks or [dict(id='code', title='Build code', owner='developer',
                              dependencies=[], acceptance={'AC1': 'Works'}, needs=dict(art=False, audio=False, ui=False, ux=False))])))
        metadata = self.board.complete(stage)
        self.conn.execute('INSERT INTO attachments VALUES(?,?)', (stage['task_id'], str(plan)))
        run = self.conn.execute('SELECT metadata FROM task_runs WHERE task_id=?', (stage['task_id'],)).fetchone()
        data = json.loads(run[0]);data['artifacts'].append(str(plan))
        self.conn.execute('UPDATE task_runs SET metadata=? WHERE task_id=?', (json.dumps(data),stage['task_id']))
        self.conn.commit()
        self.tick()

    def test_no_reviewers_are_created_until_verifier_passes(self):
        self.plan()
        self.board.complete(self.only('developer'))
        self.tick()
        self.only('verifier')
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE kind='review'").fetchone())
        self.board.complete(self.only('verifier'))
        self.tick()
        self.assertEqual([r['profile'] for r in self.board.ready()], ['claude-reviewer', 'security-reviewer'])

    def test_failed_verification_repairs_before_any_reviews_and_reverifies(self):
        self.plan()
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'})
        self.tick()
        self.only('fixer')
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE kind='review'").fetchone())
        self.board.complete(self.only('fixer'));self.tick()
        self.only('verifier')

    def test_restart_does_not_duplicate_cards(self):
        self.plan()
        before = len(self.board.cards)
        self.controller = WorkflowController(self.board, self.state, self.temp.name)
        self.tick();self.tick()
        self.assertEqual(len(self.board.cards), before)
        self.only('developer')

    def test_legacy_definition_keeps_legacy_preparation(self):
        self.definition.pop('execution_version')
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?', (json.dumps(self.definition),))
        self.tick()
        self.only('architect')

    def test_tasks_finish_before_final_integration_then_retro_then_delivery(self):
        self.plan()
        for _ in range(2):
            self.board.complete(self.only('developer'));self.tick()
            self.board.complete(self.only('verifier'));self.tick()
            for row in self.board.ready(): self.board.complete(row)
            self.tick()
        retro = self.only('factory-retro')
        self.assertNotEqual(self.state.read_root(self.conn,self.root)['phase'], 'delivered')
        self.board.complete(retro)
        result = self.tick()
        self.assertEqual(result['phase'], 'delivered')
        self.assertEqual(self.board.get_task(self.conn,self.root).status,'done')

    def test_director_plans_reach_architect_and_dependent_code_waits_for_asset_review(self):
        tasks = [
            dict(id='sprites', title='Make sprites', owner='artist', dependencies=[], acceptance={'AC1':'Sprite'},
                 needs=dict(art=True,audio=False,ui=False,ux=False)),
            dict(id='code', title='Integrate sprites', owner='developer', dependencies=['sprites'], acceptance={'AC1':'Integrated'},
                 needs=dict(art=True,audio=False,ui=False,ux=False)),
        ]
        self.plan(art=True,tasks=tasks)
        self.only('artist')
        architect = next(c for c in self.board.cards.values() if c['assignee']=='architect')
        self.assertIn('art-director',architect['body'])
        self.board.complete(self.only('artist'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        self.assertIn('art-reviewer',[r['profile'] for r in self.board.ready()])
        self.assertNotIn('developer',[r['profile'] for r in self.board.ready()])

    def test_stale_verifier_manifest_never_launches_review(self):
        self.plan();self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),manifest_sha12='111111111111')
        self.tick()
        self.only('factory-retro')
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE kind='review'").fetchone())

    def test_repair_limit_escalates_and_runs_retro_without_delivering(self):
        self.definition['max_repairs']=0
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?',(json.dumps(self.definition),))
        self.plan();self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),verdict='FAIL',ac_results={'AC1':'fail'});self.tick()
        self.board.complete(self.only('factory-retro'))
        self.assertEqual(self.tick()['phase'],'human_review')
        self.assertEqual(self.board.get_task(self.conn,self.root).status,'blocked')

    def test_missing_perceptual_evidence_stops_remaining_panel_and_runs_retro(self):
        tasks=[dict(id='sprites',title='Make sprites',owner='artist',dependencies=[],acceptance={'AC1':'Sprite'},
                    needs=dict(art=True,audio=False,ui=False,ux=False))]
        self.plan(art=True,tasks=tasks)
        self.board.complete(self.only('artist'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        art=next(r for r in self.board.ready() if r['profile']=='art-reviewer')
        self.board.complete(art);self.tick()
        self.only('factory-retro')

    def test_environment_block_can_resume_with_fresh_verification_after_human_recovery(self):
        self.plan();self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),ac_results={'AC1':'unverified:environment'})
        self.tick();self.board.complete(self.only('factory-retro'));self.tick()
        self.assertEqual(self.state.read_root(self.conn,self.root)['phase'],'blocked')
        self.controller.resume(self.conn,self.root,'Required test environment is now available')
        stage=self.only('verifier')
        self.assertEqual(stage['cycle'],0)
        self.assertEqual(stage['evidence_retry'],1)
        self.assertIn('Required test environment is now available',self.board.cards[stage['task_id']]['body'])

    def test_visual_mismatch_calls_artist_then_verifier_not_developer(self):
        tasks=[dict(id='sprites',title='Make sprites',owner='artist',dependencies=[],acceptance={'AC1':'Sprite'},
                    needs=dict(art=True,audio=False,ui=False,ux=False))]
        self.plan(art=True,tasks=tasks)
        self.board.complete(self.only('artist'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        project=json.loads(self.conn.execute('SELECT document FROM factory_project_execution').fetchone()[0])
        director=next(p for p in project['plans'] if p['profile']=='art-director')
        for row in self.board.ready():
            if row['profile']!='art-reviewer':
                self.board.complete(row)
                continue
            folder=Path(self.temp.name)/'comparison';folder.mkdir()
            image=folder/'render.png';image.write_bytes(b'render')
            report=folder/'comparison.json'
            report.write_text(json.dumps(dict(schema='factory-comparison/v1',plan_sha256=director['sha256'],manifest_sha12='abcdef123456',
                mode='rendered_asset',source='tool',outcome='fail',criteria=[dict(rule='S1',expected='Round',observed='Square',outcome='fail')],evidence=[str(image)])))
            self.board.complete(row,verdict='CHANGES_REQUIRED',findings=['F1|HIGH|AC1|sprite.png|Silhouette differs from director plan'],artifacts=[str(report),str(image)])
        self.tick();self.only('artist')
        self.board.complete(self.only('artist'));self.tick();self.only('verifier')

    def test_new_project_director_plans_missing_bible_instead_of_requiring_preexisting_assets(self):
        self.definition={**_preset('art'),'execution_version':2}
        self.definition['prepare']['instructions']+='\nKeep the mascot green.'
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?',(json.dumps(self.definition),))
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope=dict(art=True,audio=False,ui=False,ux=False))
        self.tick()
        card=self.board.cards[self.only('art-director')['task_id']]
        self.assertIn('style-bible creation task',card['body'])
        self.assertNotIn('no approved style bible: submit an Art task',card['body'])
        self.assertIn('Keep the mascot green.',card['body'])

    def test_terminal_outcome_retires_inflight_sibling_reviews(self):
        tasks=[dict(id='sprites',title='Make sprites',owner='artist',dependencies=[],acceptance={'AC1':'Sprite'},
                    needs=dict(art=True,audio=False,ui=False,ux=False))]
        self.plan(art=True,tasks=tasks);self.board.complete(self.only('artist'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        siblings=[r for r in self.board.ready() if r['profile']!='art-reviewer']
        for row in siblings:self.conn.execute("UPDATE tasks SET status='running' WHERE id=?",(row['task_id'],))
        art=next(r for r in self.board.ready() if r['profile']=='art-reviewer')
        self.board.complete(art);self.tick()
        self.assertTrue(all(self.board.get_task(self.conn,r['task_id']).status=='blocked' for r in siblings))


if __name__ == '__main__': unittest.main()
