from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from board_fixture import Board
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.workflow_controller import WorkflowController
from factory_dashboard.workflow_state import WorkflowState
from factory_dashboard.workflow_templates import _preset

NEEDS = dict(art=False, audio=False, ui=False, ux=False)
CODE = dict(id='code', title='Build code', owner='developer', dependencies=[], acceptance={'AC1': 'Works'}, needs=NEEDS)
MIXED = dict(id='mixed', title='Mixed presentation', owner='developer', dependencies=[], acceptance={'AC1': 'Works'}, needs={**NEEDS, 'art': True, 'ui': True})
SPRITES = dict(id='sprites', title='Make sprites', owner='artist', dependencies=[], acceptance={'AC1': 'Sprite'}, needs={**NEEDS, 'art': True})


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

    def architect(self, tasks=None, **overrides):
        stage = self.only('architect')
        plan = Path(self.temp.name) / f'project-plan-{stage["cycle"]}' / 'project-plan.json'
        plan.parent.mkdir()
        plan.write_text(json.dumps(dict(tasks=tasks or [CODE])))
        self.board.complete(stage, **overrides)
        self.conn.execute('INSERT INTO attachments VALUES(?,?)', (stage['task_id'], str(plan)))
        run = self.conn.execute('SELECT metadata FROM task_runs WHERE task_id=?', (stage['task_id'],)).fetchone()
        data = json.loads(run[0]);data['artifacts'].append(str(plan))
        self.conn.execute('UPDATE task_runs SET metadata=? WHERE task_id=?', (json.dumps(data),stage['task_id']))
        self.conn.commit()
        self.tick()

    def plan(self, art=False, audio=False, tasks=None):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=dict(art=art, audio=audio, ui=False, ux=False))
        self.tick()
        for profile in [*(['art-director'] if art else []), *(['audio-director'] if audio else [])]:
            self.board.complete(next(r for r in self.board.ready() if r['profile'] == profile))
        self.tick()
        if art:
            self.approve()
        self.architect(tasks)
        self.board.complete(self.only('claude-reviewer'))
        self.tick()

    def approve(self, note='Approved: matches the intended look'):
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        self.controller.resume(self.conn, self.root, note)

    def similarity(self, folder, score=92, status=None):
        path = Path(folder) / 'similarity.json'
        path.write_text(json.dumps(dict(schema='factory-similarity/v1', model='typesafe/jev-router', threshold=80, blocked_tools=[],
            assets=[dict(file='sprite.png', score=score, status=status or ('pass' if score is not None and score >= 80 else 'fail'))])))
        return str(path)

    def panel(self):
        return [r['profile'] for r in self.board.ready()]

    def project(self):
        return json.loads(self.conn.execute('SELECT document FROM factory_project_execution').fetchone()[0])

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

    def test_repair_writer_may_report_only_the_acs_it_repaired(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope=NEEDS);self.tick()
        self.architect([{**CODE, 'acceptance': {'AC1': 'Works', 'AC2': 'Also works'}}],ac_ids=['AC1','AC2'])
        self.board.complete(self.only('claude-reviewer'));self.tick()
        self.board.complete(self.only('developer'),ac_ids=['AC1','AC2']);self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail', 'AC2': 'pass'});self.tick()
        self.board.complete(self.only('fixer'),ac_ids=['AC1']);self.tick()
        self.only('verifier')

    def test_summary_note_after_the_header_line_is_accepted(self):
        self.plan()
        self.board.complete(self.only('developer'), summary_suffix=' - re-ran the baseline gates first');self.tick()
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

    def fail_first_task(self):
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),verdict='FAIL',ac_results={'AC1':'fail'});self.tick()

    def test_repair_limit_returns_to_architect_then_escalates_without_delivering(self):
        self.definition['max_repairs']=0
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?',(json.dumps(self.definition),))
        self.plan()
        for generation in (1, 2):
            self.fail_first_task()
            stage=self.only('architect')
            self.assertEqual(stage['cycle'],generation)
            card=self.board.cards[stage['task_id']]['body']
            self.assertIn('Repairs did not converge',card)
            self.assertIn('AC1: fail',card)
            self.architect()
            self.board.complete(self.only('claude-reviewer'));self.tick()
            self.assertEqual(self.only('developer')['stage_key'],f'task-code.g{generation}-implement')
        self.fail_first_task()
        self.board.complete(self.only('factory-retro'))
        self.assertEqual(self.tick()['phase'],'human_review')
        self.assertEqual(self.board.get_task(self.conn,self.root).status,'blocked')

    def test_declared_plan_defect_replans_instead_of_repairing(self):
        self.plan()
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),verdict='FAIL',ac_results={'AC1':'fail'},plan_defect='AC1 contradicts the request')
        self.tick()
        self.assertIn('AC1 contradicts the request',self.board.cards[self.only('architect')['task_id']]['body'])
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE kind='repair'").fetchone())

    def test_replan_cannot_change_a_task_that_already_passed(self):
        second=dict(CODE,id='more',dependencies=['code'])
        self.plan(tasks=[CODE,second])
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        for row in self.board.ready():self.board.complete(row)
        self.tick()
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),verdict='FAIL',ac_results={'AC1':'fail'},plan_defect='Task is too large')
        self.tick()
        self.architect([dict(CODE,title='Rewritten history'),second])
        self.only('factory-retro')

    def test_plan_review_findings_return_plan_to_architect_before_any_task(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope=NEEDS);self.tick()
        self.architect()
        self.board.complete(self.only('claude-reviewer'),findings=['F1|HIGH|AC1|code|Criterion is not testable'])
        self.tick()
        stage=self.only('architect')
        self.assertEqual(stage['cycle'],1)
        self.assertIn('Criterion is not testable',self.board.cards[stage['task_id']]['body'])
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE kind='implement'").fetchone())
        self.architect()
        self.board.complete(self.only('claude-reviewer'),findings=['F1|LOW|-|code|Consider a clearer title'])
        self.tick()
        self.only('developer')

    def test_invalid_architect_plan_returns_to_architect_instead_of_ending_the_run(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope=NEEDS);self.tick()
        self.architect(tasks=[{**CODE, 'owner': 'nobody'}])
        stage=self.only('architect')
        self.assertEqual(stage['cycle'],1)
        self.assertIn('Invalid task owner',self.board.cards[stage['task_id']]['body'])
        self.architect()
        self.only('claude-reviewer')

    def test_plan_review_that_never_passes_stops_for_a_human(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope=NEEDS);self.tick()
        for _ in range(3):
            self.architect()
            self.board.complete(self.only('claude-reviewer'),findings=['F1|BLOCKER|-|code|Request requirement is missing'])
            self.tick()
        self.board.complete(self.only('factory-retro'))
        self.assertEqual(self.tick()['phase'],'human_review')

    def test_architect_can_request_a_director_the_orchestrator_skipped(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope=NEEDS);self.tick()
        self.architect(scope_additions=['art'])
        self.board.complete(self.only('art-director'));self.tick()
        self.approve()
        stage=self.only('architect')
        self.assertEqual(stage['cycle'],1)
        self.assertIn('art-director',self.board.cards[stage['task_id']]['body'])
        self.architect([SPRITES])
        self.board.complete(self.only('claude-reviewer'));self.tick()
        self.only('artist')
        self.assertTrue(self.project()['scope']['art'])

    def test_directors_plan_concurrently(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope={**NEEDS,'art':True,'audio':True});self.tick()
        self.assertEqual(self.panel(),['art-director','audio-director'])
        self.board.complete(self.board.ready()[1]);self.tick()
        self.only('art-director')
        self.board.complete(self.only('art-director'));self.tick()
        self.assertEqual(self.board.ready(),[])
        self.approve()
        self.only('architect')

    def test_art_plan_waits_for_human_approval_and_rejection_returns_it_with_feedback(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope={**NEEDS,'art':True});self.tick()
        self.board.complete(self.only('art-director'));self.tick()
        self.assertEqual(self.board.ready(),[])
        self.assertEqual(self.board.get_task(self.conn,self.root).status,'blocked')
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE profile IN ('architect','factory-retro')").fetchone())
        with self.assertRaisesRegex(Exception,'feedback'):
            self.controller.resume(self.conn,self.root,'REJECT:')
        self.controller.resume(self.conn,self.root,'REJECT: Too dark, use the pastel palette')
        stage=self.only('art-director')
        self.assertEqual(stage['cycle'],1)
        self.assertIn('Too dark, use the pastel palette',self.board.cards[stage['task_id']]['body'])
        self.board.complete(stage);self.tick()
        self.assertEqual(self.board.ready(),[])
        self.approve('Approved')
        self.assertIn('human_approvals',self.board.cards[self.only('architect')['task_id']]['body'])

    def test_audio_only_project_needs_no_human_plan_approval(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope={**NEEDS,'audio':True});self.tick()
        self.board.complete(self.only('audio-director'));self.tick()
        self.only('architect')

    def test_repair_after_review_reruns_only_affected_reviewers(self):
        ux=dict(CODE,needs={**NEEDS,'ui':True,'ux':True})
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope={**NEEDS,'ui':True,'ux':True});self.tick()
        self.architect([ux])
        self.board.complete(self.only('claude-reviewer'));self.tick()
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        self.assertEqual(self.panel(),['claude-reviewer','security-reviewer','ux-reviewer','ui-reviewer'])
        for row in self.board.ready():
            extra=dict(verdict='CHANGES_REQUIRED',findings=['F1|HIGH|AC1|menu|Dead end']) if row['profile']=='ux-reviewer' else {}
            self.board.complete(row,**extra)
        self.tick()
        self.board.complete(self.only('fixer'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        self.assertEqual(self.panel(),['claude-reviewer','security-reviewer','ux-reviewer'])
        for row in self.board.ready():self.board.complete(row)
        self.tick()
        # Final integration always reviews the delivered manifest with the complete panel.
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        self.assertEqual(self.panel(),['claude-reviewer','security-reviewer','ux-reviewer','ui-reviewer'])

    def test_repair_before_any_review_still_owes_the_complete_panel(self):
        self.plan()
        self.fail_first_task()
        self.board.complete(self.only('fixer'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        self.assertEqual(self.panel(),['claude-reviewer','security-reviewer'])

    def test_second_code_reviewer_joins_only_high_risk_tasks_and_integration(self):
        self.definition['reviewers'].append(dict(key='codex-reviewer',kind='review',profile='codex-reviewer',instructions=''))
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?',(json.dumps(self.definition),))
        risky=dict(CODE,id='auth',risk='high',dependencies=['code'])
        self.plan(tasks=[CODE,risky])
        expected=[['claude-reviewer','security-reviewer'],['claude-reviewer','codex-reviewer','security-reviewer'],
                  ['claude-reviewer','codex-reviewer','security-reviewer']]
        for panel in expected:
            self.board.complete(self.only('developer'));self.tick()
            self.board.complete(self.only('verifier'));self.tick()
            self.assertEqual(self.panel(),panel)
            for row in self.board.ready():self.board.complete(row)
            self.tick()
        self.only('factory-retro')

    def test_integration_failure_routes_to_the_owner_of_the_failing_criterion(self):
        code=dict(CODE,id='code',acceptance={'AC2':'Integrated'},needs={**NEEDS,'art':True},dependencies=['sprites'])
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope={**NEEDS,'art':True});self.tick()
        self.board.complete(self.only('art-director'));self.tick()
        self.approve()
        self.architect([SPRITES,code],ac_ids=['AC1','AC2'])
        self.board.complete(self.only('claude-reviewer'));self.tick()
        for writer,ac in (('artist','AC1'),('developer','AC2')):
            self.board.complete(self.only(writer),ac_ids=[ac]);self.tick()
            self.board.complete(self.only('verifier'),ac_results={ac:'pass'});self.tick()
            for row in self.board.ready():self.complete_review(row)
            self.tick()
        self.board.complete(self.only('developer'),ac_ids=['AC1','AC2']);self.tick()
        self.board.complete(self.only('verifier'),verdict='FAIL',ac_results={'AC1':'fail','AC2':'pass'});self.tick()
        stage=self.only('artist')
        self.assertIn('"repair_attribution": {"AC1": ["sprites"]}',self.board.cards[stage['task_id']]['body'])

    def complete_review(self,row,mode='rendered_asset'):
        if row['profile']!='art-reviewer':
            return self.board.complete(row)
        director=next(p for p in self.project()['plans'] if p['profile']=='art-director')
        folder=Path(self.temp.name)/f'comparison-{row["task_id"]}';folder.mkdir()
        image=folder/'render.png';image.write_bytes(b'render')
        report=folder/'comparison.json'
        report.write_text(json.dumps(dict(schema='factory-comparison/v1',plan_sha256=director['sha256'],manifest_sha12='abcdef123456',
            mode=mode,source='tool',outcome='pass',criteria=[dict(rule='S1',expected='Round',observed='Round',outcome='pass')],evidence=[str(image)])))
        self.board.complete(row,artifacts=[str(report),str(image),self.similarity(folder)])

    def art_review(self):
        self.plan(art=True,tasks=[SPRITES])
        self.board.complete(self.only('artist'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        for row in self.board.ready():
            if row['profile']!='art-reviewer':self.board.complete(row)
        folder=Path(self.temp.name)/'gate';folder.mkdir()
        return self.only('art-reviewer'),folder

    def test_low_similarity_returns_to_artist_without_a_detailed_comparison(self):
        row,folder=self.art_review()
        self.board.complete(row,verdict='CHANGES_REQUIRED',findings=['F1|HIGH|AC1|sprite.png|[similarity] 61% match, below 80%: palette'],
                            artifacts=[self.similarity(folder,61)])
        self.tick()
        self.only('artist')

    def test_low_similarity_cannot_be_approved(self):
        row,folder=self.art_review()
        self.board.complete(row,artifacts=[self.similarity(folder,61)])
        self.tick()
        self.only('factory-retro')

    def test_similarity_score_is_required_before_art_approval(self):
        row,folder=self.art_review()
        self.board.complete(row,artifacts=[self.similarity(folder,None,'unverified')])
        self.tick()
        self.only('factory-retro')

    def test_resume_during_plan_review_retries_the_plan_reviewer(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope=NEEDS);self.tick()
        self.architect()
        reviewer=self.only('claude-reviewer')
        self.conn.execute("UPDATE tasks SET status='blocked' WHERE id=?",(reviewer['task_id'],));self.conn.commit()
        self.tick();self.board.complete(self.only('factory-retro'));self.tick()
        self.controller.resume(self.conn,self.root,'Reviewer credentials restored')
        stage=self.only('claude-reviewer')
        self.assertEqual((stage['stage_key'],stage['evidence_retry']),('project-plan-review',1))

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

    def verify_with(self, **evidence):
        self.plan();self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),**evidence)
        return self.tick()

    GUARD = dict(command='rm -rf scratch', reason='safety_guard', required=False, resolved=True, alternative='fw.py clean', affected_criteria=[])

    def test_guard_refused_cleanup_with_a_working_alternative_does_not_block_the_project(self):
        legacy=[dict(cmd='rm -rf scratch',block='dangerous',needed_for='none',attempts=1)]
        self.verify_with(blocked_tools=legacy,tool_incidents=[self.GUARD])
        self.assertEqual([r['profile'] for r in self.board.ready()],['claude-reviewer','security-reviewer'])
        self.assertNotEqual(self.state.read_root(self.conn,self.root)['phase'],'blocked')

    def test_unresolved_required_tool_still_blocks_the_project(self):
        needed=dict(self.GUARD,command='unity',required=True,resolved=False,alternative='',affected_criteria=['AC1'])
        self.verify_with(blocked_tools=[dict(cmd='unity',block='missing',needed_for='AC1',attempts=1)],tool_incidents=[needed],ac_results={'AC1':'unverified:environment'})
        self.only('factory-retro');self.assertFalse(self.board.cards and [r for r in self.board.ready() if r['kind']=='review'])

    def test_unresolved_required_tool_blocks_even_when_the_verifier_claims_pass(self):
        needed=dict(self.GUARD,command='unity',required=True,resolved=False,alternative='',affected_criteria=['AC1'])
        self.verify_with(tool_incidents=[needed])
        self.only('factory-retro')

    def test_legacy_blocked_tools_without_incidents_still_block(self):
        self.verify_with(blocked_tools=[dict(cmd='rm -rf scratch',block='dangerous',needed_for='none',attempts=1)])
        self.only('factory-retro')

    def test_malformed_incident_evidence_stops_for_human_review_and_never_launches_reviews(self):
        self.verify_with(tool_incidents=[dict(command='x')])
        terminal=self.project()['terminal']
        self.assertEqual(terminal['phase'],'human_review')
        self.assertIn('tool incident',terminal['reason'])
        self.assertFalse([r for r in self.board.ready() if r['kind']=='review'])

    # --- human decisions: scoped waivers, constraint conflicts and per-agent repair (the milestone-1 incident) ---
    def mixed(self, task=MIXED, **verify):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=dict(art=True, audio=False, ui=True, ux=False)); self.tick()
        self.board.complete(self.only('art-director')); self.tick()
        self.approve()
        self.architect([task])
        self.board.complete(self.only('claude-reviewer')); self.tick()
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), **verify); self.tick()

    def review_round(self, art=True, ui=True):
        folder = Path(self.temp.name) / f'gate-{len(list(Path(self.temp.name).iterdir()))}'
        folder.mkdir()
        for row in self.board.ready():
            if row['profile'] == 'art-reviewer' and art:
                self.board.complete(row, verdict='CHANGES_REQUIRED', artifacts=[self.similarity(folder, 5)],
                                    findings=['F2|HIGH|AC1|sprite.png|[similarity] 5% match to the reference, below 80%'])
            elif row['profile'] == 'ui-reviewer' and ui:
                self.board.complete(row, verdict='CHANGES_REQUIRED', findings=['F1|MEDIUM|AC1|Assets/Scripts/Builder.cs:HealthBar|Bar inside the ceiling band'])
            else:
                self.complete_review(row)
        self.tick()

    def test_repairs_are_split_by_agent_and_each_card_carries_only_its_findings(self):
        self.mixed(); self.review_round()
        artist = self.only('artist')
        body = self.board.cards[artist['task_id']]['body']
        self.assertIn('art-reviewer:F2', body)
        self.assertNotIn('ui-reviewer:F1', body)
        self.board.complete(artist); self.tick()
        fixer = self.only('fixer')
        body = self.board.cards[fixer['task_id']]['body']
        self.assertIn('ui-reviewer:F1', body)
        self.assertNotIn('art-reviewer:F2', body)

    def test_a_passing_verifiers_leftover_domain_does_not_summon_an_agent(self):
        self.mixed(repair_domains=['art']); self.review_round(art=False)
        self.only('fixer')

    def test_repair_conflicting_with_a_plan_constraint_asks_a_human_instead_of_dispatching(self):
        self.mixed(task=dict(MIXED, preserve=['sprite.png'])); self.review_round()
        terminal = self.project()['terminal']
        self.assertEqual(terminal['phase'], 'blocked')
        self.assertIn('conflicts with an approved constraint', terminal['reason'])
        self.assertFalse([r for r in self.board.ready() if r['profile'] in ('artist', 'fixer')])

    def stalled_artist(self):
        """The real incident: the artist refuses a repair that contradicts the plan and the controller stops for a human."""
        self.mixed(); self.review_round()
        artist = self.only('artist')
        self.conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (artist['task_id'],)); self.conn.commit()
        self.tick(); self.board.complete(self.only('factory-retro')); self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        return self.conn.execute('SELECT COUNT(*) FROM factory_workflow_stages').fetchone()[0]

    DECISION = dict(waivers=[dict(ac='AC1', path='sprite.png', source='art-reviewer', reason='Runtime-tinted primitive, not a finished visual asset')],
                    constraints=[dict(preserve=['sprite.png'], reason='The primitive must stay byte-identical')])

    def test_resume_with_a_scoped_waiver_repairs_only_the_ui_finding_without_repeating_reviews(self):
        before = self.stalled_artist()
        self.controller.resume(self.conn, self.root, 'Waive AC1 for sprite.png: runtime-tinted primitive', self.DECISION)
        self.only('fixer')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM factory_workflow_stages').fetchone()[0], before + 1)  # no re-verify or re-review
        stored = self.project()['waivers'][0]
        self.assertEqual(stored['applied'][0]['finding'].split('|')[0], 'art-reviewer:F2')
        self.assertIn('5% match', stored['applied'][0]['finding'])  # the original result stays in the audit trail
        self.assertEqual(self.project()['constraints'][0]['preserve'], ['sprite.png'])
        self.assertTrue(any('waived by human decision' in w for h in self.project()['history'] for w in h.get('waived', [])))

    def test_after_the_waiver_the_milestone_is_accepted_only_once_the_ui_finding_is_repaired(self):
        self.stalled_artist()
        self.controller.resume(self.conn, self.root, 'Waive AC1 for sprite.png: runtime-tinted primitive', self.DECISION)
        self.board.complete(self.only('fixer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        self.assertNotIn('mixed', [c['id'] for c in self.project()['completed']])
        for row in self.board.ready():
            self.complete_review(row)
        self.tick()
        self.assertIn('mixed', [c['id'] for c in self.project()['completed']])
        self.assertTrue(self.project()['waivers'][0]['applied'])

    def test_an_invalid_decision_changes_nothing(self):
        self.stalled_artist()
        before = json.dumps(self.project(), sort_keys=True)
        bad = dict(waivers=[dict(ac='AC1', path='*', reason='Waive everything please')])
        with self.assertRaises(ConfigurationError):
            self.controller.resume(self.conn, self.root, 'Waive everything', bad)
        self.assertEqual(json.dumps(self.project(), sort_keys=True), before)

    def test_without_a_decision_resume_keeps_retrying_the_stalled_repair(self):
        self.stalled_artist()
        self.controller.resume(self.conn, self.root, 'Retry the artist')
        self.assertEqual([r['profile'] for r in self.board.ready()], ['artist'])

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
            self.board.complete(row,verdict='CHANGES_REQUIRED',findings=['F1|HIGH|AC1|sprite.png|Silhouette differs from director plan'],artifacts=[str(report),str(image),self.similarity(folder)])
        self.tick();self.only('artist')
        self.board.complete(self.only('artist'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        self.only('art-reviewer')

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
