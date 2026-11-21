from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest

from board_fixture import Board, enable_plan_review
from reference_fixture import record_tool_session
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.project_decisions import normalize_constraint
from factory_dashboard.project_policy import budget_used
from factory_dashboard.workflow_controller import WorkflowController
from factory_dashboard.workflow_state import WorkflowState
from factory_dashboard.workflow_templates import _preset

NEEDS = dict(art=False, audio=False, ui=False, ux=False)
CODE = dict(id='code', title='Build code', owner='developer', dependencies=[], acceptance={'AC1': 'Works'}, needs=NEEDS)
MIXED = dict(id='mixed', title='Mixed presentation', owner='developer', dependencies=[], acceptance={'AC1': 'Works'}, needs={**NEEDS, 'art': True, 'ui': True})
SPRITES = dict(id='sprites', title='Make sprites', owner='artist', dependencies=[], acceptance={'AC1': 'Sprite'}, needs={**NEEDS, 'art': True})


class ProjectControllerTests(unittest.TestCase):
    def setUp(self):
        enable_plan_review(self)
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
        self.home = Path(self.temp.name) / 'hermes-home'
        previous = os.environ.get('FACTORY_HERMES_HOME')
        os.environ['FACTORY_HERMES_HOME'] = str(self.home)
        self.addCleanup(lambda: os.environ.pop('FACTORY_HERMES_HOME') if previous is None else os.environ.__setitem__('FACTORY_HERMES_HOME', previous))

    def block(self, row, reason='Cannot continue', **extra):
        """Finish a writer BLOCKED the way a worker that really tried does: evidence that matches its own session log."""
        session = 'blocksession' + row['task_id'].replace('_', '')
        command, output = 'python3 build.py --all', 'build.py: error: the engine binary is missing'
        record_tool_session(self.home, row['profile'], session, command, output)
        self.board.complete(row, verdict='BLOCKED', blocked_reason=reason, blocked_evidence=[dict(command=command, output=output)], **extra)
        run = self.conn.execute('SELECT id,metadata FROM task_runs WHERE task_id=? ORDER BY id DESC', (row['task_id'],)).fetchone()
        metadata = json.loads(run[1]); metadata['worker_session_id'] = session
        self.conn.execute('UPDATE task_runs SET metadata=? WHERE id=?', (json.dumps(metadata), run[0])); self.conn.commit()

    def tick(self):
        return self.controller.reconcile(self.conn, self.root)

    def only(self, profile):
        rows = self.board.ready()
        self.assertEqual([r['profile'] for r in rows], [profile])
        return rows[0]

    def architect(self, tasks=None, **overrides):
        stage = self.only('architect')
        plan = Path(self.temp.name) / f'project-plan-{stage["cycle"]}-{stage["evidence_retry"]}' / 'project-plan.json'
        plan.parent.mkdir()
        plan.write_text(json.dumps(dict(tasks=tasks or [CODE], **getattr(self, 'plan_extra', {}))))
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

    def approval_phrase(self):
        document = json.loads(self.conn.execute('SELECT document FROM factory_project_execution WHERE root_id=?', (self.root,)).fetchone()[0])
        awaiting = document['awaiting']
        return f"APPROVE {self.root} {awaiting['sha256'][:12]} {(awaiting.get('references_digest') or 'none')[:12]}"

    def approve(self, note='Approved: matches the intended look'):
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        self.controller.resume(self.conn, self.root, self.approval_phrase() + ' ' + note)

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

    def test_only_the_final_integration_card_demands_every_planned_manifest_path(self):
        self.plan()
        task_card = self.board.cards[self.only('developer')['task_id']]['body']
        self.assertIn('fw.py manifest PROJECT_DIR`: an include path that a later task will create', task_card)
        self.assertNotIn('--final', task_card)
        for _ in range(2):
            self.board.complete(self.only('developer')); self.tick()
            self.board.complete(self.only('verifier')); self.tick()
            for row in self.board.ready():
                if row['profile'] != 'developer': self.board.complete(row)
            self.tick()
            ready = [r for r in self.board.ready() if r['profile'] == 'developer']
            if ready and 'integration' in ready[0]['stage_key']:
                self.assertIn('fw.py manifest PROJECT_DIR --final', self.board.cards[ready[0]['task_id']]['body'])
                return
        self.fail('the final integration card was never created')

    def test_director_plans_reach_architect_and_dependent_code_does_not_wait_for_a_visual_review(self):
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
        ready=[r['profile'] for r in self.board.ready()]
        self.assertNotIn('art-reviewer',ready)                # no visual review of an individual asset task...
        self.board.complete(next(r for r in self.board.ready() if r['profile']=='claude-reviewer'))
        for row in self.board.ready():
            self.board.complete(row)
        self.tick()
        self.assertIn('developer',[r['profile'] for r in self.board.ready()])   # ...so the dependent code task starts as soon as the asset task's technical checks pass

    def test_stale_verifier_manifest_never_launches_review(self):
        self.plan();self.board.complete(self.only('developer'));self.tick()
        for _ in range(3):  # the original handoff and its two bounded retries all carry the stale manifest
            self.board.complete(self.only('verifier'),manifest_sha12='111111111111')
            self.tick()
        self.only('factory-retro')
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE kind='review'").fetchone())

    def fail_first_task(self):
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),verdict='FAIL',ac_results={'AC1':'fail'});self.tick()

    def test_the_repair_limit_stops_for_a_human_and_never_goes_back_to_the_architect(self):
        self.definition['max_repairs']=0
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?',(json.dumps(self.definition),))
        self.plan()
        self.fail_first_task()
        terminal=self.project()['terminal']
        self.assertEqual(terminal['phase'],'human_review')
        self.assertIn('Repair limit reached for task code',terminal['reason'])
        self.assertIn('AC1: fail',terminal['reason'])
        self.assertIn('extra_repairs',terminal['reason']); self.assertIn('model_overrides',terminal['reason'])
        self.assertFalse([r for r in self.board.ready() if r['profile']=='architect'])
        self.board.complete(self.only('factory-retro'))
        self.assertEqual(self.tick()['phase'],'human_review')
        self.assertEqual(self.board.get_task(self.conn,self.root).status,'blocked')
        self.assertEqual(self.project().get('replans',0),0)

    def test_a_declared_plan_defect_changes_nothing_a_failed_verification_is_repaired_like_any_other(self):
        self.plan()
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'),verdict='FAIL',ac_results={'AC1':'fail'},plan_defect='AC1 contradicts the request')
        self.tick()
        self.assertFalse([r for r in self.board.ready() if r['profile']=='architect'])
        self.assertTrue(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE kind='repair'").fetchone())

    def test_replan_cannot_change_a_task_that_already_passed(self):
        from factory_dashboard.project_controller import ProjectController
        second=dict(CODE,id='more',dependencies=['code'])
        self.plan(tasks=[CODE,second])
        self.board.complete(self.only('developer'));self.tick()
        self.board.complete(self.only('verifier'));self.tick()
        for row in self.board.ready():self.board.complete(row)
        self.tick()
        # No worker or reviewer verdict sends a project back to the architect any more; the invariant is kept for the replans that remain.
        self.board.complete(self.only('developer'))  # the second task's card is already out; the replan supersedes it
        controller=ProjectController(self.controller)
        root=self.state.read_root(self.conn,self.root); project=self.project()
        self.assertTrue(controller._replan(self.conn,root,project,project['tasks'][1],'Task is too large',['F1|HIGH|AC1|more|too large'],[]))
        controller._save(self.conn,root,project); self.conn.commit(); self.tick()
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

    BAD_PLAN = [{**CODE, 'owner': 'nobody'}]

    def start_planning(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=NEEDS); self.tick()

    def test_an_invalid_architect_plan_is_corrected_with_the_exact_errors_without_spending_a_replan(self):
        self.start_planning()
        self.architect(tasks=self.BAD_PLAN)
        stage = self.only('architect')
        self.assertEqual((stage['cycle'], stage['evidence_retry']), (0, 1))  # the same generation: no replan
        body = self.board.cards[stage['task_id']]['body']
        rejection = json.JSONDecoder().raw_decode(body.rsplit('\nPROJECT_CONTEXT ', 1)[1])[0]['previous_handoff_rejected']
        self.assertIn('Invalid task owner', rejection['reason'])
        self.assertIn('numbered acceptance criteria', rejection['required_schema'])
        self.assertEqual((rejection['attempt'], rejection['max_attempts']), (1, 2))
        self.assertEqual(self.project().get('replans', 0), 0)
        self.architect()
        self.only('claude-reviewer')

    def test_every_structural_error_of_a_plan_is_reported_at_once(self):
        self.start_planning()
        self.architect(tasks=[{**CODE, 'owner': 'nobody'}, {**CODE, 'id': 'second', 'title': '', 'acceptance': {}}])
        body = self.board.cards[self.only('architect')['task_id']]['body']
        reason = json.JSONDecoder().raw_decode(body.rsplit('\nPROJECT_CONTEXT ', 1)[1])[0]['previous_handoff_rejected']['reason']
        self.assertIn('code: Invalid task owner', reason)
        self.assertIn('second: ', reason)

    def test_structural_correction_is_bounded_then_stops_for_a_human_and_never_replans(self):
        self.start_planning()
        for _ in range(3):  # the original plan and its two corrections are all invalid
            self.architect(tasks=self.BAD_PLAN)
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('still failed validation after 2 corrections', self.project()['terminal']['reason'])
        self.assertEqual(self.project().get('replans', 0), 0)
        self.assertEqual([e['kind'] for e in self.project()['orchestration_log']], ['plan_validation_retry', 'plan_validation_retry'])

    def test_structural_corrections_leave_the_whole_architectural_replan_budget_intact(self):
        self.start_planning()
        for _ in range(2):
            self.architect(tasks=self.BAD_PLAN)
        for _ in range(3):  # then valid plans that the plan review rejects: both architectural replans are still available
            self.architect()
            self.board.complete(self.only('claude-reviewer'), findings=['F1|BLOCKER|-|code|Request requirement is missing']); self.tick()
        self.assertEqual(self.project()['replans'], 2)
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')

    def exhausted_plan_review(self):
        self.start_planning()
        for _ in range(3):
            self.architect()
            self.board.complete(self.only('claude-reviewer'), findings=['F1|BLOCKER|-|code|Request requirement is missing']); self.tick()
        self.board.complete(self.only('factory-retro')); self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'human_review')

    def test_a_human_granted_extra_replan_is_recorded_used_once_and_audited(self):
        self.exhausted_plan_review()
        self.controller.resume(self.conn, self.root, 'One more architect pass against the reviewer findings', dict(extra_replans=1), True)
        stage = self.only('architect')
        self.assertEqual(stage['cycle'], 3)
        grants = self.project()['replan_grants']
        self.assertEqual((grants['granted'], grants['consumed']), (1, 1))
        self.assertEqual([e['kind'] for e in grants['log']], ['granted', 'consumed'])
        self.assertIn('One more architect pass', grants['log'][0]['reason'])
        self.architect()
        self.board.complete(self.only('claude-reviewer'), findings=['F1|BLOCKER|-|code|Still missing']); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')  # the single grant is spent: a human decides again
        self.assertEqual(self.project()['replans'], 3)

    def test_without_a_grant_the_replan_limit_still_stops_and_a_grant_is_one_per_decision(self):
        self.exhausted_plan_review()
        self.assertEqual(self.project().get('replan_grants'), None)
        with self.assertRaises(ConfigurationError):
            self.controller.resume(self.conn, self.root, 'Two extra replans', dict(extra_replans=2), True)
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'human_review')

    def test_reevaluate_never_retries_a_planning_stage(self):
        self.start_planning()
        for _ in range(3):
            self.architect(tasks=self.BAD_PLAN)
        self.board.complete(self.only('factory-retro')); self.tick()
        architects = lambda: self.conn.execute("SELECT COUNT(*) FROM factory_workflow_stages WHERE profile='architect'").fetchone()[0]
        before = architects()
        self.controller.resume(self.conn, self.root, 'Re-judge the existing architect evidence', None, True)
        self.assertEqual(architects(), before)

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

    def test_only_the_exact_bound_phrase_approves_and_a_recovery_note_never_does(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'),project_scope={**NEEDS,'art':True});self.tick()
        self.board.complete(self.only('art-director'));self.tick()
        phrase=self.approval_phrase()
        self.assertIn(phrase,self.state.read_root(self.conn,self.root)['reason'])
        for note in ('Approved','Retry: infrastructure recovered','approve','APPROVE '+self.root,phrase.replace(phrase.split()[2],'0'*12),
                     phrase.replace(self.root,'t_other')):
            with self.assertRaisesRegex(Exception,'awaits a human decision'):
                self.controller.resume(self.conn,self.root,note)
        self.assertEqual(self.board.ready(),[])
        self.assertFalse(json.loads(self.conn.execute('SELECT document FROM factory_project_execution').fetchone()[0]).get('approvals'))
        self.controller.resume(self.conn,self.root,phrase+' looks right')
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

    def complete_review(self,row,mode='rendered_in_engine'):
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
        for row in self.board.ready():
            self.board.complete(row)
        self.tick()
        self.board.complete(self.only('developer'));self.tick()        # final integration: the only place the art reviewer runs
        self.board.complete(self.only('verifier'));self.tick()
        art=next(r for r in self.board.ready() if r['profile']=='art-reviewer')
        self.board.complete(art);self.tick()                           # no comparison evidence at all
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

    BAD_INCIDENT = dict(tool_incidents=[dict(command='x')])

    def malformed_until_stopped(self):
        self.plan();self.board.complete(self.only('developer'));self.tick()
        for _ in range(3):
            self.board.complete(self.only('verifier'),**self.BAD_INCIDENT);self.tick()
        return self.project()

    def test_malformed_incident_evidence_is_retried_twice_then_stops_for_human_review(self):
        project=self.malformed_until_stopped()
        self.assertEqual(project['terminal']['phase'],'human_review')
        self.assertIn('tool incident',project['terminal']['reason'])
        self.assertFalse([r for r in self.board.ready() if r['kind']=='review'])
        self.assertEqual(project['handoff_retries'],{'task-code-verify:0':2})

    def test_a_malformed_handoff_retries_only_that_stage_with_exact_errors_and_valid_parts(self):
        self.plan();self.board.complete(self.only('developer'));self.tick()
        stages=lambda:self.conn.execute('SELECT COUNT(*) FROM factory_workflow_stages').fetchone()[0]
        before=stages()
        self.board.complete(self.only('verifier'),**self.BAD_INCIDENT);self.tick()
        retry=self.only('verifier')
        self.assertEqual(stages(),before+1)  # one card; the writer and the milestone are not restarted
        self.assertEqual(retry['evidence_retry'],1)
        body=self.board.cards[retry['task_id']]['body']
        rejection=json.JSONDecoder().raw_decode(body.split('PROJECT_CONTEXT ',1)[1])[0]['previous_handoff_rejected']
        self.assertIn('tool incident',rejection['reason'].lower())
        self.assertEqual(rejection['required_identity']['workflow_contract'],'factory-workflow/v1')
        self.assertEqual(rejection['required_identity']['stage_key'],retry['stage_key'])
        self.assertEqual(rejection['previous_valid_metadata']['manifest_sha12'],'abcdef123456')  # the valid part of the original result
        self.assertEqual((rejection['attempt'],rejection['max_attempts']),(1,2))
        self.board.complete(retry);self.tick()  # a corrected handoff continues the same milestone
        self.assertEqual([r['profile'] for r in self.board.ready()],['claude-reviewer','security-reviewer'])

    def test_an_ownership_failure_is_not_retried_as_a_formatting_slip(self):
        self.plan();self.board.complete(self.only('developer'));self.tick()
        verifier=self.only('verifier')
        self.board.complete(verifier)
        self.conn.execute('UPDATE factory_workflow_stages SET active_run_id=999 WHERE task_id=?',(verifier['task_id'],));self.conn.commit()
        self.tick()
        self.assertEqual(self.project()['terminal']['phase'],'human_review')
        self.assertNotIn('task-code-verify:0',self.project().get('handoff_retries',{}))

    # --- human decisions: scoped waivers, constraint conflicts and per-agent repair (the milestone-1 incident) ---
    def mixed(self, task=MIXED, **verify):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=dict(art=True, audio=False, ui=True, ux=False)); self.tick()
        self.board.complete(self.only('art-director')); self.tick()
        self.approve()
        self.architect([task])
        self.board.complete(self.only('claude-reviewer')); self.tick()
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        # The task passes its own review panel (there is no art reviewer in it: the single art review is the final one), then final integration is reached.
        assert 'art-reviewer' not in [r['profile'] for r in self.board.ready()]
        for row in self.board.ready():
            self.complete_review(row)
        self.tick()
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), **verify); self.tick()

    def review_round(self, art=True, ui=True, ui_extra=None):
        """The panel of the FINAL INTEGRATION: the only place the art reviewer runs."""
        folder = Path(self.temp.name) / f'gate-{len(list(Path(self.temp.name).iterdir()))}'
        folder.mkdir()
        for row in self.board.ready():
            if row['profile'] == 'art-reviewer' and art:
                director = next(p for p in self.project()['plans'] if p['profile'] == 'art-director')
                image = folder / 'render.png'; image.write_bytes(b'render')
                report = folder / 'comparison.json'
                report.write_text(json.dumps(dict(schema='factory-comparison/v1', plan_sha256=director['sha256'], manifest_sha12='abcdef123456', mode='rendered_in_engine', source='tool', outcome='fail',
                                                  criteria=[dict(rule='S1', expected='Round', observed='Square', outcome='fail')], evidence=[str(image)])))
                self.board.complete(row, verdict='CHANGES_REQUIRED', artifacts=[str(report), str(image)],
                                    findings=['F2|HIGH|AC1|sprite.png|[visual] the sprite is square where the reference is round'])
            elif row['profile'] == 'ui-reviewer' and ui:
                self.board.complete(row, verdict='CHANGES_REQUIRED', findings=['F1|MEDIUM|AC1|Assets/Scripts/Builder.cs:HealthBar|Bar inside the ceiling band'], **(ui_extra or {}))
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
        self.assertIn('Specification conflict', terminal['reason'])
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
        self.assertIn('square where the reference is round', stored['applied'][0]['finding'])  # the original result stays in the audit trail
        self.assertEqual(self.project()['constraints'][0]['preserve'], ['sprite.png'])
        self.assertTrue(any('waived by human decision' in w for h in self.project()['history'] for w in h.get('waived', [])))

    def test_after_the_waiver_the_milestone_is_accepted_only_once_the_ui_finding_is_repaired(self):
        self.stalled_artist()
        self.controller.resume(self.conn, self.root, 'Waive AC1 for sprite.png: runtime-tinted primitive', self.DECISION)
        self.board.complete(self.only('fixer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        self.assertNotEqual(self.project().get('terminal', {}).get('phase'), 'delivered')
        for row in self.board.ready():
            self.complete_review(row)
        self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'delivered')
        self.assertTrue(self.project()['waivers'][0]['applied'])

    def test_a_decision_after_one_recorded_before_constraint_ids_existed_keeps_the_old_constraint(self):
        self.stalled_artist()
        project = self.project()
        project['constraints'] = [dict(preserve=['older.png'], reason='recorded by an earlier decision', source='human')]
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(project),)); self.conn.commit()
        self.controller.resume(self.conn, self.root, 'Add a palette rule', dict(self.DECISION, constraints=[
            dict(kind='palette', colors=['#1C1C1F'], reason='Only the approved palette may be used')]))
        kinds = sorted((c['kind'], bool(c['id'])) for c in self.project()['constraints'])
        self.assertEqual(kinds, [('immutable', True), ('palette', True)])
        self.assertEqual(self.project()['constraints'][0]['preserve'], ['older.png'])

    def test_a_decision_with_reevaluate_rejudges_the_existing_review_evidence_without_new_cards(self):
        cid = self.with_palette()
        self.mixed(); self.review_round(art=False, ui_extra=self.spec_conflict(cid))
        self.board.complete(self.only('factory-retro')); self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        count = lambda: self.conn.execute("SELECT COUNT(*) FROM factory_workflow_stages WHERE kind IN ('verify','review')").fetchone()[0]
        before = count()
        waive = dict(waivers=[dict(ac='AC1', path='Assets/Scripts/Builder.cs', source='ui-reviewer',
                                   reason='The plan fixes the palette; this contrast concern is waived for the builder')])
        self.controller.resume(self.conn, self.root, 'Waive the contrast concern', waive, True)
        self.assertEqual(count(), before)  # nothing was verified or reviewed again
        self.assertIn('mixed', [t['id'] for t in self.project()['completed']])
        self.assertEqual(self.project()['terminal']['phase'], 'delivered')  # re-judged at final integration: delivered

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

    def failed_then_repaired(self, repair_ids):
        two = dict(CODE, acceptance={'AC1': 'Works', 'AC2': 'Also works'})
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=dict(art=False, audio=False, ui=False, ux=False)); self.tick()
        later = dict(CODE, id='later', title='Later work', dependencies=['code'], acceptance={'AC3': 'Third'})
        self.architect([two, later], ac_ids=['AC1', 'AC2', 'AC3'])
        self.board.complete(self.only('claude-reviewer')); self.tick()
        self.board.complete(self.only('developer'), ac_ids=['AC1', 'AC2']); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail', 'AC2': 'pass'}); self.tick()
        self.board.complete(self.only('fixer'), ac_ids=repair_ids); self.tick()

    def test_repair_writer_naming_other_known_project_acs_is_accepted_and_judged_on_the_task_criteria(self):
        self.failed_then_repaired(['AC1', 'AC2', 'AC3'])
        self.assertNotIn('terminal', self.project())
        self.board.complete(self.only('verifier'), ac_ids=['AC1', 'AC2'], ac_results={'AC1': 'pass', 'AC2': 'pass'}); self.tick()
        self.assertEqual([r['profile'] for r in self.board.ready()], ['claude-reviewer', 'security-reviewer'])

    def two_task_plan(self):
        two = dict(CODE, acceptance={'AC1': 'Works', 'AC2': 'Also works'})
        later = dict(CODE, id='later', title='Later work', dependencies=['code'], acceptance={'AC3': 'Third'})
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=dict(art=False, audio=False, ui=False, ux=False)); self.tick()
        self.architect([two, later], ac_ids=['AC1', 'AC2', 'AC3'])
        self.board.complete(self.only('claude-reviewer')); self.tick()
        self.board.complete(self.only('developer'), ac_ids=['AC1', 'AC2']); self.tick()

    def test_a_verifier_listing_other_tasks_criteria_is_judged_only_on_this_tasks_criteria(self):
        self.two_task_plan()
        self.board.complete(self.only('verifier'), ac_ids=['AC1', 'AC2', 'AC3'],
                            ac_results={'AC1': 'pass', 'AC2': 'pass', 'AC3': 'unverified:environment'}); self.tick()
        self.assertNotIn('terminal', self.project())
        self.assertEqual([r['profile'] for r in self.board.ready()], ['claude-reviewer', 'security-reviewer'])

    def test_this_tasks_own_unverified_environment_criterion_still_blocks_and_a_missing_one_still_fails(self):
        self.two_task_plan()
        self.board.complete(self.only('verifier'), ac_results={'AC1': 'pass', 'AC2': 'unverified:environment', 'AC3': 'pass'}); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')

    def test_a_verifier_that_omits_one_of_this_tasks_criteria_is_not_accepted(self):
        self.two_task_plan()
        self.board.complete(self.only('verifier'), ac_results={'AC1': 'pass', 'AC3': 'pass'}); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('coverage', self.project()['terminal']['reason'])

    def test_repair_writer_naming_an_unknown_ac_or_none_of_the_tasks_is_still_rejected(self):
        self.failed_then_repaired(['AC1', 'AC9'])
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('Writer acceptance differs', self.project()['terminal']['reason'])

    def test_reevaluate_rejudges_existing_evidence_without_repeating_any_stage(self):
        self.malformed_until_stopped()
        verifier = self.conn.execute("SELECT task_id FROM factory_workflow_stages WHERE kind='verify' ORDER BY evidence_retry DESC").fetchone()[0]
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.board.complete(self.only('factory-retro')); self.tick()
        with self.assertRaises(ConfigurationError):
            self.controller.resume(self.conn, self.root, 'Plain resume must still refuse a human_review stop')
        # The evidence is corrected (or the controller rule is fixed); re-judge it instead of running the verifier again.
        run = self.conn.execute('SELECT id,metadata FROM task_runs WHERE task_id=?', (verifier,)).fetchone()
        data = json.loads(run[1]); data.pop('tool_incidents'); self.conn.execute('UPDATE task_runs SET metadata=? WHERE id=?', (json.dumps(data), run[0])); self.conn.commit()
        stages = self.conn.execute('SELECT COUNT(*) FROM factory_workflow_stages').fetchone()[0]
        self.controller.resume(self.conn, self.root, 'Re-judge the verifier evidence', None, True)
        self.assertEqual([r['profile'] for r in self.board.ready()], ['claude-reviewer', 'security-reviewer'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM factory_workflow_stages').fetchone()[0], stages + 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM factory_workflow_stages WHERE kind='verify'").fetchone()[0], 3)  # no new verifier

    # --- structured constraints, specification conflicts and extra repairs ---
    PALETTE = dict(kind='palette', reason='Only the approved palette may be used by the HUD', colors=['#1C1C1F', '#4A3A1E', '#F2A020'])

    def with_palette(self):
        self.plan_extra = dict(constraints=[self.PALETTE])
        return normalize_constraint(self.PALETTE)['id']

    def test_plan_constraints_are_captured_and_shown_to_every_task_stage(self):
        cid = self.with_palette()
        self.mixed()
        self.assertEqual([c['id'] for c in self.project()['plan_constraints']], [cid])
        verifier = self.conn.execute("SELECT task_id FROM factory_workflow_stages WHERE kind='verify'").fetchone()[0]
        for stage_id in (verifier,):
            self.assertIn(cid, self.board.cards[stage_id]['body'])
        self.assertIn(cid, self.board.cards[next(r['task_id'] for r in self.board.ready() if r['profile'] == 'ui-reviewer')]['body'])

    def spec_conflict(self, cid, **extra):
        return dict(spec_conflicts=[dict(constraint=cid, reason='Every fix for this finding needs a colour outside the palette', finding='ui-reviewer:F1')], **extra)

    def test_a_reviewer_reported_specification_conflict_stops_for_a_human_without_spending_repair_budget(self):
        cid = self.with_palette()
        self.mixed(); self.review_round(art=False, ui_extra=self.spec_conflict(cid))
        terminal = self.project()['terminal']
        self.assertEqual(terminal['phase'], 'blocked')
        self.assertIn('Specification conflict', terminal['reason'])
        self.assertIn(cid, terminal['reason'])
        self.assertFalse([r for r in self.board.ready() if r['profile'] in ('fixer', 'artist')])
        self.assertEqual(self.project()['work']['cycle'], 0)  # no repair cycle was consumed
        self.assertTrue(any(h.get('verdict') == 'SPEC_CONFLICT' for h in self.project()['history']))

    def test_a_conflict_naming_an_unknown_constraint_is_rejected_not_trusted(self):
        self.with_palette()
        self.mixed(); self.review_round(art=False, ui_extra=self.spec_conflict('c_00000000'))
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('unknown constraint', self.project()['terminal']['reason'])

    def conflict_check(self):
        return next(r for r in self.board.ready() if r['stage_key'].endswith('conflict-check'))

    def test_a_relevant_constraint_triggers_a_targeted_assessment_before_the_repair_is_authorized(self):
        cid = self.with_palette()
        self.mixed(); self.review_round(art=False)
        check = self.conflict_check()
        self.assertEqual(check['profile'], 'claude-reviewer')
        body = self.board.cards[check['task_id']]['body']
        self.assertIn('ui-reviewer:F1', body)
        self.assertIn(cid, body)
        self.assertFalse([r for r in self.board.ready() if r['profile'] == 'fixer'])
        self.board.complete(check); self.tick()  # no genuine contradiction: the repair proceeds
        self.only('fixer')

    def test_an_assessed_contradiction_is_a_specification_conflict_not_a_repair(self):
        cid = self.with_palette()
        self.mixed(); self.review_round(art=False)
        self.board.complete(self.conflict_check(), **self.spec_conflict(cid)); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')
        self.assertIn('conflict-check', self.project()['terminal']['reason'])
        self.assertFalse([r for r in self.board.ready() if r['profile'] == 'fixer'])
        self.assertEqual(self.project()['work']['cycle'], 0)

    def test_without_constraints_there_is_no_assessment_overhead(self):
        self.mixed(); self.review_round(art=False)
        self.only('fixer')

    def test_extra_repairs_are_granted_to_the_task_in_progress_and_extend_its_budget(self):
        self.definition['max_repairs'] = 0
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?', (json.dumps(self.definition),))
        self.plan()
        project = self.project(); project['work'] = project.get('work') or {}
        self.board.complete(self.only('developer')); self.tick()
        project = self.project(); project['work']['extra_repairs'] = 1
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(project),)); self.conn.commit()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}); self.tick()
        self.only('fixer')  # without the grant a zero budget would have gone back to the architect

    def test_a_decision_can_grant_extra_repairs_only_while_a_task_is_in_progress_and_within_the_cap(self):
        self.stalled_artist()
        self.controller.resume(self.conn, self.root, 'One more repair for this decision', dict(self.DECISION, extra_repairs=1))
        self.assertEqual(self.project()['work']['extra_repairs'], 1)
        with self.assertRaises(ConfigurationError):
            normalize_constraint(dict(kind='palette', reason='long enough reason', colors=['red']))

    # --- separate repair budgets: product defects versus orchestration recoveries ---
    def limit_repairs(self, n):
        self.definition['max_repairs'] = n
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?', (json.dumps(self.definition),))

    def used(self):
        return budget_used(self.project()['work'])

    HARNESS = dict(verdict='FAIL', ac_results={'AC1': 'unverified:harness'})

    def test_a_harness_only_failure_is_an_orchestration_recovery_and_leaves_the_product_budget_untouched(self):
        self.limit_repairs(0)  # a product repair would be out of budget immediately
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), **self.HARNESS); self.tick()
        self.board.complete(self.only('fixer')); self.tick()
        self.assertEqual(self.used(), (0, 1))
        charge = self.project()['work']['charges'][0]
        self.assertEqual(charge['kind'], 'orchestration')
        self.assertIn('unverified:harness', charge['reason'])
        self.only('verifier')

    def test_orchestration_recoveries_are_bounded_then_a_human_decides(self):
        self.limit_repairs(0)
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        for _ in range(2):
            self.board.complete(self.only('verifier'), **self.HARNESS); self.tick()
            self.board.complete(self.only('fixer')); self.tick()
        self.board.complete(self.only('verifier'), **self.HARNESS); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('Orchestration recovery limit', self.project()['terminal']['reason'])
        self.assertEqual(self.used(), (0, 2))
        self.assertFalse([r for r in self.board.ready() if r['profile'] in ('fixer', 'architect')])

    def test_a_product_defect_consumes_the_product_budget_and_is_recorded(self):
        self.limit_repairs(1)
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}); self.tick()
        self.assertEqual(self.used(), (1, 0))
        self.assertEqual(self.project()['work']['charges'][0]['kind'], 'product')
        self.board.complete(self.only('fixer')); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')  # the product budget really was spent: a human decides
        self.assertIn('Repair limit reached for task code after 1 product repair', self.project()['terminal']['reason'])
        self.assertFalse([r for r in self.board.ready() if r['profile'] == 'architect'])

    def test_a_failed_check_alongside_a_harness_gap_is_still_a_product_defect(self):
        self.limit_repairs(2)
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'unverified:harness'},
                            failed_checks=[dict(cmd='unity PlayMode', preexisting=False)]); self.tick()
        self.assertEqual(self.used(), (1, 0))

    def test_handoff_retries_and_human_resumes_are_logged_and_never_charge_a_repair(self):
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), **self.BAD_INCIDENT); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        self.assertEqual(self.used(), (0, 0))
        kinds = [e['kind'] for e in self.project()['orchestration_log']]
        self.assertEqual(kinds, ['handoff_retry'])

    def test_repairs_that_never_ran_are_not_charged_when_a_decision_rewinds_them(self):
        self.stalled_artist()
        self.assertEqual(len(self.project()['work']['charges']), 1)
        self.controller.resume(self.conn, self.root, 'Waive and re-judge the existing evidence', self.DECISION)
        self.assertEqual([c['kind'] for c in self.project()['work']['charges']], ['product'])  # only the code repair that is now dispatched

    def test_a_task_recorded_before_charges_existed_counts_each_earlier_cycle_as_a_product_repair(self):
        self.assertEqual(budget_used(dict(cycle=3)), (3, 0))
        self.assertEqual(budget_used(dict(cycle=3, charges=[dict(kind='product'), dict(kind='orchestration'), dict(kind='product')])), (2, 1))

    def test_exhaustion_after_a_granted_repair_stops_for_a_human_without_replan_or_another_repair(self):
        self.limit_repairs(0)
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        project = self.project(); project['work'].update(extra_repairs=1, on_exhaustion='human_review')
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(project),)); self.conn.commit()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}); self.tick()
        self.board.complete(self.only('fixer')); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('Repair limit reached for task code', self.project()['terminal']['reason'])
        self.assertFalse([r for r in self.board.ready() if r['profile'] in ('architect', 'fixer')])

    def test_exhaustion_without_a_decision_stops_for_a_human_and_never_replans(self):
        self.limit_repairs(0)
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertFalse([r for r in self.board.ready() if r['profile'] == 'architect'])

    def test_a_decision_records_the_exhaustion_choice_on_the_task_in_progress(self):
        self.stalled_artist()
        self.controller.resume(self.conn, self.root, 'One more repair, then a human', dict(self.DECISION, extra_repairs=1, on_exhaustion='human_review'))
        self.assertEqual((self.project()['work']['extra_repairs'], self.project()['work']['on_exhaustion']), (1, 'human_review'))

    def test_a_blocked_writer_that_declares_a_plan_defect_stops_for_a_human_and_is_not_replanned(self):
        self.plan()
        self.block(self.only('developer'), 'Task acceptance conflict',
                   plan_defect='The acceptance criteria contradict each other; the architect must clarify them')
        self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')
        self.assertIn('Task acceptance conflict', self.project()['terminal']['reason'])
        self.assertFalse([r for r in self.board.ready() if r['profile'] == 'architect'])

    def test_a_blocked_writer_without_a_plan_defect_still_stops_for_a_human(self):
        self.plan()
        self.block(self.only('developer'), 'The Unity editor is not installed')
        self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')
        self.assertIn('Stage blocked', self.project()['terminal']['reason'])

    def test_reevaluating_a_blocked_writer_stop_keeps_it_blocked_and_does_not_rerun_the_writer(self):
        self.plan()
        self.block(self.only('developer'), 'Task acceptance conflict', plan_defect='Contradictory criteria need clarification')
        developers = lambda: self.conn.execute("SELECT COUNT(*) FROM factory_workflow_stages WHERE profile='developer'").fetchone()[0]
        self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')
        before = developers()
        self.tick(); self.board.complete(self.only('factory-retro')); self.tick()
        self.controller.resume(self.conn, self.root, 'Re-judge under the current rules', None, True)
        self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')
        self.assertFalse([r for r in self.board.ready() if r['profile'] == 'architect'])
        self.assertEqual(developers(), before)

    # --- a repair-limit stop is resumed by a human, optionally with a stronger model ---
    def stopped_at_the_repair_limit(self):
        self.definition['max_repairs'] = 0
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?', (json.dumps(self.definition),))
        self.plan(); self.fail_first_task()
        self.board.complete(self.only('factory-retro'))
        self.assertEqual(self.tick()['phase'], 'human_review')

    def test_a_repair_limit_stop_resumes_with_extra_repairs_and_a_recorded_model_override(self):
        self.stopped_at_the_repair_limit()
        override = dict(fixer=dict(provider='openai-codex', model='gpt-5', effort='high'))
        self.controller.resume(self.conn, self.root, 'A stronger model for the fixer, one more repair', dict(extra_repairs=1, model_overrides=override))
        project = self.project()
        self.assertNotIn('terminal', project)
        self.assertEqual(project['work']['extra_repairs'], 1)
        self.assertEqual(project['model_overrides']['fixer']['model'], 'gpt-5')
        entry = next(e for e in project['orchestration_log'] if e['kind'] == 'human_model_override')
        self.assertEqual(entry['models'], {'fixer': 'openai-codex/gpt-5'})
        self.tick(); self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}); self.tick()
        self.only('fixer')  # the granted repair runs; the project did not go to the architect
        self.assertEqual(self.project().get('replans', 0), 0)

    def test_a_repair_limit_stop_without_a_decision_cannot_be_resumed(self):
        self.stopped_at_the_repair_limit()
        with self.assertRaisesRegex(ConfigurationError, 'Only an infrastructure-blocked project can resume'):
            self.controller.resume(self.conn, self.root, 'Just try again', None)

    def test_a_malformed_model_override_changes_nothing(self):
        self.stopped_at_the_repair_limit()
        with self.assertRaises(ConfigurationError):
            self.controller.resume(self.conn, self.root, 'Bad', dict(extra_repairs=1, model_overrides=dict(fixer=dict(provider='x'))))
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertNotIn('model_overrides', self.project())

    def test_a_repair_card_the_worker_blocked_is_redispatched_as_a_new_attempt_after_a_decision(self):
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        findings = ['F1|HIGH|AC1|code.py|Real defect to repair', 'F2|MEDIUM|AC1|notes.md|Wording a human must confirm']
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}, findings=findings, repair_domains=['code']); self.tick()
        stalled = self.only('fixer')
        self.conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (stalled['task_id'],)); self.conn.commit()  # the worker called kanban_block
        self.tick(); self.board.complete(self.only('factory-retro')); self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        waiver = dict(waivers=[dict(ac='AC1', path='notes.md', source='verifier', reason='Human confirmed this wording is authoritative')])
        self.controller.resume(self.conn, self.root, 'Waive F2 only; F1 still needs repair', waiver)
        self.tick()
        fresh = self.only('fixer')  # the same profile again: a new attempt, not the blocked card and not another stop
        self.assertNotEqual(fresh['task_id'], stalled['task_id'])
        self.assertEqual((fresh['stage_key'], fresh['evidence_retry']), (stalled['stage_key'], stalled['evidence_retry'] + 1))
        self.assertNotIn('terminal', self.project())
        card = self.board.cards[fresh['task_id']]['body']
        self.assertIn('F1|HIGH|AC1|code.py', card); self.assertNotIn('F2|MEDIUM', card)

    def test_a_retried_writer_starts_from_the_manifest_its_failed_predecessor_left_on_disk(self):
        self.plan()
        first = self.only('developer')
        self.assertIn('BASELINE none', self.board.cards[first['task_id']]['body'])
        self.block(first, 'Could not finish', manifest_sha12='fedcba654321')  # it edited files and rebuilt the manifest
        self.tick(); self.board.complete(self.only('factory-retro')); self.tick()
        self.controller.resume(self.conn, self.root, 'Retry the writer', dict(retry_stage=True))
        self.tick()
        card = self.board.cards[self.only('developer')['task_id']]['body']
        self.assertIn('MANIFEST fedcba654321', card); self.assertIn('BASELINE fedcba654321', card)
        self.assertIn('continues from the files the superseded attempt left on disk', card)

    def test_a_retried_writer_whose_predecessor_reported_no_new_manifest_keeps_the_card_baseline(self):
        self.plan()
        first = self.only('developer')
        self.block(first, 'Could not finish', manifest_sha12='none')
        self.tick(); self.board.complete(self.only('factory-retro')); self.tick()
        self.controller.resume(self.conn, self.root, 'Retry the writer', dict(retry_stage=True)); self.tick()
        card = self.board.cards[self.only('developer')['task_id']]['body']
        self.assertIn('BASELINE none', card); self.assertNotIn('continues from the files', card)

    def test_a_writer_card_lists_the_approved_plan_files_as_exact_paths(self):
        self.plan()
        card = self.board.cards[self.only('developer')['task_id']]['body']
        paths = [p['path'] for p in self.project()['plans'] if p.get('path')]
        self.assertTrue(paths)
        self.assertIn('read exactly these absolute paths (copy them, never retype them): ' + '; '.join(paths), card)

    def test_a_stage_retry_reruns_only_the_reviewer_that_stopped_and_keeps_accepted_verification_and_reviews(self):
        self.plan(tasks=[dict(CODE, risk='high')])
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        rows = {r['profile']: r for r in self.board.ready()}
        self.assertEqual(set(rows), {'claude-reviewer', 'security-reviewer'})
        self.board.complete(rows['security-reviewer'])
        self.conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (rows['claude-reviewer']['task_id'],)); self.conn.commit()  # the worker blocked itself
        self.tick(); self.board.complete(self.only('factory-retro')); self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        count = lambda: self.conn.execute('SELECT COUNT(*) FROM factory_workflow_stages').fetchone()[0]
        before = count()
        self.controller.resume(self.conn, self.root, 'The reviewer tool is back', dict(retry_stage=True))
        self.tick()
        fresh = self.only('claude-reviewer')  # nothing else is ready: no new verification, no second security review
        self.assertEqual(fresh['evidence_retry'], rows['claude-reviewer']['evidence_retry'] + 1)
        self.assertEqual(count(), before + 1)
        self.assertEqual(self.project()['stage_retries'], {fresh['stage_key'] + ':0': 1})
        self.board.complete(fresh); self.tick()
        self.assertIn('code', [t['id'] for t in self.project()['completed']])  # the other reviewer's valid result was reused

    def test_a_stage_retry_infers_the_stalled_reviewer_for_a_stop_recorded_without_last_node(self):
        self.plan()
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        rows = {r['profile']: r for r in self.board.ready()}
        self.board.complete(rows['claude-reviewer'])
        reviewer = rows['security-reviewer']  # the second reviewer stalls after the first was accepted, as in the live incident
        self.conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (reviewer['task_id'],)); self.conn.commit()
        self.tick(); self.board.complete(self.only('factory-retro')); self.tick()
        project = self.project(); project.pop('last_node', None)  # as stored by a controller that did not record it
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(project),)); self.conn.commit()
        self.controller.resume(self.conn, self.root, 'The reviewer tool is back', dict(retry_stage=True)); self.tick()
        fresh = self.only('security-reviewer')  # only the stalled reviewer: no second verification, no repeat of the accepted claude review
        self.assertEqual(fresh['evidence_retry'], reviewer['evidence_retry'] + 1)

    def style_task_reviewers(self, changed_files):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=dict(art=True, audio=False, ui=True, ux=False)); self.tick()
        self.board.complete(self.only('art-director')); self.tick()
        self.approve()
        self.architect([MIXED])
        self.board.complete(self.only('claude-reviewer')); self.tick()
        extra = dict(changed_files=changed_files) if changed_files is not None else {}
        self.board.complete(self.only('developer'), **extra); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        return {r['profile'] for r in self.board.ready()}

    def test_a_task_that_changed_only_the_style_bible_is_reviewed_without_the_art_reviewer(self):
        panel = self.style_task_reviewers(['art/style/STYLE.md', 'art/style/style.json', 'art/style/reference/look-D.png'])
        self.assertNotIn('art-reviewer', panel)
        self.assertIn('ui-reviewer', panel)  # every other reviewer the task needs still reviews it
        self.assertTrue(self.project()['work']['style_only'])

    def test_no_task_panel_ever_contains_the_art_reviewer_whatever_the_task_changed(self):
        # Art review is ONE final gate on the assembled, engine-rendered game: nothing visual blocks an individual task.
        for changed in (['art/style/STYLE.md', 'Assets/Art/Room01/wall.png'], None):
            with self.subTest(changed=changed):
                self.setUp()
                self.assertNotIn('art-reviewer', self.style_task_reviewers(changed))

    def test_the_panel_never_drops_the_art_reviewer_from_the_final_integration(self):
        from factory_dashboard.project_controller import ProjectController
        task = dict(id='integration', needs=dict(art=True, audio=False, ui=True, ux=False), risk='normal')
        panel = ProjectController._panel(['claude-reviewer', 'art-reviewer', 'ui-reviewer'], task, dict(style_only=True))
        self.assertIn('art-reviewer', panel)

    def test_stages_after_a_task_that_amended_the_style_bible_are_told_the_plans_style_hash_is_stale(self):
        second = dict(CODE, id='more', dependencies=['code'])
        self.plan(tasks=[CODE, second])
        first_card = self.board.cards[self.only('developer')['task_id']]['body']
        self.assertNotIn('amended the style bible', first_card)
        self.board.complete(self.only('developer'), changed_files=['art/style/STYLE.md', 'art/style/style.json']); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        for row in self.board.ready(): self.board.complete(row)
        self.tick()
        self.assertTrue(self.project()['completed'][0]['style_changed'])
        card = self.board.cards[self.only('developer')['task_id']]['body']
        self.assertIn('The completed task code amended the style bible under art/style/', card)
        self.assertIn('take the expected hash when your stage starts', card)
        self.board.complete(self.only('developer')); self.tick()
        verify = self.board.cards[self.only('verifier')['task_id']]['body']
        self.assertIn('style_sha256 the writer recorded', verify)

    def test_a_task_that_changed_no_style_file_does_not_trigger_the_style_note(self):
        second = dict(CODE, id='more', dependencies=['code'])
        self.plan(tasks=[CODE, second])
        self.board.complete(self.only('developer'), changed_files=['Assets/Scripts/Game.cs']); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        for row in self.board.ready(): self.board.complete(row)
        self.tick()
        self.assertFalse(self.project()['completed'][0]['style_changed'])
        self.assertNotIn('amended the style bible', self.board.cards[self.only('developer')['task_id']]['body'])

    def blocked_repair(self, defect, prior_refunds=0):
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'},
                            findings=['F1|HIGH|AC1|code.py|Real defect to repair'], repair_domains=['code']); self.tick()
        if prior_refunds:
            project = self.project(); project['work']['tool_defect_refunds'] = [dict(key='x')] * prior_refunds
            self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(project),)); self.conn.commit()
        extra = dict(tool_defect=defect) if defect else {}
        self.block(self.only('fixer'), 'Cannot continue', **extra)
        self.tick()
        return self.project()

    def test_a_human_can_drop_a_model_override_and_the_profile_default_applies_again(self):
        project = self.blocked_repair(None)
        project['model_overrides'] = dict(fixer=dict(provider='openai-codex', model='gpt-5', effort='high', note='n', at=1))
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(project),)); self.conn.commit()
        self.conn.execute("UPDATE factory_workflow_roots SET phase='blocked'"); self.conn.commit()  # what the stop does to the root
        self.controller.resume(self.conn, self.root, 'Provider key expired: back to the profile default', dict(model_overrides=dict(fixer=None)))
        project = self.project()
        self.assertEqual(project.get('model_overrides'), {})
        entry = next(e for e in project['orchestration_log'] if e['kind'] == 'human_model_override')
        self.assertEqual(entry['models'], {'fixer': 'profile default'})
        self.assertEqual(self.used(), (1, 0))  # dropping an override grants nothing

    def test_clearing_an_override_needs_a_recorded_note_and_a_valid_profile_name(self):
        from factory_dashboard.project_decisions import normalize_decisions
        from factory_dashboard.model_policy import ConfigurationError
        with self.assertRaises(ConfigurationError):
            normalize_decisions(dict(model_overrides=dict(fixer=None)), '')
        with self.assertRaises(ConfigurationError):
            normalize_decisions(dict(model_overrides={'Bad Name': None}), 'x')
        self.assertEqual(normalize_decisions(dict(model_overrides=dict(fixer=None)), 'x')['model_overrides'], dict(fixer=None))

    def routed_repair(self, finding):
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier'), verdict='FAIL', ac_results={'AC1': 'fail'}, findings=[finding], repair_domains=['code']); self.tick()
        return self.only('fixer')

    def visual_opinion_flow(self, severity, path='Assets/Art/Room01/room01-wall-backdrop.png'):
        self.plan(art=True, tasks=[dict(SPRITES, id='sprites')])
        self.board.complete(self.only('artist')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        for row in self.board.ready():
            if row['profile'] == 'claude-reviewer':
                self.board.complete(row, verdict='CHANGES_REQUIRED' if severity in ('HIGH', 'BLOCKER') else 'NO_BLOCKING_FINDINGS',
                                    findings=['F1|%s|AC1|%s|the texture is too gritty and the look differs from the reference' % (severity, path)])
            else:
                self.complete_review(row)
        self.tick()

    def test_another_reviewers_visual_opinion_of_an_image_asset_never_blocks_a_task_or_spends_a_repair(self):
        self.visual_opinion_flow('MEDIUM')
        self.assertEqual(self.used(), (0, 0))                                        # no repair was charged
        self.assertNotEqual([r['profile'] for r in self.board.ready()], ['artist'])  # and no artist repair was scheduled
        self.assertIn('sprites', [c['id'] for c in self.project()['completed']])      # the task completed on its technical checks

    def test_a_high_finding_on_an_image_asset_is_still_a_blocking_technical_problem(self):
        self.visual_opinion_flow('HIGH')
        self.assertEqual(self.used(), (1, 0))                                        # a corrupt or wrongly sized file would be reported like this and still blocks
        self.assertIn('fixer', [r['profile'] for r in self.board.ready()])           # another reviewer's blocking finding goes to the fixer

    def test_a_medium_finding_on_a_code_file_still_blocks(self):
        self.visual_opinion_flow('MEDIUM', path='Assets/Scripts/Builder.cs')
        self.assertEqual(self.used(), (1, 0))

    def test_non_art_reviewer_cards_forbid_visual_judgement_and_the_art_reviewer_is_not_told_that(self):
        self.plan(art=True, tasks=[dict(SPRITES, id='sprites')])
        self.board.complete(self.only('artist')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        cards = {r['profile']: self.board.cards[r['task_id']]['body'] for r in self.board.ready()}
        self.assertNotIn('art-reviewer', cards)
        for profile, body in cards.items():
            self.assertIn('Do not judge how an art asset looks', body, profile)
            self.assertIn('your opinion of it is never a finding at any severity', body, profile)

    def test_the_verifier_card_limits_look_criteria_to_objective_properties_and_leaves_style_to_the_final_review(self):
        self.plan(art=True, tasks=[dict(SPRITES, id='sprites')])
        self.board.complete(self.only('artist')); self.tick()
        body = self.board.cards[self.only('verifier')['task_id']]['body']
        for text in ('only through objective, measurable properties', 'cropping at the canvas edge', 'stray or\ndetached fragments', 'judged once, by the final art review of the complete game',
                     'A cropped sprite, stray fragments, a wrong size or lost transparency are technical defects and still fail'):
            self.assertIn(text, body)
        self.board.complete(self.only('verifier')); self.tick()
        for row in self.board.ready():
            self.assertNotIn('only through objective, measurable properties', self.board.cards[row['task_id']]['body'], row['profile'])   # reviewers have their own rule

    def test_the_gate_waives_only_medium_visual_findings_of_non_art_reviewers_on_image_files(self):
        from factory_dashboard.workflow_gate import evaluate_cycle
        from types import SimpleNamespace
        def writer(): return SimpleNamespace(valid=True, metadata=dict(verdict='DONE', manifest_sha12='m', ac_ids=['AC1']))
        def reader(profile, finding): return SimpleNamespace(valid=True, kind='review', metadata=dict(manifest_sha12='m', source_profile=profile, findings=[finding], verdict='CHANGES_REQUIRED' if '|HIGH|' in finding or profile == 'art-reviewer' else 'NO_BLOCKING_FINDINGS', tool_incidents=[], blocked_tools=[]))
        png = lambda sev: f'F1|{sev}|AC1|Assets/a.png|looks off'
        verifier = lambda: SimpleNamespace(valid=True, kind='verify', metadata=dict(manifest_sha12='m', source_profile='verifier', ac_results={'AC1': 'pass'}, failed_checks=[], checks_failed=0,
                                                                              release_audit='PASS', verdict='PASS', findings=[], tool_incidents=[], blocked_tools=[]))
        for profile, sev, blocks in (('claude-reviewer', 'MEDIUM', False), ('security-reviewer', 'MEDIUM', False), ('claude-reviewer', 'HIGH', True), ('art-reviewer', 'MEDIUM', True)):
            decision = evaluate_cycle(writer(), [verifier(), reader(profile, png(sev))], None, 5, 0, dict(visual_final_only=True))
            self.assertEqual(decision.decision == 'repair', blocks, (profile, sev))
        off = evaluate_cycle(writer(), [verifier(), reader('claude-reviewer', png('MEDIUM'))], None, 5, 0, dict())
        self.assertEqual(off.decision, 'repair')                                   # without the flag the old behaviour is unchanged

    def test_owned_paths_come_only_from_explicit_finding_files_and_fail_closed(self):
        from factory_dashboard.project_controller import owned_paths
        self.assertEqual(owned_paths(['verifier:F1|HIGH|AC2|Assets/Art/a.png|x', 'F2|LOW|AC2|Assets/Art/a.png|dup', 'F3|LOW|AC2|b/c d.txt|x']), ['Assets/Art/a.png', 'b/c d.txt'])
        for bad in ('F1|HIGH|AC2||no path', 'F1|HIGH|AC2|Assets/*.png|pattern', 'F1|HIGH|AC2|/abs/a.png|abs', 'F1|HIGH|AC2|../a.png|up', 'F1|HIGH|AC2|Assets|dir', 'F1|HIGH|AC2|a.png,b.png|two', 'short|only'):
            self.assertEqual(owned_paths([bad]), [], bad)
        self.assertEqual(owned_paths(None), [])

    def test_a_repair_card_names_the_owned_files_and_keeps_the_check_mandatory(self):
        card = self.board.cards[self.routed_repair('F1|HIGH|AC1|code.py|Real defect to repair')['task_id']]['body']
        self.assertIn('OWNED_PATHS code.py', card)
        base = self.project()['work']['manifest'][:12]
        self.assertIn('fw.py check PROJECT_DIR --expect %s --owned "code.py"' % base, card)
        self.assertIn('authoritative baseline manifest for this check is ' + base, card)
        self.assertIn('still mandatory', card)

    def test_with_a_verified_baseline_snapshot_the_card_header_keeps_the_controller_baseline(self):
        import os
        row = self.routed_repair('F1|HIGH|AC1|code.py|Real defect to repair')
        authoritative = self.project()['work']['manifest'][:12]
        snap = os.path.join(self.temp.name, 'src-%s.tgz' % authoritative)
        open(snap, 'w').write('x')
        from factory_dashboard import project_controller as pc
        original = pc.baseline_snapshot
        pc.baseline_snapshot = lambda manifest, hint: snap   # content verification of real archives is covered by its own test
        self.addCleanup(lambda: setattr(pc, 'baseline_snapshot', original))
        self.block(row, 'start check failed', manifest_sha12='2a733f8c645d'); self.tick()
        self.conn.execute("UPDATE factory_workflow_roots SET phase='blocked'"); self.conn.commit()
        self.controller.resume(self.conn, self.root, 'Fresh attempt after a blocked one'); self.tick()
        fixer = next(r for r in self.board.ready() if r['profile'] == 'fixer')
        card = self.board.cards[fixer['task_id']]['body']
        self.assertIn('BASELINE ' + authoritative, card)
        self.assertNotIn('2a733f8c645d', card.split('INSTRUCTIONS')[0])
        self.assertIn('--expect %s --owned "code.py" --baseline-tgz "%s"' % (authoritative, snap), card)

    def test_run_214_a_blocked_predecessors_mutated_manifest_never_becomes_the_owned_checks_baseline(self):
        row = self.routed_repair('F1|HIGH|AC1|code.py|Real defect to repair')
        authoritative = self.project()['work']['manifest'][:12]
        mutated = '2a733f8c645d'   # run 212: the blocked worker ran `fw.py manifest` and reported the rebuilt manifest
        self.assertNotEqual(authoritative, mutated)
        self.block(row, 'start check failed', manifest_sha12=mutated); self.tick()
        self.conn.execute("UPDATE factory_workflow_roots SET phase='blocked'"); self.conn.commit()
        self.controller.resume(self.conn, self.root, 'Fresh attempt after a blocked one'); self.tick()
        fixer = next(r for r in self.board.ready() if r['profile'] == 'fixer')   # the retro of the stopped attempt is ready too
        card = self.board.cards[fixer['task_id']]['body']
        self.assertIn('BASELINE ' + mutated, card)                    # the existing continue-from-the-tree header still follows the predecessor
        self.assertIn('--expect %s --owned "code.py"' % authoritative, card)   # but the owned check expects the controller's baseline, never the mutated one
        self.assertNotIn('--expect %s --owned' % mutated, card)
        self.assertIn('authoritative baseline manifest for this check is ' + authoritative, card)
        self.assertIn('overrides the BASELINE in this card', card)
        self.assertEqual(self.project()['work']['manifest'][:12], authoritative)   # the controller's baseline was not redefined

    def test_a_blocked_before_editing_repair_is_told_not_to_rebuild_the_baseline_manifest(self):
        card = self.board.cards[self.routed_repair('F1|HIGH|AC1|code.py|Real defect to repair')['task_id']]['body']
        self.assertIn('never run `fw.py manifest`', card)
        self.assertIn('report the BASELINE value as manifest_sha12', card)

    def test_the_baseline_snapshot_is_the_archive_that_really_holds_the_baseline_manifest(self):
        from factory_dashboard.project_controller import baseline_snapshot
        import hashlib, io, os, tarfile, tempfile

        def make(path, manifest_text):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with tarfile.open(path, 'w:gz') as tar:
                data = manifest_text.encode(); info = tarfile.TarInfo('.factory/SHA256SUMS'); info.size = len(data); tar.addfile(info, io.BytesIO(data))
            return hashlib.sha256(manifest_text.encode()).hexdigest()[:12]
        with tempfile.TemporaryDirectory() as root:
            sha_a = make(os.path.join(root, 't_a', 'src-LAST.tgz'), 'a\n')            # the card's own snapshot: another manifest
            sha_b = make(os.path.join(root, 't_b', 'src-%s.tgz' % hashlib.sha256(b'b\n').hexdigest()[:12]), 'b\n')
            hint = os.path.join(root, 't_a', 'src-LAST.tgz')
            self.assertEqual(baseline_snapshot(sha_b, hint), os.path.join(root, 't_b', 'src-%s.tgz' % sha_b))
            self.assertEqual(baseline_snapshot(sha_a, hint), '')   # named src-LAST, not src-<sha>: never matched by content alone
            lying = os.path.join(root, 't_c', 'src-%s.tgz' % ('c' * 12)); make(lying, 'not what the name says\n')
            self.assertEqual(baseline_snapshot('c' * 12, hint), '')   # the name is not trusted: the content hash must match
            self.assertEqual(baseline_snapshot('d' * 12, hint), '')
            self.assertEqual(baseline_snapshot(sha_b, 'none'), '')
            self.assertEqual(baseline_snapshot('not-a-sha', hint), '')
            self.assertEqual(baseline_snapshot('', hint), '')

    def test_the_owned_check_uses_the_baseline_snapshot_only_when_the_card_has_one(self):
        from factory_dashboard.project_cards import OWNED_CHECK
        with_tgz = OWNED_CHECK.format(owned='a.png', expect='abcdef123456', tgz=' --baseline-tgz "/x/src-0.tgz"', rebuilt=' --baseline-tgz compares')
        without = OWNED_CHECK.format(owned='a.png', expect='abcdef123456', tgz='', rebuilt='')
        self.assertIn('--owned "a.png" --baseline-tgz "/x/src-0.tgz"', with_tgz)
        self.assertNotIn('--baseline-tgz', without)


        card = self.board.cards[self.routed_repair('F1|HIGH|AC1||Real defect with no file')['task_id']]['body']
        self.assertNotIn('OWNED_PATHS', card)

    def test_a_normal_writer_card_has_no_owned_check(self):
        self.plan()
        self.assertNotIn('OWNED_PATHS', self.board.cards[self.only('developer')['task_id']]['body'])

    def finish_repair(self, row, start_check):
        self.board.complete(row, verdict='DONE', start_check=start_check); self.tick()

    def test_an_owned_start_check_is_accepted_recorded_and_audited(self):
        row = self.routed_repair('F1|HIGH|AC1|code.py|Real defect to repair')
        base = self.project()['work']['manifest']
        self.finish_repair(row, dict(baseline_sha12=base[:12], owned=['code.py'], differed=['code.py'], accepted_owned=['code.py'], rejected_outside_scope=[]))
        project = self.project()
        entry = next(e for e in project['orchestration_log'] if e['kind'] == 'start_check_owned')
        self.assertEqual((entry['accepted'], entry['differed'], entry['baseline']), (['code.py'], ['code.py'], base[:12]))
        self.assertTrue(self.conn.execute("SELECT 1 FROM factory_workflow_events WHERE kind='project_start_check_owned'").fetchone())

    def test_a_start_check_that_accepts_a_file_the_repair_does_not_own_is_rejected(self):
        row = self.routed_repair('F1|HIGH|AC1|code.py|Real defect to repair')
        base = self.project()['work']['manifest']
        self.finish_repair(row, dict(baseline_sha12=base[:12], owned=['code.py', 'other.py'], differed=['other.py'], accepted_owned=['other.py'], rejected_outside_scope=[]))
        self.assertFalse(any(e['kind'] == 'start_check_owned' for e in self.project().get('orchestration_log', [])))
        self.assertNotEqual(self.project().get('work', {}).get('step'), 'verifying')

    def test_a_start_check_against_another_baseline_or_with_outside_differences_is_rejected(self):
        for wrong in (dict(baseline_sha12='0' * 12), dict(rejected_outside_scope=['other.py'])):
            with self.subTest(wrong=wrong):
                row = self.routed_repair('F1|HIGH|AC1|code.py|Real defect to repair')
                base = self.project()['work']['manifest']
                record = dict(baseline_sha12=base[:12], owned=['code.py'], differed=['code.py'], accepted_owned=['code.py'], rejected_outside_scope=[])
                record.update(wrong)
                self.finish_repair(row, record)
                self.assertFalse(any(e['kind'] == 'start_check_owned' for e in self.project().get('orchestration_log', [])))
                self.tearDown(); self.setUp()

    def test_a_start_check_on_a_card_without_owned_paths_is_rejected(self):
        row = self.routed_repair('F1|HIGH|AC1||Real defect with no file')
        base = self.project()['work']['manifest']
        self.finish_repair(row, dict(baseline_sha12=base[:12], owned=['code.py'], differed=['code.py'], accepted_owned=['code.py'], rejected_outside_scope=[]))
        self.assertFalse(any(e['kind'] == 'start_check_owned' for e in self.project().get('orchestration_log', [])))

    # --- BLOCKED is a last resort and needs proof of a real attempt ---
    def blocked_plain(self, row, **extra):
        self.board.complete(row, verdict='BLOCKED', blocked_reason='The plan is not staged', **extra)

    def test_a_writer_that_finishes_blocked_with_no_evidence_is_sent_back_not_stopped_and_costs_no_budget(self):
        self.plan()
        row = self.only('developer')
        self.blocked_plain(row); self.tick()
        project = self.project()
        self.assertNotIn('terminal', project)                                        # the project did not stop for a human
        self.assertEqual(project['handoff_retries'], {'task-code-implement:0': 1})   # a bounded handoff retry...
        self.assertEqual(self.used(), (0, 0))                                        # ...that spends no repair budget
        self.assertTrue(any(e['kind'] == 'handoff_retry' and 'Unsupported BLOCKED' in e['reason'] for e in project['orchestration_log']))
        again = self.only('developer')
        self.assertNotEqual(again['task_id'], row['task_id'])                        # a fresh card for the same stage
        body = self.board.cards[again['task_id']]['body']
        self.assertIn('Unsupported BLOCKED: no evidence of an attempt', json.dumps(self.board.get_task(self.conn, again['task_id']).__dict__, default=str) + body)

    def test_evidence_that_the_session_never_produced_is_refused_as_invented(self):
        self.plan()
        row = self.only('developer')
        record_tool_session(self.home, 'developer', 'inventedsession1', 'ls', 'total 8 drwxr-xr-x something real')
        self.board.complete(row, verdict='BLOCKED', blocked_reason='Blocked by the approvals guard',
                            blocked_evidence=[dict(command='sh tool.sh', output='the approvals guard refused this command outright')])
        run = self.conn.execute('SELECT id,metadata FROM task_runs WHERE task_id=? ORDER BY id DESC', (row['task_id'],)).fetchone()
        meta = json.loads(run[1]); meta['worker_session_id'] = 'inventedsession1'
        self.conn.execute('UPDATE task_runs SET metadata=? WHERE id=?', (json.dumps(meta), run[0])); self.conn.commit()
        self.tick()
        self.assertNotIn('terminal', self.project())
        self.assertTrue(any('does not match the tool calls and outputs of your session' in e['reason'] for e in self.project()['orchestration_log'] if e['kind'] == 'handoff_retry'))

    def test_evidence_that_matches_the_session_is_a_genuine_block_and_still_stops_for_a_human(self):
        self.plan()
        self.block(self.only('developer'), 'The compiler is missing'); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')
        self.assertIn('The compiler is missing', self.project()['terminal']['reason'])
        self.assertEqual(self.project().get('handoff_retries', {}), {})

    def test_the_bounded_retry_ends_at_its_limit_with_the_stop_the_worker_earned(self):
        self.plan()
        for attempt in range(1, 4):
            self.blocked_plain(self.only('developer')); self.tick()
            if attempt < 3:
                self.assertNotIn('terminal', self.project(), attempt)
        self.assertEqual(self.project()['handoff_retries']['task-code-implement:0'], 2)
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')       # an exhausted handoff budget is a stop for a human, never an unlimited loop

    def test_a_specification_conflict_and_a_declared_tool_defect_carry_their_own_account_and_are_exempt(self):
        self.plan()
        self.blocked_plain(self.only('developer'), tool_defect='sprite_fit --coverage opaque still returned opaque 0.03'); self.tick()
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')
        self.assertIn('Tool defect reported', self.project()['terminal']['reason'])

    def test_a_non_writer_blocked_is_not_subject_to_the_evidence_rule(self):
        from factory_dashboard.project_controller import ProjectController
        for kind in ('prepare', 'review', 'verify'):
            result = type('R', (), dict(metadata=dict(verdict='BLOCKED')))()
            self.assertIsNone(ProjectController._unsupported_block(self, self.conn, kind, 'x', result))

    def test_writer_cards_carry_the_blocked_needs_evidence_rule_and_reviewer_cards_do_not(self):
        self.plan()
        body = self.board.cards[self.only('developer')['task_id']]['body']
        for text in ('BLOCKED is a last resort', 'metadata.blocked_evidence', 'a missing .factory/include.txt entry (add the path)', 'an unspecified pixel size (derive it)',
                     'a path or filename named in the acceptance text (create it)', 'costs no repair budget'):
            self.assertIn(text, body)
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        for row in self.board.ready():
            self.assertNotIn('metadata.blocked_evidence', self.board.cards[row['task_id']]['body'], row['profile'])

    def test_a_non_artist_writer_card_has_no_fit_mode_text(self):
        self.plan()
        self.assertNotIn('Fit mode (required', self.board.cards[self.only('developer')['task_id']]['body'])

    def test_a_repair_that_reports_a_tool_defect_is_refunded_recorded_and_not_held_against_the_budget(self):
        project = self.blocked_repair('sprite_fit --coverage opaque still returned opaque 0.03 on the floor band')
        self.assertEqual(self.used(), (0, 0))  # the product charge was given back
        self.assertEqual(len(project['work']['tool_defect_refunds']), 1)
        self.assertIn('opaque 0.03', project['work']['tool_defect_refunds'][0]['defect'])
        self.assertTrue(any(l['kind'] == 'tool_defect_refund' for l in project['orchestration_log']))
        self.assertIn('Tool defect reported by fixer', project['terminal']['reason'])
        self.assertIn('not held against the product repair budget', project['terminal']['reason'])
        self.assertTrue(self.conn.execute("SELECT 1 FROM factory_workflow_events WHERE kind='project_repair_refunded'").fetchone())

    def test_a_blocked_repair_without_a_tool_defect_keeps_its_charge(self):
        project = self.blocked_repair(None)
        self.assertEqual(self.used(), (1, 0))
        self.assertNotIn('tool_defect_refunds', project['work'])
        self.assertTrue(project['terminal']['reason'].startswith('Stage blocked'))

    def test_tool_defect_refunds_are_bounded_so_one_fault_cannot_loop_forever(self):
        project = self.blocked_repair('the same tool defect again', prior_refunds=2)
        self.assertEqual(self.used(), (1, 0))   # the cap is spent: the charge stays and a human decides
        self.assertEqual(len(project['work']['tool_defect_refunds']), 2)

    # --- the independent plan review is off by default ---
    def review_off(self):
        from unittest import mock
        from factory_dashboard import project_controller
        patcher = mock.patch.object(project_controller, 'PLAN_REVIEW_ENABLED', False)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_without_plan_review_a_valid_plan_goes_straight_to_task_execution(self):
        self.review_off()
        self.start_planning(); self.architect()
        self.assertEqual(self.project()['mode'], 'tasks')
        self.assertEqual(self.only('developer')['stage_key'], 'task-code-implement')
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE stage_key LIKE 'project-plan-review%'").fetchone())
        event = json.loads(self.conn.execute("SELECT document FROM factory_workflow_events WHERE kind='project_plan_approved'").fetchone()[0])
        self.assertEqual((event['reviewer'], event['review']), (None, 'disabled'))

    def test_without_plan_review_an_invalid_plan_is_still_rejected_structurally(self):
        self.review_off()
        self.start_planning(); self.architect(tasks=self.BAD_PLAN)
        self.assertEqual(self.only('architect')['evidence_retry'], 1)
        self.assertNotEqual(self.project()['mode'], 'tasks')

    def test_a_project_stopped_in_the_old_review_stage_is_approved_without_a_reviewer_once_review_is_off(self):
        self.start_planning(); self.architect()
        self.assertEqual(self.project()['mode'], 'plan_review')
        self.only('claude-reviewer')  # the review card exists, nobody ran it
        self.review_off()
        self.tick()
        self.assertEqual(self.project()['mode'], 'tasks')
        # The unrun review card stays on the board (the controller never archives mid-transaction); the project moves on without it.
        self.assertTrue(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE stage_key='task-code-implement'").fetchone())

    def test_the_verifier_card_says_gates_needing_the_whole_checkout_are_writer_gates(self):
        self.plan(); self.board.complete(self.only('developer')); self.tick()
        card = self.board.cards[self.only('verifier')['task_id']]['body']
        self.assertIn('These are writer or publisher gates', card)
        self.assertIn('never in failed_checks', card)
        self.assertIn('Not a Unity project', card)
        self.assertIn('npm audit', card); self.assertIn('ENOLOCK', card); self.assertIn('residual_risk and never in failed_checks', card)

    # --- uncovered project ACs are surfaced, reviewed and made explicit integration work ---
    def test_an_uncovered_project_ac_is_recorded_shown_to_the_plan_reviewer_and_is_not_an_error(self):
        self.start_planning()
        self.architect(ac_ids=['AC1', 'AC2'])
        self.assertEqual(self.project()['uncovered_acs'], ['AC2'])
        self.assertNotIn('1', self.project().get('plan_validation_retries', {}))  # accepted on the first submission, no correction round
        review = self.board.cards[self.only('claude-reviewer')['task_id']]['body']
        self.assertIn('UNCOVERED ACCEPTANCE CRITERIA: no task states AC2', review)
        self.assertIn('BLOCKER finding that names its AC id', review)
        self.assertTrue(self.conn.execute("SELECT 1 FROM factory_workflow_events WHERE kind='plan_uncovered_acs'").fetchone())
        self.assertTrue(any(l['kind'] == 'plan_uncovered_acs' and l['acs'] == ['AC2'] for l in self.project()['orchestration_log']))

    def test_a_fully_covered_plan_adds_no_uncovered_note(self):
        self.start_planning(); self.architect()
        self.assertEqual(self.project()['uncovered_acs'], [])
        self.assertNotIn('UNCOVERED', self.board.cards[self.only('claude-reviewer')['task_id']]['body'])

    def test_integration_states_each_uncovered_ac_with_its_plan_text(self):
        from factory_dashboard.project_controller import ProjectController
        plan = Path(self.temp.name) / 'PLAN.md'
        plan.write_text('# Plan\n- **AC1** The room loads\n- **AC2**: Enemies drop a pickup when defeated\n')
        project = dict(ac_ids=['AC1', 'AC2'], uncovered_acs=['AC2'], plans=[dict(profile='architect', path=str(plan))])
        acceptance = ProjectController._integration_acceptance(project)
        self.assertEqual(acceptance['AC1'], 'Project PLAN.md: AC1')
        self.assertTrue(acceptance['AC2'].startswith('NOT STATED BY ANY PLANNED TASK: implement and verify it here. Enemies drop a pickup when defeated'))
        project['plans'] = []  # an unreadable plan still yields an explicit criterion
        self.assertIn('NOT STATED BY ANY PLANNED TASK', ProjectController._integration_acceptance(project)['AC2'])

    # --- stage retry: re-run only the stopped stage, keep history ---
    def stopped_on_a_blocked_writer(self):
        self.plan()
        self.block(self.only('developer'), 'The linter cannot express the plan')
        self.tick(); self.board.complete(self.only('factory-retro'))
        self.assertEqual(self.tick()['phase'], 'blocked')

    def developer_rows(self):
        return [dict(r) for r in self.conn.execute("SELECT task_id,evidence_retry FROM factory_workflow_stages WHERE profile='developer' ORDER BY evidence_retry")]

    def test_retry_stage_reruns_only_the_stopped_stage_and_keeps_its_history(self):
        self.stopped_on_a_blocked_writer()
        before = self.developer_rows(); old_task = before[-1]['task_id']
        project = self.project(); replans, history = project.get('replans', 0), len(project['history'])
        self.controller.resume(self.conn, self.root, 'Tooling corrected', dict(retry_stage=True))
        self.tick()
        after = self.developer_rows()
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[-1]['evidence_retry'], before[-1]['evidence_retry'] + 1)
        self.assertEqual(after[0]['task_id'], before[0]['task_id'])  # the stopped row is history, not deleted
        self.assertEqual(self.board.get_task(self.conn, old_task).status, 'done')
        project = self.project()
        self.assertNotIn('terminal', project)
        self.assertEqual(project.get('replans', 0), replans)
        self.assertGreaterEqual(len(project['history']), history)
        self.assertEqual(project['stage_retries'], {'task-code-implement:0': 1})
        card = self.board.cards[self.only('developer')['task_id']]['body']
        self.assertIn('Earlier attempts of this stage (' + old_task + ') are superseded', card)
        self.assertIn('never run fw.py check --expect with a manifest taken from an earlier attempt', card)
        self.assertEqual(project['orchestration_log'][-2]['kind'], 'human_stage_retry')
        self.board.complete(self.only('developer')); self.tick()  # the fresh result carries no stale defect: the project goes on
        self.only('verifier')

    def test_retry_stage_is_bounded_per_stage(self):
        self.stopped_on_a_blocked_writer()
        for attempt in range(2):
            self.controller.resume(self.conn, self.root, 'Tooling corrected', dict(retry_stage=True)); self.tick()
            self.block(self.only('developer'), 'Still blocked')
            self.tick(); self.board.complete(self.only('factory-retro'))
            self.assertEqual(self.tick()['phase'], 'blocked')
        with self.assertRaisesRegex(ConfigurationError, 'human stage retries'):
            self.controller.resume(self.conn, self.root, 'One more', dict(retry_stage=True))
        self.assertEqual(self.project()['terminal']['phase'], 'blocked')  # a refused retry changes nothing

    def test_retry_stage_is_refused_while_the_stage_is_running(self):
        self.stopped_on_a_blocked_writer()
        self.controller.resume(self.conn, self.root, 'Tooling corrected', dict(retry_stage=True)); self.tick()
        running = len(self.developer_rows())
        project = self.project(); project['terminal'] = dict(phase='human_review', reason='stale'); project['mode'] = 'finished'
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(project),))
        self.conn.execute("UPDATE factory_workflow_roots SET phase='human_review'"); self.conn.commit()
        with self.assertRaisesRegex(ConfigurationError, 'would run it twice'):
            self.controller.resume(self.conn, self.root, 'Again', dict(retry_stage=True))
        self.assertEqual(len(self.developer_rows()), running)

    def test_retry_stage_cannot_be_combined_with_reevaluate(self):
        self.stopped_on_a_blocked_writer()
        with self.assertRaisesRegex(ConfigurationError, 'Choose one'):
            self.controller.resume(self.conn, self.root, 'Both', dict(retry_stage=True), True)

    # --- bounded plan_correction, separate from architectural replans ---
    BASELINE = 'deadbeefcafe1234'
    LOCAL = ['F1|MEDIUM|AC1|code|State that the waived check is reported as waived, never as pass']

    def reviewed_plan(self, findings, classes=None, original_text=None):
        self.start_planning(); self.architect()
        if original_text:
            Path(next(p for p in self.project()['plans'] if p['profile'] == 'architect')['path']).write_text(original_text)
        extra = dict(findings=findings, **({'finding_classes': classes} if classes else {}))
        self.board.complete(self.only('claude-reviewer'), **extra); self.tick()

    def correction_card(self):
        return next(r for r in self.board.ready() if r['stage_key'].startswith('project-plan-correction-g') and 'review' not in r['stage_key'])

    def correct(self, tasks=None, text='Plan text with the baseline deadbeefcafe1234 retained', **overrides):
        stage = self.correction_card()
        folder = Path(self.temp.name) / f'correction-{stage["task_id"]}'; folder.mkdir()
        plan = folder / 'project-plan.json'; plan.write_text(json.dumps(dict(tasks=tasks or [CODE])))
        metadata = self.board.complete(stage, **overrides)
        Path(metadata['artifacts'][0]).write_text(text)
        self.conn.execute('INSERT INTO attachments VALUES(?,?)', (stage['task_id'], str(plan)))
        run = json.loads(self.conn.execute('SELECT metadata FROM task_runs WHERE task_id=?', (stage['task_id'],)).fetchone()[0]); run['artifacts'].append(str(plan))
        self.conn.execute('UPDATE task_runs SET metadata=? WHERE task_id=?', (json.dumps(run), stage['task_id'])); self.conn.commit()
        self.tick()

    def focused_review(self, **overrides):
        row = next(r for r in self.board.ready() if 'correction-review' in r['stage_key'])
        self.board.complete(row, **overrides); self.tick()

    def test_localized_findings_are_corrected_in_place_reviewed_in_focus_and_cost_no_replan(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        card = self.correction_card()
        self.assertEqual(card['profile'], 'architect')
        self.assertIn('Targeted plan correction', self.board.cards[card['task_id']]['body'])
        self.assertIn('State that the waived check', self.board.cards[card['task_id']]['body'])
        self.correct()
        self.focused_review()
        self.assertEqual(self.only('developer')['stage_key'], 'task-code-implement')  # the plan stands and execution proceeds
        self.assertEqual(self.project().get('replans', 0), 0)
        self.assertEqual(self.project()['plan_corrections'], {'0': 1})
        self.assertIn('plan_correction_accepted', [e['kind'] for e in self.project()['orchestration_log']])

    def test_an_unclassified_or_architectural_finding_still_triggers_a_replan(self):
        self.reviewed_plan(self.LOCAL)  # no classification: architectural by default
        self.assertEqual(self.only('architect')['cycle'], 1)
        self.assertEqual(self.project()['replans'], 1)

    def test_one_architectural_finding_among_corrections_makes_the_whole_review_a_replan(self):
        self.reviewed_plan([*self.LOCAL, 'F2|HIGH|AC1|code|A task is missing'], {'F1': 'correction', 'F2': 'architectural'})
        self.assertEqual(self.only('architect')['cycle'], 1)
        self.assertNotIn('correction', self.project())

    def test_a_correction_that_changes_an_acceptance_criterion_becomes_an_architectural_replan(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        self.correct(tasks=[dict(CODE, acceptance={'AC1': 'A weaker criterion'})])
        project = self.project()
        self.assertNotIn('terminal', project)
        self.assertNotIn('correction', project)
        self.assertEqual(project['replans'], 1)  # a full replan, so the full plan review follows
        self.assertEqual(project['plan_corrections'], {})
        self.assertIn('plan_correction_escalated', [e['kind'] for e in project['orchestration_log']])
        self.assertEqual(self.only('architect')['cycle'], 1)

    def test_a_correction_that_adds_a_task_or_changes_an_owner_also_becomes_a_replan(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        self.correct(tasks=[CODE, dict(CODE, id='extra', title='Extra', dependencies=['code'])])
        self.assertEqual(self.project()['replans'], 1)
        self.assertNotIn('terminal', self.project())

    def test_an_escalating_correction_stops_for_a_human_only_when_the_replan_budget_is_spent(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        spent = self.project()
        spent['replans'] = 2
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(spent, sort_keys=True),))
        self.correct(tasks=[dict(CODE, acceptance={'AC1': 'A weaker criterion'})])
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('replan budget is exhausted', self.project()['terminal']['reason'])
        self.assertEqual(self.project()['replans'], 2)

    def test_a_correction_may_not_drop_the_original_integrity_baselines_and_may_retry_once(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        self.correct(text='The old hash was replaced by 0123456789abcdef')
        retry = self.correction_card()
        self.assertEqual(retry['cycle'], 1)
        body = self.board.cards[retry['task_id']]['body']
        self.assertIn('dropped original integrity baselines', body)
        self.assertIn(self.BASELINE, body)
        self.assertEqual(self.project()['plan_corrections'], {'0': 1})
        self.correct(text=f'Baseline {self.BASELINE} (original) and current 0123456789abcdef (verified)')
        self.focused_review()
        self.only('developer')
        self.assertEqual(self.project()['plan_corrections'], {'0': 2})

    def test_corrections_that_never_pass_the_focused_review_exhaust_two_attempts_then_stop_for_a_human(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        for _ in range(2):
            self.correct()
            self.focused_review(verdict='DONE', findings=['F1|MEDIUM|AC1|code|Still unresolved'])
        self.assertEqual(self.project()['terminal']['phase'], 'human_review')
        self.assertIn('Plan correction budget exhausted after 2 attempts', self.project()['terminal']['reason'])
        self.assertEqual(self.project().get('replans', 0), 0)  # the architectural budget was never touched
        self.assertEqual([e['kind'] for e in self.project()['orchestration_log']].count('plan_correction_failed'), 2)

    def test_the_focused_review_reports_a_plan_defect_when_the_architecture_changed(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        self.correct()
        self.focused_review(plan_defect='The correction quietly changed what AC1 requires')
        self.assertIn('architectural change', self.project()['terminal']['reason'])

    def test_a_structurally_invalid_correction_is_an_attempt_not_a_replan(self):
        self.reviewed_plan(self.LOCAL, {'F1': 'correction'}, self.BASELINE)
        self.correct(tasks=[{**CODE, 'owner': 'nobody'}])
        self.assertEqual(self.correction_card()['cycle'], 1)
        self.assertIn('structural validation', self.board.cards[self.correction_card()['task_id']]['body'])
        self.assertEqual(self.project().get('replans', 0), 0)

    def test_a_human_classification_sends_the_current_findings_through_correction_after_the_replan_limit(self):
        self.exhausted_plan_review()
        reviews = lambda: self.conn.execute("SELECT COUNT(*) FROM factory_workflow_stages WHERE stage_key='project-plan-review'").fetchone()[0]
        before = reviews()
        self.controller.resume(self.conn, self.root, 'These findings are localized wording corrections', dict(plan_correction=['F1']), True)
        self.assertEqual(self.correction_card()['profile'], 'architect')
        self.assertEqual(reviews(), before)  # the plan was not reviewed again from scratch
        self.assertEqual(self.project()['plan_class_overrides']['ids'], ['F1'])

    def test_plan_correction_decisions_apply_only_to_a_plan_review_stop(self):
        self.stalled_artist()
        with self.assertRaises(ConfigurationError):
            self.controller.resume(self.conn, self.root, 'Wrong place for this decision', dict(plan_correction=['F1']), True)

    def test_a_malformed_finding_classification_is_a_handoff_error_and_is_retried(self):
        self.start_planning(); self.architect()
        self.board.complete(self.only('claude-reviewer'), findings=self.LOCAL, finding_classes={'F1': 'maybe'}); self.tick()
        self.assertEqual(self.project()['handoff_retries'], {'project-plan-review:0': 1})

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
        for row in self.board.ready():
            self.board.complete(row)
        self.tick()
        self.board.complete(self.only('developer'));self.tick()        # final integration
        self.board.complete(self.only('verifier'));self.tick()
        siblings=[r for r in self.board.ready() if r['profile']!='art-reviewer']
        for row in siblings:self.conn.execute("UPDATE tasks SET status='running' WHERE id=?",(row['task_id'],))
        art=next(r for r in self.board.ready() if r['profile']=='art-reviewer')
        self.board.complete(art);self.tick()
        self.assertTrue(all(self.board.get_task(self.conn,r['task_id']).status=='blocked' for r in siblings))


if __name__ == '__main__': unittest.main()
