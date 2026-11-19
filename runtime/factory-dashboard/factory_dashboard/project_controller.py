"""Restart-safe two-level Factory execution over the existing guarded board API."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import time

from .model_policy import ConfigurationError
from .project_cards import (ARCHITECT, COMPARISON, CONFLICT_CHECK, SIMILARITY, DIRECTOR, PLAN_DEFECT, PLAN_REVIEW, REPLAN, RETRO, SCOPE,
                            SPEC_CONSTRAINTS, TOOL_INCIDENTS, project_card)
from .project_decisions import (constraints_of, normalize_decisions, preserved_conflict, record_applied, relevant_constraints,
                                validate_plan_constraints, validate_spec_conflicts)
from .project_evidence import plan_evidence, retained_json, validate_comparison, validate_similarity
from .project_policy import (MAX_REPLANS, blocking_findings, finding_ac, planning_profiles, route_findings, rereview_profiles,
                             review_profiles, scope_additions, validate_plan, validate_scope)

REPAIR_LIMIT = 'Captured repair limit reached'
MAX_HANDOFF_RETRIES = 2
# Worker-side formatting slips are retried; a missing or foreign run is about who completed the stage, never the worker's formatting.
NOT_RETRYABLE = ('Missing or stale completed worker run', 'Worker ownership evidence is missing')
from .tool_incidents import tool_blockers
from .workflow_gate import evaluate_cycle
from .workflow_guards import controller_scope
from .workflow_handoffs import VERDICTS
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
        if project.get('awaiting') and not project.get('terminal'):
            # A pause for a human decision, not a failure: no retro, nothing retired.
            return self._controller._stop(conn, root, 'blocked', 'Awaiting human approval of the art-director plan: ' + project['awaiting']['path'])
        return self._state.read_root(conn, root['root_id'])

    def _save(self, conn, root, project):
        conn.execute('INSERT INTO factory_project_execution VALUES(?,?) ON CONFLICT(root_id) DO UPDATE SET document=excluded.document',
                     (root['root_id'], json.dumps(project, sort_keys=True, allow_nan=False)))

    def _node(self, conn, root, definition, context, project, key, kind, profile, instructions, inputs, *, task=None, cycle=0):
        from .workflow_templates import GAME_ART, GAME_AUDIO
        original = instructions
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
            tries = project.setdefault('handoff_retries', {}).get(token, 0)
            if result.reason in NOT_RETRYABLE or tries >= MAX_HANDOFF_RETRIES:
                raise ConfigurationError(result.reason + ': ' + key)
            # A malformed handoff is a worker slip, not a failed milestone: retry only this stage, telling the worker exactly what to fix.
            project['handoff_retries'][token] = tries + 1
            project.setdefault('handoff_rejections', {})[key] = self._rejection(conn, row, result, kind, key, cycle, root, tries + 1)
            project.setdefault('retry_keys', []).append(token)
            self._state.event(conn, root['root_id'], 'handoff_rejected', dict(key=key, task_id=row['task_id'], reason=result.reason, attempt=tries + 1))
            return self._node(conn, root, definition, context, project, key, kind, profile, original, [*inputs, row['task_id']], task=task, cycle=cycle)
        if result.metadata['verdict'] == 'BLOCKED':
            blocked = dict(key=key, profile=profile, task_id=row['task_id'], run_id=result.run_id, cycle=cycle,
                           verdict='BLOCKED', artifacts=result.metadata.get('artifacts', []), reason=result.metadata.get('blocked_reason', key))
            if not any(h.get('task_id') == row['task_id'] and h.get('run_id') == result.run_id for h in project['history']):
                project['history'].append(blocked)
                self._state.event(conn, root['root_id'], 'project_stage_blocked', blocked)
            if result.metadata.get('spec_conflicts'):
                raise ProjectBlocked('Specification conflict reported by ' + profile + ': ' + result.metadata.get('blocked_reason', key)
                                     + ' [' + ', '.join(c['constraint'] for c in result.metadata['spec_conflicts']) + ']. A human must decide.')
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

    def _rejection(self, conn, row, result, kind, key, cycle, root, attempt):
        """What a retried worker is told: the exact reason, the required identity/schema, and the valid part of what it sent."""
        kept = {}
        try:
            run = self._board.get_run(conn, row.get('active_run_id'))
            sent = getattr(run, 'metadata', None) or {}
            kept = {k: v for k, v in sent.items() if k not in ('artifacts', 'worker_session_id')} if isinstance(sent, dict) else {}
            if len(json.dumps(kept, default=str)) > 4000:
                kept = {k: v for k, v in kept.items() if k in ('contract', 'workflow_contract', 'root', 'stage_key', 'cycle', 'stage', 'verdict', 'manifest_sha12', 'ac_ids', 'ac_results')}
        except Exception:
            kept = {}
        required = dict(contract='factory-worker/v2', workflow_contract='factory-workflow/v1', root=root['root_id'], stage_key=key,
                        cycle=cycle + 1, verdict='one of ' + ' | '.join(VERDICTS[kind]))
        return dict(attempt=attempt, max_attempts=MAX_HANDOFF_RETRIES, rejected_task=row['task_id'], reason=result.reason, required_identity=required,
                    instruction='Resubmit the handoff with the missing or wrong fields corrected. Keep what was valid; redo work only if the reason requires it. '
                                'Prior attachments are readable from the rejected task.', previous_valid_metadata=kept)

    @staticmethod
    def _inputs(project):
        return [p['task_id'] for p in project['plans']]

    @staticmethod
    def _current(project):
        if project['mode'] == 'integration':
            return project['integration']
        done = {t['id'] for t in project['completed']}
        return next((t for t in project['tasks'] if t['id'] not in done), None)

    @staticmethod
    def _prefix(project, task):
        # A replanned task may reuse an ID; '.' cannot occur in task IDs, so generations never share stage keys.
        gen = project.get('gen', 0)
        return 'task-' + task['id'] + (f'.g{gen}' if gen else '')

    @staticmethod
    def _panel(selected, task, work):
        """Reviewers for this cycle. Final integration always gets the complete panel on the delivered manifest."""
        integration = task['id'] == 'integration'
        profiles = review_profiles(task['needs'], selected, integration or task.get('risk') == 'high')
        scoped = None if integration else work.get('panel')
        return [p for p in profiles if p in scoped] if scoped else profiles

    @staticmethod
    def _defect(results):
        return next((r.metadata['plan_defect'].strip() for r in results
                     if isinstance(r.metadata.get('plan_defect'), str) and r.metadata['plan_defect'].strip()), None)

    def _replan(self, conn, root, project, task, reason, findings, inputs):
        """Return the project to the architect. Bounded; completed tasks stay frozen."""
        if project.get('replans', 0) >= MAX_REPLANS:
            return False
        project.update(replans=project.get('replans', 0) + 1, gen=project.get('gen', 0) + 1, mode='planning',
                       replan=dict(reason=reason, task=task['id'] if task else None, findings=list(findings)[:15],
                                   inputs=list(dict.fromkeys(inputs))))
        project.pop('work', None)
        project.pop('integration', None)
        self._state.event(conn, root['root_id'], 'project_replan', project['replan'])
        project['history'].append(dict(replan=project['replans'], **project['replan']))
        return True

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
            captured = {p['profile'] for p in project['plans']}
            missing = [p for p in project['planners'] if p != 'architect' and p not in captured]
            if missing:
                # Directors only read the request and scope and write nothing shared, so they plan concurrently.
                inputs, progressed = self._inputs(project), False
                for profile in missing:
                    node = self._node(conn, root, definition, context, project, 'project-' + profile, 'prepare', profile, DIRECTOR, inputs,
                                      cycle=project.get('director_gen', {}).get(profile, 0))
                    if node:
                        project['plans'].append(plan_evidence(profile, node[0]['task_id'], node[1].metadata))
                        progressed = True
                return progressed
            art = next((p for p in project['plans'] if p['profile'] == 'art-director'), None)
            if art and project.get('approvals', {}).get('art-director', {}).get('sha256') != art['sha256']:
                # Visual direction is a human call: nothing is architected on an art plan nobody approved.
                if project.get('awaiting', {}).get('sha256') != art['sha256']:
                    project['awaiting'] = dict(profile='art-director', sha256=art['sha256'], path=art['path'], task_id=art['task_id'])
                    self._state.event(conn, root['root_id'], 'project_awaiting_human', project['awaiting'])
                return False
            gen, replan = project.get('gen', 0), project.get('replan')
            node = self._node(conn, root, definition, context, project, 'project-architect', 'prepare', 'architect',
                              ARCHITECT + ('\n' + REPLAN if replan else ''),
                              [*self._inputs(project), *(replan or {}).get('inputs', [])], cycle=gen)
            if not node:
                return False
            row, result = node
            added = scope_additions(result.metadata.get('scope_additions'), project['scope'])
            if added:
                # The orchestrator's choice is not final: the architect may widen it once, never narrow it.
                if project.get('scope_amended'):
                    raise ConfigurationError('Project scope can be amended only once')
                project['scope'] = {**project['scope'], **dict.fromkeys(added, True)}
                project.update(scope_amended=added, planners=planning_profiles(project['scope']))
                self._state.event(conn, root['root_id'], 'project_scope_amended', dict(added=added, scope=project['scope'], task_id=row['task_id']))
                if {'art', 'audio'} & set(added):
                    project['gen'] = gen + 1
                    return True
            evidence = plan_evidence('architect', row['task_id'], result.metadata)
            try:
                plan_document = retained_json(result.metadata['artifacts'], 'project-plan.json')
                tasks = validate_plan(plan_document, project['scope'], result.metadata['ac_ids'])
                plan_constraints = validate_plan_constraints(plan_document.get('constraints'))
            except ConfigurationError as exc:
                # A malformed plan goes back to the architect (bounded by MAX_REPLANS) instead of ending the run.
                if not self._replan(conn, root, project, None, 'Plan failed validation: ' + str(exc), ['architect:F1|HIGH|-|' + str(exc).replace('|', '/') + '|Return a plan that passes validation'], [row['task_id']]):
                    raise
                return True
            previous = {t['id']: t for t in project['tasks']}
            if any(done['id'] != 'integration' and previous.get(done['id']) not in tasks for done in project['completed']):
                raise ConfigurationError('Replan changed a task that already passed')
            project['plans'] = [p for p in project['plans'] if p['profile'] != 'architect'] + [evidence]
            project.update(ac_ids=result.metadata['ac_ids'], tasks=tasks, plan_constraints=plan_constraints, mode='plan_review')
            self._state.event(conn, root['root_id'], 'project_plan_captured', dict(tasks=tasks, plans=project['plans'], generation=gen))
            return True
        if mode == 'plan_review':
            # The plan is the most expensive thing to get wrong, so it is reviewed before any task is written.
            gen = project.get('gen', 0)
            reviewer = next(s.profile for s in definition.reviewers if s.profile in ('claude-reviewer', 'codex-reviewer'))
            node = self._node(conn, root, definition, context, project, 'project-plan-review', 'prepare', reviewer, PLAN_REVIEW,
                              self._inputs(project), cycle=gen)
            if not node:
                return False
            row, result = node
            if not any(Path(p).name.startswith('PLAN-REVIEW') and Path(p).suffix == '.md' for p in result.metadata['artifacts']):
                raise ConfigurationError('Plan review did not retain PLAN-REVIEW.md')
            blocking = [reviewer + ':' + f for f in blocking_findings(result.metadata.get('findings', []))]
            if blocking:
                if not self._replan(conn, root, project, None, 'Plan review findings', blocking, [row['task_id']]):
                    raise ConfigurationError('Plan review findings remain after the replan limit')
                return True
            project.pop('replan', None)
            project['mode'] = 'tasks'
            self._state.event(conn, root['root_id'], 'project_plan_approved', dict(task_id=row['task_id'], reviewer=reviewer, generation=gen))
            return True
        if mode == 'tasks':
            task = self._current(project)
            if task is None:
                # A read-only verification is insufficient: the developer assembles the final project first.
                project['integration'] = dict(id='integration', title='Final project integration', owner='developer',
                    dependencies=[t['id'] for t in project['tasks']], acceptance={ac: 'Project PLAN.md: ' + ac for ac in project['ac_ids']}, needs=project['scope'])
                project['mode'] = 'integration'
                return True
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
        # Each repair agent receives only the findings routed to it, never the other agents' findings.
        mine = work.get('repair_findings', {}).get(work['repairs'][0]) if work['step'] == 'repairing' and work['repairs'] else None
        blocking = mine or work['blocking']
        context = {**context, 'scope': [f.split('|', 1)[0] for f in blocking] or list(task['acceptance']), 'blocking': blocking,
                   'baseline': work.get('manifest', 'none'), 'baseline_tgz': work.get('snapshot') or 'none',
                   'manifest': work.get('manifest', 'none')}
        prefix = self._prefix(project, task)
        if work['step'] in ('writing', 'repairing'):
            repair = work['step'] == 'repairing'
            profile = work['repairs'][0] if repair else task['owner']
            key = prefix + ('-repair-' + profile if repair else '-implement')
            instructions = ('Repair only the supplied findings. Preserve director intent and completed task outputs. '
                            'Do not change the approved plan to make a mismatch pass. ' if repair else '')
            instructions += 'Read every inherited plan and TASK acceptance criteria. Use the relevant production skill for assets. '
            instructions += 'Integrate required art and audio outputs; run applicable checks and rebuild the cumulative project manifest.'
            instructions += ('\nIf a test, build or gate fails, including tests you just wrote, diagnose it and fix the test or the code, '
                             'then re-run, repeating until every gate you can run passes. A failure you can fix is never a reason for '
                             'VERDICT=BLOCKED; use BLOCKED only for a missing tool or capability you cannot provide. '
                             'The approved plan paths named in your card are your plan: read them there, and if you need the plan under '
                             'PROJECT_DIR/.factory copy it yourself. A plan attachment that looks missing is never a reason for BLOCKED.')
            instructions += '\n' + SPEC_CONSTRAINTS + '\n' + PLAN_DEFECT
            node = self._node(conn, root, definition, context, project, key, 'repair' if repair else 'implement', profile,
                              instructions, work['writer_inputs'], task=task, cycle=cycle)
            if not node:
                return False
            row, result = node
            defect = self._defect([result])
            if defect:
                if not self._replan(conn, root, project, task, 'Plan defect: ' + defect, work['blocking'], [row['task_id']]):
                    raise ConfigurationError('Plan defect reported after the replan limit: ' + defect)
                return True
            reported, expected = set(result.metadata['ac_ids']), set(task['acceptance'])
            # An implement writer reports every task AC. A repair writer may report fewer (the findings it repaired) or may also
            # name other known project ACs (task text often says "ac_status covers AC1..ACn"); an unknown ID or no task AC at all
            # is still rejected. The verifier re-checks every task AC either way.
            if (not reported or not reported <= set(project['ac_ids']) or not reported & expected) if repair else reported != expected:
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
        writer = self._scoped_writer(self._controller._result(conn, writer_row), task)
        if writer is None or not writer.valid or writer.metadata['manifest_sha12'] != work['manifest']:
            raise ConfigurationError('Captured writer evidence is no longer valid')
        inputs = list(dict.fromkeys([*self._inputs(project), *work['writer_inputs'], work['writer_task']]))
        # Verification is a prerequisite, not a parallel member of the review panel.
        node = self._node(conn, root, definition, context, project, prefix + '-verify', 'verify', 'verifier',
                          'Verify only TASK acceptance IDs against the exact cumulative manifest. Run tests, integration checks, asset lint gates and release audit. '
                          'Record repair_domains (code/art/audio) for failed asset or integration checks. Missing tools are environment gaps, never passes. '
                          'Never use inline interpreter flags such as python -c or node -e (the safety guard blocks them): read files with the file tools or run a script file. '
                          + TOOL_INCIDENTS + '\n' + SPEC_CONSTRAINTS + '\n' + PLAN_DEFECT,
                          inputs, task=task, cycle=cycle)
        if not node:
            return False
        verifier_row, verifier = node
        blockers = tool_blockers(verifier.metadata)
        if any(v == 'unverified:environment' for v in verifier.metadata['ac_results'].values()) or blockers:
            raise ProjectBlocked('Verification requires unavailable environment or tools' + (': ' + '; '.join(blockers) if blockers else ''))
        preliminary = evaluate_cycle(writer, [verifier], work.get('last_gate'), definition.max_repairs + work.get('extra_repairs', 0), cycle, {**context, 'unity_ci': False, 'waivers': project.get('waivers', [])})
        if preliminary.decision == 'repair' and not self._spec_check(conn, root, definition, context, project, task, work, cycle, prefix,
                                                                      [verifier], preliminary, [*inputs, verifier_row['task_id']]):
            return False
        if preliminary.decision != 'pass':
            return self._decision(conn, root, project, task, writer, [verifier], preliminary, [verifier_row], definition, reviewed=False)
        if verifier.metadata['verdict'] != 'PASS':
            raise ConfigurationError('Review requires an explicit successful verifier')
        work.update(step='reviewing', snapshot=verifier.metadata.get('snapshot'))
        profiles = self._panel([s.profile for s in definition.reviewers], task, work)
        readers, rows, waiting = [verifier], [verifier_row], False
        for profile in profiles:
            instructions = 'Review only your discipline against TASK acceptance and the inherited plans; report actionable findings.\n' + TOOL_INCIDENTS + '\n' + SPEC_CONSTRAINTS + '\n' + PLAN_DEFECT
            if profile == 'art-reviewer':
                instructions += '\n' + COMPARISON
            if profile == 'art-reviewer' and task['id'] != 'integration':
                instructions += '\n' + SIMILARITY
            selected = next((r.instructions for r in definition.reviewers if r.profile == profile), '')
            instructions += '\n' + selected
            node = self._node(conn, root, definition, context, project, prefix + '-' + profile, 'review', profile, instructions,
                              [*inputs, verifier_row['task_id']], task=task, cycle=cycle)
            if node is None:
                waiting = True
                continue
            row, result = node
            review_blockers = tool_blockers(result.metadata)
            if review_blockers:
                raise ProjectBlocked('Review requires unavailable tools: ' + profile + ': ' + '; '.join(review_blockers))
            # Below 80% the reviewer stops at the score, so there is no detailed comparison to validate.
            close_enough = profile != 'art-reviewer' or task['id'] == 'integration' or validate_similarity(result)
            if profile == 'art-reviewer' and close_enough:
                validate_comparison(profile, result, project['plans'], task['id'] == 'integration')
            readers.append(result)
            rows.append(row)
        if waiting:
            return False
        decision = evaluate_cycle(writer, readers, work.get('last_gate'), definition.max_repairs + work.get('extra_repairs', 0), cycle, {**context, 'unity_ci': False, 'waivers': project.get('waivers', [])})
        if decision.decision == 'repair' and not self._spec_check(conn, root, definition, context, project, task, work, cycle, prefix,
                                                                   readers, decision, [*inputs, verifier_row['task_id']]):
            return False
        return self._decision(conn, root, project, task, writer, readers, decision, rows, definition, reviewed=True)

    def _spec_check(self, conn, root, definition, context, project, task, work, cycle, prefix, readers, decision, inputs):
        """Before a repair is authorized: a finding that can only be fixed by breaking an approved requirement is a specification
        conflict for a human, never an implementation defect that spends repair budget. Returns False while the assessment is pending."""
        constraints = constraints_of(project)
        if not constraints:
            return True
        known = {c['id']: c for c in constraints}

        def conflict(reported, who):
            names = '; '.join(f"{c['constraint']} ({known[c['constraint']]['kind']}: {known[c['constraint']]['reason']}): {c['reason']}" for c in reported)
            record = dict(task=task['id'], cycle=cycle, by=who, conflicts=reported, blocking=list(decision.blocking))
            project['history'].append(dict(key=prefix + '-spec-conflict', verdict='SPEC_CONFLICT', **record))
            self._state.event(conn, root['root_id'], 'project_spec_conflict', record)
            raise ProjectBlocked('Specification conflict (' + who + '): ' + names + '. A human must decide: waive the finding, amend the requirement or change the plan.')

        for finding in decision.blocking:
            frozen = preserved_conflict(finding, constraints)
            if frozen:
                conflict([dict(constraint=frozen['id'], reason='the finding targets a path the plan fixed as unchanged: ' + finding, finding=finding)], 'controller')
        for reader in readers:
            reported = validate_spec_conflicts(reader.metadata)
            unknown = [c['constraint'] for c in reported if c['constraint'] not in known]
            if unknown:
                raise ConfigurationError('Reported conflict names an unknown constraint: ' + ', '.join(unknown))
            if reported:
                conflict(reported, reader.metadata.get('source_profile', 'reviewer'))
        relevant = {f: relevant_constraints(f, constraints) for f in decision.blocking}
        if not any(relevant.values()):
            return True
        assessor = next(s.profile for s in definition.reviewers if s.profile in ('claude-reviewer', 'codex-reviewer'))
        shown = {c['id']: c for found in relevant.values() for c in found}
        text = (CONFLICT_CHECK + '\nFINDINGS ' + json.dumps(list(decision.blocking), sort_keys=True)
                + '\nCONSTRAINTS ' + json.dumps([{k: v for k, v in c.items() if k in ('id', 'kind', 'reason', 'preserve', 'paths', 'colors', 'rules', 'acs') and v}
                                                  for c in shown.values()], sort_keys=True))
        node = self._node(conn, root, definition, context, project, prefix + '-conflict-check', 'review', assessor, text, inputs, task=task, cycle=cycle)
        if node is None:
            return False
        _, result = node
        reported = validate_spec_conflicts(result.metadata)
        unknown = [c['constraint'] for c in reported if c['constraint'] not in shown]
        if unknown:
            raise ConfigurationError('Conflict assessment names a constraint outside the question: ' + ', '.join(unknown))
        if reported:
            conflict(reported, 'conflict-check:' + assessor)
        return True

    def _decision(self, conn, root, project, task, writer, readers, decision, rows, definition, reviewed):
        work = project['work']
        record = dict(task=task['id'], cycle=work['cycle'], **asdict(decision))
        self._state.event(conn, root['root_id'], 'project_gate', record)
        project['history'].append(record)
        for audit in record_applied(project, decision.waived, task['id'], work['cycle']):
            self._state.event(conn, root['root_id'], 'project_waiver_applied', audit)
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
                del project['work']
            return True
        defect = self._defect(readers)
        exhausted = decision.decision == 'human_review' and decision.reason == REPAIR_LIMIT
        if exhausted or (defect and decision.decision == 'repair'):
            # Patching symptoms of a wrong plan never converges: escalate to the architect before a human.
            reason = 'Plan defect: ' + defect if defect else 'Repairs did not converge within the captured limit'
            if not self._replan(conn, root, project, task, reason, decision.blocking, [work['writer_task'], *[r['task_id'] for r in rows]]):
                self._terminal(conn, root, project, 'human_review', decision.reason if exhausted else reason + ' (replan limit reached)')
            return True
        if decision.decision == 'repair':
            # Only readers that reported a failure ask for repair domains; a passing verifier's leftover domain must not summon an agent.
            domains = [d for reader in readers if reader.metadata.get('verdict') not in ('PASS', 'NO_BLOCKING_FINDINGS')
                       for d in reader.metadata.get('repair_domains', [])]
            integration = task['id'] == 'integration'
            # Integration failures belong to whoever produced the failing acceptance criterion, not to a default fixer.
            ac_owners = {ac: sorted({t['owner'] for t in project['tasks'] if ac in t['acceptance']}) for ac in project['ac_ids']} if integration else None
            # A repair that would change a path the approved plan or the human froze is a decision, not a task to dispatch.
            frozen = constraints_of(project)
            for finding in decision.blocking:
                constraint = preserved_conflict(finding, frozen)
                if constraint:
                    raise ProjectBlocked('Repair conflicts with an approved constraint (' + constraint['reason'] + '): ' + finding
                                         + '. A human must waive this finding for that path or amend the plan.')
            routes = route_findings(decision.blocking, task['owner'], domains, ac_owners)
            profiles = list(routes)
            allowed = {'fixer', *(['artist'] if project['scope']['art'] else []), *(['sound-designer'] if project['scope']['audio'] else [])}
            if not set(profiles) <= allowed:
                raise ConfigurationError('Repair expands the captured project scope')
            panel = attribution = None
            if integration:
                attribution = {ac: [t['id'] for t in project['tasks'] if ac in t['acceptance']]
                               for ac in sorted({finding_ac(f) for f in decision.blocking} - {None})}
            else:
                # Re-review only what the repair touches. Reviews that never ran stay owed.
                full = self._panel([s.profile for s in definition.reviewers], task, {})
                owed = [] if reviewed else work.get('panel') if work.get('reviewed') else None
                if owed is not None:
                    wanted = {*owed, *rereview_profiles(full, decision.blocking, profiles)}
                    panel = [p for p in full if p in wanted] or None
                work['reviewed'] = bool(reviewed or work.get('reviewed'))
            record.update(repairs=list(profiles), rereview=panel or 'all', attribution=attribution)
            self._state.event(conn, root['root_id'], 'project_repair_routed', dict(task=task['id'], cycle=work['cycle'],
                              repairs=list(profiles), rereview=panel or 'all', attribution=attribution))
            work.update(panel=panel, attribution=attribution)
            work.update(step='repairing', cycle=work['cycle']+1, blocking=list(decision.blocking), repairs=profiles, repair_findings=routes,
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

    @staticmethod
    def _scoped_writer(writer, task):
        """A repair writer's evidence covers the task's acceptance IDs, whatever extra or fewer IDs it listed; the gate then compares
        it with the verifier's results for exactly the task's criteria. The IDs it reported are kept for the record."""
        if writer is None or not writer.valid or writer.kind != 'repair':
            return writer
        expected = sorted(task['acceptance'])
        if sorted(writer.metadata['ac_ids']) == expected:
            return writer
        return replace(writer, metadata={**writer.metadata, 'ac_ids': expected, 'ac_ids_reported': list(writer.metadata['ac_ids'])})

    def _repair_done(self, conn, root, prefix, work):
        rows = self._controller._rows(conn, root, prefix + '-repair-' + work['repairs'][0], work['cycle'])
        return bool(rows) and rows[0]['accepted_run_id'] is not None

    def resume(self, conn, root, note, decisions=None, reevaluate=False):
        # Validate a human decision before anything changes; an invalid one leaves the project exactly as it was.
        decided = normalize_decisions(decisions, note)
        row = conn.execute('SELECT document FROM factory_project_execution WHERE root_id=?', (root['root_id'],)).fetchone()
        project = json.loads(row[0]) if row else {}
        if decided['extra_repairs'] and 'work' not in project:
            raise ConfigurationError('extra_repairs applies to a task in progress; none is')
        awaiting = project.get('awaiting')
        if decisions and awaiting and not project.get('terminal'):
            raise ConfigurationError('Waivers and constraints apply to a blocked stage, not to plan approval')
        if root['phase'] == 'blocked' and awaiting and not project.get('terminal'):
            # The note is the decision: 'REJECT: <feedback>' returns the plan to the director, anything else approves it.
            profile, text = awaiting['profile'], note.strip()
            rejected = text.upper().startswith('REJECT:')
            if rejected and not text[7:].strip():
                raise ConfigurationError('A rejection requires feedback for the director')
            del project['awaiting']
            if rejected:
                project['plans'] = [p for p in project['plans'] if p['profile'] != profile]
                project.setdefault('director_feedback', {})[profile] = text[7:].strip()
                project.setdefault('director_gen', {})[profile] = project.get('director_gen', {}).get(profile, 0) + 1
            else:
                project.setdefault('approvals', {})[profile] = dict(sha256=awaiting['sha256'], note=text)
            self._save(conn, root, project)
            conn.execute("UPDATE factory_workflow_roots SET phase='project',reason='' WHERE root_id=?", (root['root_id'],))
            decision = dict(profile=profile, decision='rejected' if rejected else 'approved', sha256=awaiting['sha256'], note=text, execution_version=2)
            self._state.event(conn, root['root_id'], 'human_plan_decision', decision)
            self._board._append_event(conn, root['root_id'], 'workflow_resumed', dict(note=note))
            return
        stopped = ('blocked', 'human_review') if reevaluate else ('blocked',)
        if root['phase'] not in stopped or project.get('terminal', {}).get('phase') not in stopped:
            raise ConfigurationError('Only an infrastructure-blocked project can resume; changed scope requires a new task')
        project.update(mode=project['resume_mode'], active_keys=[], recoveries=project.get('recoveries', 0)+1, recovery_note=note)
        project.pop('terminal', None);project.pop('retro', None)
        known = {w['id'] for w in project.setdefault('waivers', [])}
        project['waivers'].extend(w for w in decided['waivers'] if w['id'] not in known)
        project.setdefault('constraints', []).extend(c for c in decided['constraints'] if c['id'] not in {k['id'] for k in project['constraints']})
        if decided['extra_repairs']:
            # Granted to the task in progress only: it lives in that task's work record and disappears with it.
            project['work']['extra_repairs'] = project['work'].get('extra_repairs', 0) + decided['extra_repairs']
        if decisions:
            self._state.event(conn, root['root_id'], 'human_decision', dict(note=note, waivers=[w['id'] for w in decided['waivers']],
                              constraints=decided['constraints'], extra_repairs=decided['extra_repairs'], execution_version=2))
        gen = project.get('gen', 0)
        if 'work' in project:
            work = project['work']
            task = self._current(project)
            prefix = self._prefix(project, task)
            if reevaluate and not decisions:
                # Judge the evidence that already exists again under the current rules: no stage is retried or repeated.
                project['retry_keys'] = []
            elif decisions and work['step'] == 'repairing' and work['repairs'] and work['cycle'] > 0 and not self._repair_done(conn, root, prefix, work):
                # The repairs were dispatched against findings the decision may have changed: retire the stalled repair and
                # judge the evidence that already exists again, instead of repeating verification or review work. The stalled card is left
                # on the board (blocked, harmless): archiving needs its own transaction, which this one already holds.
                work.update(step='reviewing', cycle=work['cycle'] - 1, repairs=[])
                work.pop('repair_findings', None)
                project['retry_keys'] = []
            elif work['step'] in ('verifying', 'reviewing'):
                work['step'] = 'verifying'
                keys = [prefix + '-verify', *[prefix + '-' + p for p in self._panel([s['profile'] for s in root['definition']['reviewers']], task, work)]]
                project['retry_keys'] = [f'{key}:{work["cycle"]}' for key in keys]
            else:
                profile = work['repairs'][0] if work['step'] == 'repairing' else task['owner']
                key = prefix + ('-repair-' + profile if work['step'] == 'repairing' else '-implement')
                project['retry_keys'] = [f'{key}:{work["cycle"]}']
        elif project['mode'] == 'scope':
            project['retry_keys'] = ['project-scope:0']
        elif project['mode'] == 'plan_review':
            project['retry_keys'] = [f'project-plan-review:{gen}']
        elif project['mode'] == 'planning':
            captured = {p['profile'] for p in project['plans']}
            missing = [p for p in project['planners'] if p != 'architect' and p not in captured]
            project['retry_keys'] = [f"project-{p}:{project.get('director_gen', {}).get(p, 0)}" for p in missing] or [f'project-architect:{gen}']
        else:
            project['retry_keys'] = []
        self._save(conn, root, project)
        conn.execute("UPDATE factory_workflow_roots SET phase='project',reason='' WHERE root_id=?", (root['root_id'],))
        self._state.event(conn, root['root_id'], 'human_resume', dict(note=note, execution_version=2))
        self._board._append_event(conn, root['root_id'], 'workflow_resumed', dict(note=note))
