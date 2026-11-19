"""Restart-safe phase transitions; Hermes alone launches the resulting workers."""
from dataclasses import asdict
import json
import re
from pathlib import Path
import time
from .model_policy import ConfigurationError
from .workflow_cards import build_stage_card
from .workflow_gate import evaluate_cycle
from .workflow_guards import controller_scope
from .workflow_handoffs import StageResult, normalize_handoff
from .workflow_types import WorkflowDefinition


class WorkflowController:
    def __init__(self, board_api, state, new_project_root):
        self._board = board_api
        self._state = state
        self._projects = Path(new_project_root)

    def reconcile(self, conn, root_id):
        with self._board.write_txn(conn, allow_nested=True):
            root = self._state.read_root(conn, root_id)
            if not root or root['phase'] in ('delivered','human_review','blocked'):
                return root
            definition = WorkflowDefinition.from_document(root['definition'])
            if definition.execution_version == 2:
                from .project_controller import ProjectController
                return ProjectController(self).reconcile(conn, root, definition)
            task = self._board.get_task(conn,root_id)
            if not task or task.status=='archived':
                return self._stop(conn,root,'blocked','Root is unavailable or archived')
            context = self._context(task)
            self._restore_cycle_context(conn,root,context)
            if not context['project_dir']:
                return self._stop(conn,root,'blocked','Existing project requires an absolute project directory')
            with controller_scope(conn,root_id):
                if root['phase']=='reviewing':
                    self._review(conn,root,definition,context)
                else:
                    self._writer(conn,root,definition,context)
            self._state.mark_reconciled(conn,root_id)
            return self._state.read_root(conn,root_id)

    def _context(self, task):
        header, _, request = (task.body or '').partition('REQUEST:')
        fields = dict(line.split(':',1) for line in header.splitlines() if ':' in line)
        fields = {k.strip():v.strip() for k,v in fields.items()}
        mode = fields.get('PROJECT_MODE','new')
        project = fields.get('PROJECT_DIR','auto')
        if project=='auto':
            project = str(self._projects / task.id) if mode=='new' else ''
        if project and not Path(project).is_absolute():
            project = ''
        return dict(root_id=task.id,project_dir=project,project_mode=mode,request=request or task.body or task.title,
                    acceptance=fields.get('USER_ACCEPTANCE',''),unity_ci=fields.get('UNITY_CI')=='yes',root_header=header)

    def _rows(self,conn,root,stage_key,cycle=None):
        return [dict(r) for r in conn.execute('SELECT * FROM factory_workflow_stages WHERE root_id=? AND stage_key=? AND cycle=? ORDER BY evidence_retry DESC', (root['root_id'],stage_key,root['cycle'] if cycle is None else cycle))]

    def _result(self,conn,stage):
        task = self._board.get_task(conn,stage['task_id'])
        if not task or task.status!='done':
            return None
        run = self._board.get_run(conn,stage['active_run_id']) if stage.get('active_run_id') else None
        if run and not conn.execute(
            "SELECT 1 FROM task_events WHERE task_id=? AND run_id=? AND kind IN ('spawned','worker_registered') LIMIT 1",
            (task.id,run.id),
        ).fetchone():
            return StageResult(False,'Worker launch evidence is missing',stage['kind'],run.id,{})
        expected={**stage,'retained_artifacts':[a.stored_path for a in self._board.list_attachments(conn,task.id)]}
        return normalize_handoff(asdict(task),asdict(run) if run else None,expected)

    def _materialize(self,conn,root,definition,stage,context,inputs,retry=0):
        if self._rows(conn,root,stage.key) and retry==0:
            return
        if stage.kind in ('review','verify') and root['cycle']:
            inputs=list(dict.fromkeys([*inputs,*context['source_inputs']]))
        card = build_stage_card(definition,stage.key,root['cycle'],context,inputs)
        if retry:
            card['idempotency_key'] += f'-r{retry+1}'
        with controller_scope(conn,root['root_id'],stage,root['cycle'],retry):
            task_id = self._board.create_task(conn,**card)
        self._state.event(conn,root['root_id'],'stage_created',dict(task_id=task_id,key=stage.key,cycle=root['cycle'],retry=retry))

    def _accept(self,conn,stage,result):
        conn.execute('UPDATE factory_workflow_stages SET accepted_run_id=? WHERE task_id=?',(result.run_id,stage['task_id']))

    def _writer(self,conn,root,definition,context):
        stage = {'preparing':definition.prepare,'implementing':definition.implement,'repairing':definition.repair}[root['phase']]
        rows = self._rows(conn,root,stage.key)
        if not rows:
            self._materialize(conn,root,definition,stage,context,[])
            return
        current = rows[0]
        result = self._result(conn,current)
        if result is None:
            task=self._board.get_task(conn,current['task_id'])
            if task and task.status in ('blocked','triage','archived'):
                self._stop(conn,root,'blocked','A workflow stage needs intervention before retrying')
            return
        if not result.valid:
            self._stop(conn,root,'human_review',result.reason);return
        if result.metadata['verdict']=='BLOCKED':
            self._stop(conn,root,'blocked',result.metadata.get('blocked_reason','Worker blocked'));return
        if stage.kind=='prepare':
            if not any(re.fullmatch(r'PLAN(?:_[0-9]+)?\.md',Path(p).name) for p in result.metadata['artifacts']):
                self._stop(conn,root,'human_review','Preparation did not retain PLAN.md');return
            self._accept(conn,current,result)
            conn.execute("UPDATE factory_workflow_roots SET phase='implementing' WHERE root_id=?",(root['root_id'],))
            root['phase']='implementing'
            context['plan_artifacts']=result.metadata['artifacts']
            self._materialize(conn,root,definition,definition.implement,context,[current['task_id']])
            return
        plan = self._rows(conn,root,definition.prepare.key,0)[0]
        prepared = self._result(conn,plan)
        if not prepared or not prepared.valid or set(prepared.metadata['ac_ids'])!=set(result.metadata['ac_ids']):
            self._stop(conn,root,'human_review','Writer acceptance criteria differ from the captured plan');return
        self._accept(conn,current,result)
        conn.execute("UPDATE factory_workflow_roots SET phase='reviewing' WHERE root_id=?",(root['root_id'],))
        root['phase']='reviewing';context['manifest']=result.metadata['manifest_sha12']
        for reader in (*definition.reviewers,definition.verify):
            self._materialize(conn,root,definition,reader,context,[current['task_id']])

    def _review(self,conn,root,definition,context):
        writer_spec = definition.repair if root['cycle'] else definition.implement
        writer_stage = self._rows(conn,root,writer_spec.key)[0]
        writer = self._result(conn,writer_stage)
        if not writer:
            self._stop(conn,root,'human_review','Writer evidence is no longer completed');return
        context['manifest']=writer.metadata.get('manifest_sha12','none')
        results=[];waiting=False
        for spec in (*definition.reviewers,definition.verify):
            rows=self._rows(conn,root,spec.key)
            if not rows:
                self._materialize(conn,root,definition,spec,context,[writer_stage['task_id']]);waiting=True;continue
            current=rows[0];result=self._result(conn,current)
            if result is None:
                task=self._board.get_task(conn,current['task_id'])
                if task and task.status in ('blocked','triage','archived'):
                    self._stop(conn,root,'blocked','A review stage needs intervention before retrying');return
                waiting=True;continue
            if not result.valid:
                if current['evidence_retry']==0:
                    self._materialize(conn,root,definition,spec,context,[writer_stage['task_id']],retry=1)
                    waiting=True;continue
                self._stop(conn,root,'human_review',result.reason);return
            self._accept(conn,current,result);results.append(result)
        if waiting:
            return
        prior=conn.execute("SELECT document FROM factory_workflow_events WHERE root_id=? AND kind='gate' ORDER BY id DESC LIMIT 1",(root['root_id'],)).fetchone()
        decision=evaluate_cycle(writer,results,json.loads(prior[0]) if prior else None,definition.max_repairs,root['cycle'],context)
        self._state.event(conn,root['root_id'],'gate',asdict(decision))
        if decision.decision=='pass':
            conn.execute("UPDATE factory_workflow_roots SET phase='delivered',reason=? WHERE root_id=?",(decision.reason,root['root_id']))
            verifier=next(r.metadata for r in results if r.kind=='verify')
            delivery=dict(outcome='LOCAL_DELIVERED',manifest_sha12=writer.metadata['manifest_sha12'],project_dir=context['project_dir'],ac_results=verifier['ac_results'],snapshot=verifier.get('snapshot'),snapshot_attached=verifier['snapshot_attached'],publish_commands=verifier.get('publish_commands',[]),waived=decision.waived)
            conn.execute("UPDATE tasks SET status='done',completed_at=?,result=?,block_kind=NULL WHERE id=?",(int(time.time()),json.dumps(delivery),root['root_id']))
            self._board._append_event(conn,root['root_id'],'completed',delivery)
        elif decision.decision=='repair':
            conn.execute("UPDATE factory_workflow_roots SET phase='repairing',cycle=cycle+1 WHERE root_id=?",(root['root_id'],))
            root['cycle']+=1;root['phase']='repairing';context['blocking']=decision.blocking
            context['baseline']=writer.metadata['manifest_sha12']
            context['baseline_tgz']=next(r.metadata['snapshot'] for r in results if r.kind=='verify') or 'none'
            context['scope']=[finding.split('|',1)[0] for finding in decision.blocking]
            context['source_inputs']=[writer_stage['task_id'],*[r['task_id'] for r in self._current_panel(conn,root,definition,root['cycle']-1)]]
            cycle_context={key:context[key] for key in ('baseline','baseline_tgz','blocking','scope','source_inputs')}
            self._state.event(conn,root['root_id'],'cycle_started',dict(cycle=root['cycle'],context=cycle_context))
            self._materialize(conn,root,definition,definition.repair,context,context['source_inputs'])
        else:
            self._stop(conn,root,decision.decision,decision.reason)

    def _restore_cycle_context(self,conn,root,context):
        if not root['cycle']:
            return
        rows=conn.execute("SELECT document FROM factory_workflow_events WHERE root_id=? AND kind='cycle_started' ORDER BY id DESC",(root['root_id'],))
        for row in rows:
            event=json.loads(row[0])
            if event['cycle']==root['cycle']:
                context.update(event['context'])
                return
        raise ConfigurationError('Captured repair context is missing; workflow cannot continue')

    def _current_panel(self,conn,root,definition,cycle):
        return [self._rows(conn,root,s.key,cycle)[0] for s in (*definition.reviewers,definition.verify)]

    def _stop(self,conn,root,phase,reason):
        conn.execute('UPDATE factory_workflow_roots SET phase=?,reason=? WHERE root_id=?',(phase,str(reason),root['root_id']))
        conn.execute("UPDATE tasks SET status='blocked',block_kind='needs_input',result=? WHERE id=?",(str(reason),root['root_id']))
        self._state.event(conn,root['root_id'],phase,dict(reason=str(reason),resume_phase=root['phase']))
        return self._state.read_root(conn,root['root_id'])

    def resume(self,conn,root_id,note,decisions=None,reevaluate=False):
        if not isinstance(note,str) or not note.strip() or len(note)>2000:
            raise ConfigurationError('A short recovery decision is required')
        with self._board.write_txn(conn):
            root=self._state.read_root(conn,root_id)
            if root and root['definition'].get('execution_version', 1) == 2:
                from .project_controller import ProjectController
                ProjectController(self).resume(conn, root, note, decisions, reevaluate)
                return self.reconcile(conn, root_id)
            if decisions:
                raise ConfigurationError('Waivers and constraints are supported only by v2 project workflows')
            if not root or root['phase']!='blocked':
                raise ConfigurationError('Only blocked infrastructure stages can be retried; a different workflow requires a new task')
            event=conn.execute("SELECT document FROM factory_workflow_events WHERE root_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(root_id,)).fetchone()
            phase=json.loads(event[0])['resume_phase']
            candidates=conn.execute("SELECT s.*,t.status FROM factory_workflow_stages s JOIN tasks t ON t.id=s.task_id WHERE s.root_id=? AND s.cycle=? AND t.status IN ('blocked','done')",(root_id,root['cycle'])).fetchall()
            rows=[]
            kinds={'preparing':('prepare',),'implementing':('implement',),'repairing':('repair',),'reviewing':('review','verify')}[phase]
            for candidate in candidates:
                stage=dict(candidate)
                if stage['kind'] not in kinds or self._rows(conn,root,stage['stage_key'])[0]['task_id']!=stage['task_id']:
                    continue
                result=self._result(conn,stage) if stage['status']=='done' else None
                if stage['status']=='blocked' or (result and result.valid and result.metadata['verdict']=='BLOCKED'):
                    rows.append(stage)
            if not rows:
                raise ConfigurationError('No blocked worker stage is available to retry')
            for stage in rows:
                task_id=stage['task_id']
                conn.execute("UPDATE tasks SET status='ready',block_kind=NULL,current_run_id=NULL,completed_at=NULL,result=NULL,consecutive_failures=0 WHERE id=?",(task_id,))
                conn.execute('UPDATE factory_workflow_stages SET active_run_id=NULL,accepted_run_id=NULL WHERE task_id=?',(task_id,))
                self._board._append_event(conn,task_id,'workflow_retry',dict(note=note,previous_run_id=stage['active_run_id']))
            conn.execute("UPDATE factory_workflow_roots SET phase=?,reason='' WHERE root_id=?",(phase,root_id))
            self._state.event(conn,root_id,'human_resume',dict(note=note,phase=phase))
            self._board._append_event(conn,root_id,'workflow_resumed',dict(note=note))
        return self.reconcile(conn,root_id)
