"""Restart-safe two-level Factory execution over the existing guarded board API."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from .model_policy import ConfigurationError
from .project_cards import ARCHITECT, COMPARISON, DIRECTOR, RETRO, SCOPE, project_card
from .project_evidence import plan_evidence, retained_json, validate_comparison
from .project_policy import planning_profiles, repair_profiles, review_profiles, validate_plan, validate_scope
from .workflow_gate import evaluate_cycle
from .workflow_guards import controller_scope
from .workflow_types import StageSpec


class ProjectBlocked(ConfigurationError):
    """Recoverable missing environment; requires an explicit human recovery note."""


class ProjectController:
    def __init__(self, controller):
        self._controller = controller
        self._board = controller._board
        self._state = controller._state

    def reconcile(self, conn, root, definition):
        conn.execute('CREATE TABLE IF NOT EXISTS factory_project_execution(root_id TEXT PRIMARY KEY,document TEXT NOT NULL)')
        row = conn.execute('SELECT document FROM factory_project_execution WHERE root_id=?', (root['root_id'],)).fetchone()
        project = json.loads(row[0]) if row else dict(mode='scope', plans=[], tasks=[], completed=[], history=[], active_keys=[])
        task = self._board.get_task(conn, root['root_id'])
        if not task or task.status == 'archived':
            return self._controller._stop(conn, root, 'blocked', 'Project root is unavailable or archived')
        context = self._controller._context(task)
        if not context['project_dir']:
            return self._controller._stop(conn, root, 'blocked', 'Project requires an absolute directory')
        conn.execute("UPDATE factory_workflow_roots SET phase='project' WHERE root_id=?", (root['root_id'],))
        root['phase'] = 'project'
        try:
            # Advance completed nodes within this transaction; never launch providers here.
            for _ in range(100):
                if not self._advance(conn, root, definition, context, project):
                    break
            else:
                raise ConfigurationError('Project transition limit exceeded')
        except (ConfigurationError, OSError, ValueError) as exc:
            self._terminal(conn, root, project, 'blocked' if isinstance(exc, ProjectBlocked) else 'human_review', str(exc))
            self._retro(conn, root, definition, context, project)
        self._save(conn, root, project)
        self._state.mark_reconciled(conn, root['root_id'])
        return self._state.read_root(conn, root['root_id'])

    def _save(self, conn, root, project):
        conn.execute('INSERT INTO factory_project_execution VALUES(?,?) ON CONFLICT(root_id) DO UPDATE SET document=excluded.document',
                     (root['root_id'], json.dumps(project, sort_keys=True, allow_nan=False)))

    def _node(self, conn, root, definition, context, project, key, kind, profile, instructions, inputs, *, task=None, cycle=0):
        from .workflow_templates import GAME_ART, GAME_AUDIO
        for owner, notes in [('artist', GAME_ART), ('sound-designer', GAME_AUDIO)]:
            if profile == owner:
                instructions += '\n' + notes['repair' if kind == 'repair' else 'implement']
        if kind == 'verify' and task:
            for domain, notes in [('art', GAME_ART), ('audio', GAME_AUDIO)]:
                if task['needs'][domain]:
                    instructions += '\n' + notes['verify']
        for spec in (definition.prepare, definition.implement, definition.verify, definition.repair):
            if spec.profile == profile and spec.kind == kind:
                extra = spec.instructions
                if profile in ('art-director', 'audio-director'):
                    # Replace the legacy asset-only preflight, preserving captured custom guidance.
                    extra = extra.replace(GAME_ART['prepare'], '').replace(GAME_AUDIO['prepare'], '')
                instructions += '\n' + extra
        rows = self._controller._rows(conn, root, key, cycle)
        token = f'{key}:{cycle}'
        if token not in project['active_keys']:
            project['active_keys'].append(token)
        retry_requested = token in project.get('retry_keys', [])
        if not rows or retry_requested:
            retry = rows[0]['evidence_retry'] + 1 if rows else 0
            stage = StageSpec(key, kind, profile, instructions)
            self._save(conn, root, project)
            card = project_card(definition, stage, cycle, context, list(dict.fromkeys(inputs)), project, task)
            if retry:
                card['idempotency_key'] += '-r' + str(retry+1)
            with controller_scope(conn, root['root_id'], stage, cycle, retry):
                tid = self._board.create_task(conn, **card)
            if retry_requested:
                project['retry_keys'].remove(token)
            self._state.event(conn, root['root_id'], 'stage_created', dict(task_id=tid, key=key, profile=profile, cycle=cycle, execution_version=2))
            return None
        row = rows[0]
        result = self._controller._result(conn, row)
        if result is None:
            task_row = self._board.get_task(conn, row['task_id'])
            if not task_row or task_row.status in ('blocked', 'triage', 'archived'):
                raise ProjectBlocked('Project stage requires intervention: ' + key)
            return None
        if not result.valid:
            raise ConfigurationError(result.reason + ': ' + key)
        if result.metadata['verdict'] == 'BLOCKED':
            blocked = dict(key=key, profile=profile, task_id=row['task_id'], run_id=result.run_id, cycle=cycle,
                           verdict='BLOCKED', artifacts=result.metadata.get('artifacts', []), reason=result.metadata.get('blocked_reason', key))
            if not any(h.get('task_id') == row['task_id'] and h.get('run_id') == result.run_id for h in project['history']):
                project['history'].append(blocked)
                self._state.event(conn, root['root_id'], 'project_stage_blocked', blocked)
            raise ProjectBlocked('Stage blocked: ' + result.metadata.get('blocked_reason', key))
        self._controller._accept(conn, row, result)
        project['active_keys'].remove(token)
        history = dict(key=key, profile=profile, task_id=row['task_id'], run_id=result.run_id, cycle=cycle,
                       verdict=result.metadata['verdict'], manifest=result.metadata.get('manifest_sha12'),
                       findings=result.metadata.get('findings', []), failed_checks=result.metadata.get('failed_checks', []),
                       artifacts=result.metadata.get('artifacts', []))
        if not any(h.get('task_id') == row['task_id'] and h.get('run_id') == result.run_id for h in project['history']):
            project['history'].append(history)
            self._state.event(conn, root['root_id'], 'project_stage_accepted', history)
        return row, result

    @staticmethod
    def _inputs(project):
        return [p['task_id'] for p in project['plans']]

    def _advance(self, conn, root, definition, context, project):
        mode = project['mode']
        if mode == 'retro':
            return self._retro(conn, root, definition, context, project)
        if mode == 'finished':
            return False
        if mode == 'scope':
            node = self._node(conn, root, definition, context, project, 'project-scope', 'prepare', 'factory-orchestrator', SCOPE, [])
            if not node:
                return False
            row, result = node
            scope = validate_scope(result.metadata.get('project_scope'))
            for task_type, domain in [('art', 'art'), ('audio', 'audio')]:
                if definition.task_type == task_type and not scope[domain]:
                    raise ConfigurationError('Scope contradicts the submitted asset task type')
            project.update(scope=scope, scope_task=row['task_id'], planners=planning_profiles(scope), mode='planning', ac_ids=result.metadata['ac_ids'])
            project['plans'].append(plan_evidence('factory-orchestrator', row['task_id'], result.metadata))
            return True
        if mode == 'planning':
            index = len(project['plans']) - 1
            profile = project['planners'][index]
            node = self._node(conn, root, definition, context, project, 'project-' + profile, 'prepare', profile,
                              ARCHITECT if profile == 'architect' else DIRECTOR, self._inputs(project))
            if not node:
                return False
            row, result = node
            project['plans'].append(plan_evidence(profile, row['task_id'], result.metadata))
            if profile == 'architect':
                project['ac_ids'] = result.metadata['ac_ids']
                project['tasks'] = validate_plan(retained_json(result.metadata['artifacts'], 'project-plan.json'), project['scope'], project['ac_ids'])
                project.update(mode='tasks', index=0)
                self._state.event(conn, root['root_id'], 'project_plan_captured', dict(tasks=project['tasks'], plans=project['plans']))
            return True
        if mode == 'tasks':
            if project['index'] == len(project['tasks']):
                # A read-only verification is insufficient: the developer assembles the final project first.
                project['integration'] = dict(id='integration', title='Final project integration', owner='developer',
                    dependencies=[t['id'] for t in project['tasks']], acceptance={ac: 'Project PLAN.md: ' + ac for ac in project['ac_ids']}, needs=project['scope'])
                project['mode'] = 'integration'
                return True
            task = project['tasks'][project['index']]
        else:
            task = project['integration']
        if 'work' not in project:
            if not set(task['dependencies']) <= {t['id'] for t in project['completed']}:
                raise ConfigurationError('Task dependencies have not passed their complete Factory cycles')
            project['work'] = dict(step='writing', cycle=0, blocking=[], writer_inputs=[*self._inputs(project),
                *[t['evidence_task'] for t in project['completed'] if t['id'] in task['dependencies']]], repairs=[])
        return self._work(conn, root, definition, context, project, task)

    def _work(self, conn, root, definition, context, project, task):
        work = project['work']
        cycle = work['cycle']
        context = {**context, 'scope': [f.split('|', 1)[0] for f in work['blocking']] or list(task['acceptance']), 'blocking': work['blocking'],
                   'baseline': work.get('manifest', 'none'), 'baseline_tgz': work.get('snapshot') or 'none',
                   'manifest': work.get('manifest', 'none')}
        prefix = 'task-' + task['id']
        if work['step'] in ('writing', 'repairing'):
            repair = work['step'] == 'repairing'
            profile = work['repairs'][0] if repair else task['owner']
            key = prefix + ('-repair-' + profile if repair else '-implement')
            instructions = ('Repair only the supplied findings. Preserve director intent and completed task outputs. '
                            'Do not change the approved plan to make a mismatch pass. ' if repair else '')
            instructions += 'Read every inherited plan and TASK acceptance criteria. Use the relevant production skill for assets. '
            instructions += 'Integrate required art and audio outputs; run applicable checks and rebuild the cumulative project manifest.'
            node = self._node(conn, root, definition, context, project, key, 'repair' if repair else 'implement', profile,
                              instructions, work['writer_inputs'], task=task, cycle=cycle)
            if not node:
                return False
            row, result = node
            if set(result.metadata['ac_ids']) != set(task['acceptance']):
                raise ConfigurationError('Writer acceptance differs from the captured small-task plan')
            work.update(writer_key=key, writer_task=row['task_id'], manifest=result.metadata['manifest_sha12'])
            if repair:
                work['repairs'].pop(0)
                work['writer_inputs'].append(row['task_id'])
                if work['repairs']:
                    return True
            work['step'] = 'verifying'
            return True
        writer_row = self._controller._rows(conn, root, work['writer_key'], cycle)[0]
        writer = self._controller._result(conn, writer_row)
        if writer is None or not writer.valid or writer.metadata['manifest_sha12'] != work['manifest']:
            raise ConfigurationError('Captured writer evidence is no longer valid')
        inputs = list(dict.fromkeys([*self._inputs(project), *work['writer_inputs'], work['writer_task']]))
        # Verification is a prerequisite, not a parallel member of the review panel.
        node = self._node(conn, root, definition, context, project, prefix + '-verify', 'verify', 'verifier',
                          'Verify only TASK acceptance IDs against the exact cumulative manifest. Run tests, integration checks, asset lint gates and release audit. '
                          'Record repair_domains (code/art/audio) for failed asset or integration checks. Missing tools are environment gaps, never passes.',
                          inputs, task=task, cycle=cycle)
        if not node:
            return False
        verifier_row, verifier = node
        if any(v == 'unverified:environment' for v in verifier.metadata['ac_results'].values()) or verifier.metadata.get('blocked_tools'):
            raise ProjectBlocked('Verification requires unavailable environment or tools')
        preliminary = evaluate_cycle(writer, [verifier], work.get('last_gate'), definition.max_repairs, cycle, {**context, 'unity_ci': False})
        if preliminary.decision != 'pass':
            return self._decision(conn, root, project, task, writer, [verifier], preliminary, [verifier_row], definition)
        if verifier.metadata['verdict'] != 'PASS':
            raise ConfigurationError('Review requires an explicit successful verifier')
        work.update(step='reviewing', snapshot=verifier.metadata.get('snapshot'))
        profiles = review_profiles(task['needs'], [s.profile for s in definition.reviewers])
        readers, rows, waiting = [verifier], [verifier_row], False
        for profile in profiles:
            instructions = 'Review only your discipline against TASK acceptance and the inherited plans; report actionable findings.'
            if profile in ('art-reviewer', 'audio-reviewer'):
                instructions += '\n' + COMPARISON
            selected = next((r.instructions for r in definition.reviewers if r.profile == profile), '')
            instructions += '\n' + selected
            node = self._node(conn, root, definition, context, project, prefix + '-' + profile, 'review', profile, instructions,
                              [*inputs, verifier_row['task_id']], task=task, cycle=cycle)
            if node is None:
                waiting = True
                continue
            row, result = node
            if result.metadata.get('blocked_tools'):
                raise ProjectBlocked('Review requires unavailable tools: ' + profile)
            if profile in ('art-reviewer', 'audio-reviewer'):
                validate_comparison(profile, result, project['plans'], task['id'] == 'integration')
            readers.append(result)
            rows.append(row)
        if waiting:
            return False
        decision = evaluate_cycle(writer, readers, work.get('last_gate'), definition.max_repairs, cycle, {**context, 'unity_ci': False})
        return self._decision(conn, root, project, task, writer, readers, decision, rows, definition)

    def _decision(self, conn, root, project, task, writer, readers, decision, rows, definition):
        work = project['work']
        record = dict(task=task['id'], cycle=work['cycle'], **asdict(decision))
        self._state.event(conn, root['root_id'], 'project_gate', record)
        project['history'].append(record)
        if decision.decision == 'pass':
            verifier = next(r for r in readers if r.kind == 'verify')
            project['completed'].append(dict(id=task['id'], evidence_task=next(r['task_id'] for r in rows if r['kind'] == 'verify'),
                                             writer_task=work['writer_task'], manifest=work['manifest']))
            if task['id'] == 'integration':
                project['delivery'] = dict(outcome='LOCAL_DELIVERED', manifest_sha12=work['manifest'],
                    ac_results=verifier.metadata['ac_results'], snapshot=verifier.metadata.get('snapshot'),
                    snapshot_attached=verifier.metadata['snapshot_attached'], publish_commands=verifier.metadata['publish_commands'],
                    tasks=project['completed'], execution_version=2)
                self._terminal(conn, root, project, 'delivered', 'All tasks and final integration passed')
            else:
                project['index'] += 1
                del project['work']
            return True
        if decision.decision == 'repair':
            domains = [d for reader in readers for d in reader.metadata.get('repair_domains', [])]
            profiles = repair_profiles(decision.blocking, task['owner'], domains)
            allowed = {'fixer', *(['artist'] if project['scope']['art'] else []), *(['sound-designer'] if project['scope']['audio'] else [])}
            if not set(profiles) <= allowed:
                raise ConfigurationError('Repair expands the captured project scope')
            work.update(step='repairing', cycle=work['cycle']+1, blocking=list(decision.blocking), repairs=profiles,
                        writer_inputs=list(dict.fromkeys([*self._inputs(project), work['writer_task'], *[r['task_id'] for r in rows]])),
                        last_gate=asdict(decision))
            return True
        self._terminal(conn, root, project, decision.decision, decision.reason)
        return True

    def _terminal(self, conn, root, project, phase, reason):
        if project.get('terminal'):
            return
        project['resume_mode'] = project['mode']
        for token in project['active_keys']:
            key, cycle = token.rsplit(':', 1)
            for stage in self._controller._rows(conn, root, key, int(cycle))[:1]:
                task = self._board.get_task(conn, stage['task_id'])
                if task and task.status in ('ready', 'running'):
                    with controller_scope(conn, root['root_id']):
                        self._board.block_task(conn, task.id, reason='Project stopped: ' + reason,
                                               kind='needs_input', expected_run_id=task.current_run_id)
        project['terminal'] = dict(phase=phase, reason=reason)
        project['active_keys'] = []
        project['mode'] = 'retro'
        self._state.event(conn, root['root_id'], 'project_outcome', project['terminal'])

    def _retro(self, conn, root, definition, context, project):
        inputs = list(dict.fromkeys([h['task_id'] for h in project['history'] if 'task_id' in h]))
        try:
            key = 'project-retro' + ('-' + str(project['recoveries']) if project.get('recoveries') else '')
            node = self._node(conn, root, definition, context, project, key, 'prepare', 'factory-retro', RETRO, inputs)
            if not node:
                return False
            row, result = node
            if not any(Path(p).name.startswith('RETRO') and Path(p).suffix == '.md' for p in result.metadata['artifacts']):
                raise ConfigurationError('Retrospective did not retain RETRO.md')
            project['retro'] = dict(task_id=row['task_id'], artifacts=result.metadata['artifacts'])
        except ConfigurationError as exc:
            project['retro'] = dict(unavailable=str(exc))
            self._state.event(conn, root['root_id'], 'retro_unavailable', project['retro'])
        terminal = project['terminal']
        phase = terminal['phase']
        if 'unavailable' in project['retro'] and phase == 'delivered':
            phase = 'human_review'
            terminal = dict(phase=phase, reason=project['retro']['unavailable'])
        if phase == 'delivered':
            delivery = {**project['delivery'], 'project_dir': context['project_dir'], 'retro': project['retro']}
            with controller_scope(conn, root['root_id']):
                conn.execute("UPDATE tasks SET status='done',completed_at=?,result=?,block_kind=NULL WHERE id=?", (int(time.time()), json.dumps(delivery), root['root_id']))
            self._board._append_event(conn, root['root_id'], 'completed', delivery)
            conn.execute("UPDATE factory_workflow_roots SET phase='delivered',reason=? WHERE root_id=?", (terminal['reason'],root['root_id']))
        else:
            self._controller._stop(conn, root, phase if phase in ('blocked', 'human_review') else 'human_review', terminal['reason'])
        project.update(mode='finished', active_keys=[])
        return False

    def resume(self, conn, root, note):
        row = conn.execute('SELECT document FROM factory_project_execution WHERE root_id=?', (root['root_id'],)).fetchone()
        project = json.loads(row[0]) if row else {}
        if root['phase'] != 'blocked' or project.get('terminal', {}).get('phase') != 'blocked':
            raise ConfigurationError('Only an infrastructure-blocked project can resume; changed scope requires a new task')
        project.update(mode=project['resume_mode'], active_keys=[], recoveries=project.get('recoveries', 0)+1, recovery_note=note)
        project.pop('terminal', None);project.pop('retro', None)
        if 'work' in project:
            work = project['work']
            task = project['integration'] if project['mode'] == 'integration' else project['tasks'][project['index']]
            if work['step'] in ('verifying', 'reviewing'):
                work['step'] = 'verifying'
                keys = ['task-' + task['id'] + '-verify', *['task-' + task['id'] + '-' + p for p in review_profiles(task['needs'], [s['profile'] for s in root['definition']['reviewers']])]]
                project['retry_keys'] = [f'{key}:{work["cycle"]}' for key in keys]
            else:
                profile = work['repairs'][0] if work['step'] == 'repairing' else task['owner']
                key = 'task-' + task['id'] + ('-repair-' + profile if work['step'] == 'repairing' else '-implement')
                project['retry_keys'] = [f'{key}:{work["cycle"]}']
        else:
            profile = 'scope' if project['mode'] == 'scope' else project['planners'][len(project['plans'])-1]
            project['retry_keys'] = [f'project-{profile}:0']
        self._save(conn, root, project)
        conn.execute("UPDATE factory_workflow_roots SET phase='project',reason='' WHERE root_id=?", (root['root_id'],))
        self._state.event(conn, root['root_id'], 'human_resume', dict(note=note, execution_version=2))
        self._board._append_event(conn, root['root_id'], 'workflow_resumed', dict(note=note))
