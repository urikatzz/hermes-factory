"""Restart-safe two-level Factory execution over the existing guarded board API."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import re
import time

from .model_policy import ConfigurationError
from .project_cards import (ART_PLAN, ROLE_FINDINGS, APPROVED_COMPARISON, APPROVED_REFERENCES, INSPECTION, REFERENCE_AUDIT, VISUAL_TRACE, ARCHITECT, COMPARISON, CONFLICT_CHECK, SIMILARITY, DIRECTOR, PLAN_CORRECTION, PLAN_CORRECTION_REVIEW, PLAN_DEFECT,
                            PLAN_REVIEW, REPLAN, RETRO, SCOPE, SPEC_CONSTRAINTS, TOOL_INCIDENTS, project_card)
from .project_decisions import (constraint_view, constraints_of, normalize_decisions, preserved_conflict, record_applied, relevant_constraints,
                                validate_plan_constraints, validate_spec_conflicts)
from .project_evidence import dedupe_artifacts, plan_evidence, retained_json, validate_comparison, validate_similarity
from . import project_references as refs
from .project_policy import (MAX_ORCHESTRATION_RECOVERIES, MAX_PLAN_CORRECTIONS, MAX_REPLANS, blocking_findings, budget_used, finding_id,
                             missing_baseline_tokens, plan_architecture_diff, repair_origin, finding_ac, planning_profiles, route_findings, rereview_profiles,
                             review_profiles, scope_additions, validate_plan, validate_scope)

REPAIR_LIMIT = 'Captured repair limit reached'
MAX_HANDOFF_RETRIES = 2
# Scan candidates in plan prose have their own budget: a keyword match is not a worker slip and must not exhaust the retries meant for malformed handoffs.
MAX_SCAN_RETRIES = 3
# A plan that fails structural validation (missing fields, no numbered criteria, bad graph) is corrected by the architect with the exact
# errors; this never spends an architectural replan. Past the bound a human decides.
MAX_PLAN_VALIDATION_RETRIES = 2
PLAN_SCHEMA = ('project-plan.json: {"tasks":[{"id":"lowercase-id","title":"...","owner":"developer|artist|sound-designer","dependencies":["task-id"],'
               '"acceptance":{"AC1":"observable criterion"},"needs":{"art":false,"audio":false,"ui":false,"ux":false},"risk":"normal|high",'
               '"preserve":["optional path"],"visual":["optional approved visual requirement ids V1.."]}],"constraints":[optional structured constraints]}; every task needs numbered acceptance criteria (each criterion text at most 1000 characters) '
               '(AC1, AC2, ...); together the tasks cover every project AC; completed tasks stay byte-for-byte unchanged. A task id is lowercase letters, digits and hyphens only, starting with a letter, '
               'at most 24 characters (no underscores, no "t_" prefix). Every requirement id you list in a task\'s "visual" must also be written (for example "V2") in that same task\'s acceptance text, '
               'and every demanded requirement must be listed by at least one task.')
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
            return self._controller._stop(conn, root, 'blocked', 'Awaiting human approval of the art-director plan: ' + project['awaiting']['path'] + (' (mockup: ' + project['awaiting']['mockup'] + ')' if project['awaiting'].get('mockup') else '')
                                          + (' (' + str(len(project['awaiting'].get('explained') or [])) + ' flagged line(s) the director explained are listed in the awaiting record for you to judge)' if project['awaiting'].get('explained') else '') + '. Approve with the note "' + self._approval_phrase(root['root_id'], project) + '" or reject with "REJECT: <feedback>"; no other note approves.')
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
        approved = refs.authoritative(project.get('reference_records', [])) if key != 'project-scope' else []
        if approved:
            instructions += '\n' + APPROVED_REFERENCES
            if refs.must_inspect(profile, key):
                instructions += '\n' + INSPECTION + '\n' + ROLE_FINDINGS[refs.role_kind(profile, key)]
            if profile == 'art-director':
                instructions += '\n' + ART_PLAN
            if profile in ('architect', 'art-director'):
                instructions += '\n' + VISUAL_TRACE
            if key == refs.PLAN_REVIEW_KEY:
                instructions += '\n' + REFERENCE_AUDIT
        rows = self._controller._rows(conn, root, key, cycle)
        token = f'{key}:{cycle}'
        if token not in project['active_keys']:
            project['active_keys'].append(token)
        retry_requested = token in project.get('retry_keys', [])
        if not rows or retry_requested:
            if approved and refs.must_inspect(profile, key):
                # A stage that must look at the reference cannot be created for a profile that cannot open images.
                problem = refs.vision_problem(profile, self._hermes_home())
                if problem:
                    raise ProjectBlocked('Visual capability missing: ' + problem)
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
        if result.valid and isinstance(result.metadata.get('artifacts'), list):
            result.metadata['artifacts'] = dedupe_artifacts(result.metadata['artifacts'])
        reason = None if not result.valid else self._inspection_problem(conn, project, profile, key, result, context)
        if not result.valid or reason:
            reason = reason or result.reason
            scan = 'Scan candidates' in reason
            budget_key, limit = (token + ':scan', MAX_SCAN_RETRIES) if scan else (token, MAX_HANDOFF_RETRIES)
            tries = project.setdefault('handoff_retries', {}).get(budget_key, 0)
            if reason in NOT_RETRYABLE or tries >= limit:
                raise ConfigurationError(reason + ': ' + key)
            # A malformed handoff is a worker slip, not a failed milestone: retry only this stage, telling the worker exactly what to fix.
            project['handoff_retries'][budget_key] = tries + 1
            project.setdefault('orchestration_log', []).append(dict(kind='handoff_retry', key=key, attempt=tries + 1, reason=reason, at=int(time.time())))
            project.setdefault('handoff_rejections', {})[key] = self._rejection(conn, row, result, kind, key, cycle, root, tries + 1, reason, limit)
            project.setdefault('retry_keys', []).append(token)
            self._state.event(conn, root['root_id'], 'handoff_rejected', dict(key=key, task_id=row['task_id'], reason=reason, attempt=tries + 1))
            return self._node(conn, root, definition, context, project, key, kind, profile, original, [*inputs, row['task_id']], task=task, cycle=cycle)
        if result.metadata['verdict'] == 'BLOCKED' and not self._defect([result]):
            # A BLOCKED stage that declares a plan defect is not blocked work: it goes on to the architect (bounded replans).
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

    @staticmethod
    def _approval_phrase(root_id, project):
        """The exact words that approve the awaiting plan: bound to this root, the plan's hash and the approved-references digest."""
        awaiting = project['awaiting']
        return f"APPROVE {root_id} {awaiting['sha256'][:12]} {(awaiting.get('references_digest') or project.get('references_digest') or 'none')[:12]}"

    def _reference_plan_errors(self, project, context, document, tasks):
        """Reference-related plan problems (contradicting acceptance, traceability, an unamended bible), tolerant of a plan that also fails the schema check."""
        if tasks is None:
            raw = document.get('tasks') if isinstance(document, dict) else None
            tasks = [dict(id=str(t.get('id')), title=str(t.get('title', '')), owner=t.get('owner'), visual=t.get('visual') if isinstance(t.get('visual'), list) else [],
                          acceptance={str(k): str(v) for k, v in t['acceptance'].items()}) for t in (raw if isinstance(raw, list) else [])
                     if isinstance(t, dict) and isinstance(t.get('acceptance'), dict)]
        errors = []
        records = project['reference_records']
        texts = {'task ' + t['id']: t.get('title', '') + ': ' + '; '.join(t['acceptance'].values()) for t in tasks}
        carried = {'task ' + t['id']: [i for i in t.get('visual', []) if isinstance(i, str)] for t in tasks}
        clash = refs.find_contradictions(records, texts, carried)
        if clash:
            errors.append('Task acceptance contradicts, defers or replaces approved reference requirements: ' + self._describe(clash))
        errors += refs.traceability_errors(records, tasks, self._bible_contradictions(project, context))
        return errors

    @staticmethod
    def _open_candidates(project):
        """Explained scan candidates (director and architect prose) nobody has resolved yet."""
        resolved = set(project.get('scan_resolved', []))
        return [c for group in project.get('explained_candidates', {}).values() for c in group if c['id'] not in resolved]

    @staticmethod
    def _hermes_home():
        return refs.hermes_root(os.environ, Path.home() / '.hermes')

    @staticmethod
    def _describe(findings):
        return '; '.join(f"{c['requirement']} [{c['kind']}: '{c['keyword']}'] {c['document']}:{c['line']}: {c['text']}" for c in findings[:5])

    def _inspection_problem(self, conn, project, profile, key, result, context):
        """A stage that decides or judges visuals must prove it opened each approved reference image. None when satisfied or not required.

        Proof is the worker's own session log: a successful vision_analyze call on the exact reference file. A well-formed JSON file alone is not evidence."""
        records = project.get('reference_records', [])
        if not refs.authoritative(records) or not refs.must_inspect(profile, key) or result.metadata.get('verdict') == 'BLOCKED':
            return None
        try:
            try:
                inspection = refs.validate_inspection(retained_json(result.metadata['artifacts'], 'reference-inspection.json'), records)
            except ConfigurationError as exc:
                return 'Reference inspection rejected: ' + str(exc)
            try:
                run = self._board.get_run(conn, result.run_id)
                session = (getattr(run, 'metadata', None) or {}).get('worker_session_id')
            except Exception:
                session = None
            root = Path(context['project_dir'])
            wanted = {r['id']: root / r['path'] for r in refs.authoritative(records)}
            mockup = refs.plan_mockup(result.metadata['artifacts']) if profile == 'art-director' else None
            if mockup:
                wanted['plan-mockup'] = mockup
            try:
                absent = refs.vision_proof(profile, session, self._hermes_home(), wanted, scratch_ok={'plan-mockup'})
            except ConfigurationError as exc:
                # The log or the worker session is missing or unreadable: that is the factory's problem, not a worker slip. Stop for recovery; no worker retry is spent.
                raise ProjectBlocked('Image inspection cannot be verified for ' + profile + ' (' + str(exc) + '). This is an infrastructure fault, not a worker defect; recover and resume.') from exc
            if absent:
                return ('Reference inspection rejected: the worker session shows no successful vision_analyze call on ' + ', '.join(
                    f"{i} ({wanted[i]})" for i in absent) + '. Open each approved image with vision_analyze before describing it.')
            if profile == 'art-reviewer':
                shots = {Path(a).name: a for a in result.metadata['artifacts'] if Path(a).suffix.lower() in refs.IMAGE_SUFFIXES}
                if shots and len(refs.vision_proof(profile, session, self._hermes_home(), shots, scratch_ok=set(shots))) == len(shots):
                    return 'Reference inspection rejected: the worker session shows the reviewer never opened any of the rendered screenshots with vision_analyze.'
            kind = refs.role_kind(profile, key)
            images = [Path(a) for a in result.metadata['artifacts'] if Path(a).suffix.lower() in refs.IMAGE_SUFFIXES]
            tasks = []
            if kind == 'carry':
                tasks = [t for t in retained_json(result.metadata['artifacts'], 'project-plan.json').get('tasks', []) if isinstance(t, dict) and isinstance(t.get('id'), str)]
            elif kind == 'plan_check':
                tasks = project.get('tasks', [])
            try:
                refs.validate_role_findings(inspection, records, kind, tasks, [p.name for p in images], result.metadata.get('findings', []), result.metadata.get('verdict'))
            except ConfigurationError as exc:
                return 'Reference inspection rejected: ' + str(exc)
            if key == refs.PLAN_REVIEW_KEY:
                candidates = self._open_candidates(project)
                if candidates:
                    ruled = refs.validate_adjudication(retained_json(result.metadata['artifacts'], 'scan-adjudication.json'), candidates)
                    for entry in ruled:
                        if entry['verdict'] == 'contradiction' and not any(entry['id'] in f and f.split('|', 4)[1] in ('BLOCKER', 'HIGH') for f in result.metadata.get('findings', [])):
                            raise ConfigurationError('A contradiction ruling on ' + entry['id'] + ' needs a BLOCKER/HIGH finding naming that id')
            if profile == 'art-director':
                if not mockup:
                    raise ConfigurationError('The art plan has no representative mockup: retain plan-mockup.png (a PNG of at least 640x360) next to PLAN.md; it stays subordinate to the approved reference')
                plan_text = next((Path(a).read_text(errors='replace') for a in result.metadata['artifacts'] if Path(a).name == 'PLAN.md' or re.fullmatch(r'PLAN_[0-9]+\.md', Path(a).name)), '')
                refs.validate_art_plan(plan_text)
            if profile in ('art-director', 'architect'):
                plan = next((Path(a) for a in result.metadata['artifacts'] if Path(a).name == 'PLAN.md' or re.fullmatch(r'PLAN_[0-9]+\.md', Path(a).name)), None)
                text = plan.read_text(errors='replace') if plan and plan.is_file() else ''
                missing = [r['id'] for r in refs.required_requirements(records) if not re.search(r'\b' + re.escape(r['id']) + r'\b', text)]
                if missing:
                    raise ConfigurationError('PLAN.md does not carry approved visual requirement(s): ' + ', '.join(missing))
                clash = refs.find_contradictions(records, {profile + ' PLAN.md': text})
                unresolved, explained = refs.split_explained(clash, inspection.get('scan_explanations'))
                project.setdefault('explained_candidates', {})[profile] = explained
                if unresolved:
                    raise ConfigurationError('Scan candidates in PLAN.md: ' + self._describe(unresolved) + '. Reword each, or explain it in a top-level "scan_explanations" list of '
                                             '{"quote":"<15+ characters of the flagged text>","requirement_id":"V..","explanation":"<why it is not a contradiction, 40+ characters>"}. '
                                             'An explained candidate is shown to the human and ruled on by the plan reviewer; it is not dismissed.')
        except ProjectBlocked:
            raise
        except ConfigurationError as exc:
            return 'Approved-reference check rejected: ' + str(exc)
        return None

    def _refresh_references(self, project, context):
        """Load the approved references; they are frozen for the run: a changed image or references file needs a human."""
        loaded = refs.load_references(context['project_dir'])
        if loaded['problems']:
            raise ProjectBlocked('; '.join(loaded['problems']) + '. A human must re-approve the reference.')
        prior = project.get('references_digest')
        if prior and loaded['digest'] != prior:
            raise ProjectBlocked('Approved references changed during the run. A human must re-approve them (resume with a note) before work continues.')
        project['reference_records'] = loaded['references']
        project['references'] = refs.view(loaded['references'])
        project['references_digest'] = loaded['digest']
        project['references_source'] = loaded['source']
        return loaded['references']

    @staticmethod
    def _bible_contradictions(project, context):
        """The existing style bible against the approved references."""
        documents = {}
        for name in ('art/style/STYLE.md', 'art/style/style.json'):
            path = Path(context['project_dir']) / name
            if path.is_file():
                documents[name] = path.read_text(errors='replace')
        return refs.find_contradictions(project.get('reference_records', []), documents)

    def _rejection(self, conn, row, result, kind, key, cycle, root, attempt, reason=None, limit=MAX_HANDOFF_RETRIES):
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
        required = dict(contract='factory-worker/v2', workflow_contract='factory-workflow/v1', root=root['root_id'], stage_key=key, stage=key,
                        cycle=cycle + 1, verdict='one of ' + ' | '.join(VERDICTS[kind]))
        return dict(attempt=attempt, max_attempts=limit, rejected_task=row['task_id'], reason=reason or result.reason, required_identity=required,
                    instruction='Resubmit the handoff with the missing or wrong fields corrected. Keep what was valid; redo work only if the reason requires it. '
                                'Prior attachments are readable from the rejected task: read them there, write your files again under $HERMES_KANBAN_WORKSPACE in THIS run and list those new absolute paths in '
                                'kanban_complete(artifacts=[...]); never list paths from the rejected task or from any cache or scratch folder. '
                                'The first line of the summary must be exactly VERDICT=<verdict> STAGE=<the same value as metadata.stage> CYCLE=<metadata.cycle> MANIFEST=<metadata.manifest_sha12>.',
                    previous_valid_metadata=kept)

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

    @staticmethod
    def _plan_classes(project, result, blocking):
        """Each blocking plan-review finding is a localized correction or an architectural defect. A human decision classifies the current
        findings by id; otherwise the reviewer's own classification counts; anything unclassified is architectural."""
        reported = result.metadata.get('finding_classes') or {}
        override = project.get('plan_class_overrides') or {}
        human = set(override.get('ids', [])) if override.get('gen') == project.get('gen', 0) else set()
        return {finding_id(f): 'correction' if finding_id(f) in human else reported.get(finding_id(f), 'architectural') for f in blocking}

    def _plan_correction(self, conn, root, definition, context, project):
        """Bounded, targeted correction of the approved plan: it may change wording, metadata and constraints only. The correction is checked
        mechanically (structure, task architecture, original baselines) and then reviewed only for the findings and the requirements they touch."""
        correction, gen = project['correction'], project['correction']['gen']
        attempt, reviewer = correction['attempt'], next(s.profile for s in definition.reviewers if s.profile in ('claude-reviewer', 'codex-reviewer'))
        key = f'project-plan-correction-g{gen}'
        listing = '\nFINDINGS TO CORRECT ' + json.dumps(correction['findings'], sort_keys=True)
        if correction.get('optional'):
            listing += '\nNON-BLOCKING SUGGESTIONS (address where cheap) ' + json.dumps(correction['optional'], sort_keys=True)
        inputs = [*self._inputs(project), correction['review_task']]
        node = self._node(conn, root, definition, context, project, key, 'prepare', 'architect', PLAN_CORRECTION + listing, inputs, cycle=attempt)
        if not node:
            return False
        row, result = node
        try:
            document = retained_json(result.metadata['artifacts'], 'project-plan.json')
            tasks = validate_plan(document, project['scope'], result.metadata['ac_ids'])
            constraints = validate_plan_constraints(document.get('constraints'))
        except ConfigurationError as exc:
            return self._correction_failed(conn, root, project, correction, key, 'Corrected plan failed structural validation: ' + str(exc))
        if sorted(result.metadata['ac_ids']) != sorted(project['ac_ids']) or plan_architecture_diff(project['tasks'], tasks):
            changed = plan_architecture_diff(project['tasks'], tasks) or ['project acceptance IDs']
            raise ConfigurationError('Plan correction changed architecture or acceptance criteria (' + ', '.join(changed) + '): that needs an architectural replan or a human decision')
        evidence = plan_evidence('architect', row['task_id'], result.metadata)
        previous = next(p for p in project['plans'] if p['profile'] == 'architect')
        try:
            lost = missing_baseline_tokens(Path(previous['path']).read_text(), Path(evidence['path']).read_text())
        except OSError as exc:
            raise ConfigurationError('Cannot compare the corrected plan text with the approved plan: ' + str(exc))
        if lost:
            return self._correction_failed(conn, root, project, correction, key, 'Corrected plan dropped original integrity baselines (keep them, labelled as baseline): ' + ', '.join(lost[:8]))
        review = self._node(conn, root, definition, context, project, f'project-plan-correction-review-g{gen}', 'prepare', reviewer,
                            PLAN_CORRECTION_REVIEW + listing, [*inputs, row['task_id']], cycle=attempt)
        if not review:
            return False
        review_row, verdict = review
        if not any(Path(p).name.startswith('PLAN-REVIEW') and Path(p).suffix == '.md' for p in verdict.metadata['artifacts']):
            raise ConfigurationError('Focused plan review did not retain PLAN-REVIEW.md')
        defect = self._defect([verdict])
        if defect:
            raise ConfigurationError('Plan correction review found an architectural change: ' + defect)
        remaining = [reviewer + ':' + f for f in blocking_findings(verdict.metadata.get('findings', []))]
        if remaining:
            return self._correction_failed(conn, root, project, correction, key, 'The focused review found unresolved findings', remaining)
        project['plans'] = [p for p in project['plans'] if p['profile'] != 'architect'] + [evidence]
        project.update(plan_constraints=constraints, mode='tasks')
        project.pop('correction', None)
        project.pop('replan', None)
        project['plan_corrections'][str(gen)] = attempt + 1
        project.setdefault('orchestration_log', []).append(dict(kind='plan_correction_accepted', generation=gen, attempts=attempt + 1, at=int(time.time())))
        self._state.event(conn, root['root_id'], 'project_plan_corrected', dict(generation=gen, attempts=attempt + 1, task_id=row['task_id'], review_task=review_row['task_id']))
        return True

    def _correction_failed(self, conn, root, project, correction, key, reason, findings=None):
        used = correction['attempt'] + 1
        project['plan_corrections'][str(correction['gen'])] = used
        project.setdefault('orchestration_log', []).append(dict(kind='plan_correction_failed', generation=correction['gen'], attempt=used, reason=reason[:400], at=int(time.time())))
        self._state.event(conn, root['root_id'], 'project_plan_correction_failed', dict(generation=correction['gen'], attempt=used, reason=reason[:1000]))
        if used >= MAX_PLAN_CORRECTIONS:
            raise ConfigurationError(f'Plan correction budget exhausted after {used} attempts: {reason}')
        correction.update(attempt=used, findings=findings or correction['findings'])
        project.setdefault('handoff_rejections', {})[key] = dict(attempt=used, max_attempts=MAX_PLAN_CORRECTIONS, reason=reason,
            instruction='Fix only what remains; the same limits apply: no task, owner, dependency or acceptance-criterion change, and original baselines stay.')
        return True

    def _replan(self, conn, root, project, task, reason, findings, inputs):
        """Return the project to the architect. Bounded; completed tasks stay frozen."""
        grants = project.get('replan_grants', {})
        if project.get('replans', 0) >= MAX_REPLANS + grants.get('granted', 0):
            return False
        if project.get('replans', 0) >= MAX_REPLANS:
            # This replan runs on a human grant: record the consumption.
            grants['consumed'] = grants.get('consumed', 0) + 1
            grants.setdefault('log', []).append(dict(kind='consumed', replan=project.get('replans', 0) + 1, reason=reason[:300], at=int(time.time())))
            self._state.event(conn, root['root_id'], 'project_replan_grant_consumed', dict(consumed=grants['consumed'], granted=grants['granted']))
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
        if mode not in ('retro', 'finished'):
            self._refresh_references(project, context)
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
                    project['awaiting'] = dict(profile='art-director', sha256=art['sha256'], path=art['path'], task_id=art['task_id'], references_digest=project.get('references_digest', ''), explained=[dict(id=c['id'], requirement=c['requirement'], text=c['text'], explanation=c['explanation']) for c in project.get('explained_candidates', {}).get('art-director', [])],
                                           **({'mockup': art['mockup']} if art.get('mockup') else {}))
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
                errors, tasks, plan_constraints = [], None, None
                try:
                    tasks = validate_plan(plan_document, project['scope'], result.metadata['ac_ids'])
                    plan_constraints = validate_plan_constraints(plan_document.get('constraints'))
                except ConfigurationError as exc:
                    errors.append(str(exc))
                if refs.authoritative(project.get('reference_records', [])):
                    # All structural problems are reported together, even when the schema check failed: one error per retry would exhaust the budget.
                    errors += self._reference_plan_errors(project, context, plan_document, tasks)
                if errors:
                    raise ConfigurationError('; '.join(errors))
            except ConfigurationError as exc:
                # Structural failure, not an architectural one: the architect corrects it with the exact errors, off the replan budget.
                tries = project.setdefault('plan_validation_retries', {}).get(str(gen), 0)
                if tries >= MAX_PLAN_VALIDATION_RETRIES:
                    raise ConfigurationError(f'Plan still failed validation after {tries} corrections: {exc}')
                project['plan_validation_retries'][str(gen)] = tries + 1
                project.setdefault('handoff_rejections', {})['project-architect'] = dict(
                    attempt=tries + 1, max_attempts=MAX_PLAN_VALIDATION_RETRIES, rejected_task=row['task_id'],
                    reason='Plan failed structural validation: ' + str(exc), required_schema=PLAN_SCHEMA,
                    instruction='Correct only what the validation errors name, keep every valid part of the plan, and resubmit project-plan.json. '
                                'Your previous attachments are readable from the rejected task.')
                project.setdefault('retry_keys', []).append(f'project-architect:{gen}')
                project.setdefault('orchestration_log', []).append(dict(kind='plan_validation_retry', generation=gen, attempt=tries + 1, reason=str(exc)[:400], at=int(time.time())))
                self._state.event(conn, root['root_id'], 'plan_validation_rejected', dict(generation=gen, attempt=tries + 1, reason=str(exc)[:1000]))
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
            candidates = self._open_candidates(project)
            if candidates:
                ambiguous = [e for e in refs.validate_adjudication(retained_json(result.metadata['artifacts'], 'scan-adjudication.json'), candidates) if e['verdict'] == 'ambiguous']
                if ambiguous:
                    raise ProjectBlocked('Plan prose the reviewer could not rule on needs a human: ' + '; '.join(f"{e['id']} ({e['rationale'][:120]})" for e in ambiguous)
                                         + '. Resume with "SCAN-BENIGN <id>" for each you accept; anything else asks the reviewer again.')
            blocking = [reviewer + ':' + f for f in blocking_findings(result.metadata.get('findings', []))]
            if blocking:
                classes = self._plan_classes(project, result, blocking)
                if all(kind == 'correction' for kind in classes.values()):
                    # Localized wording, metadata or consistency defects: corrected in place, off the architectural replan budget.
                    used = project.setdefault('plan_corrections', {}).get(str(gen), 0)
                    if used >= MAX_PLAN_CORRECTIONS:
                        raise ConfigurationError(f'Plan correction budget exhausted ({used} attempts): {len(blocking)} finding(s) remain')
                    optional = [reviewer + ':' + f for f in result.metadata.get('findings', []) if reviewer + ':' + f not in blocking]
                    project['correction'] = dict(gen=gen, attempt=used, findings=blocking, optional=optional, review_task=row['task_id'])
                    project['mode'] = 'plan_correction'
                    self._state.event(conn, root['root_id'], 'project_plan_correction_started', dict(generation=gen, findings=blocking, classes=classes))
                    return True
                if not self._replan(conn, root, project, None, 'Plan review findings', blocking, [row['task_id']]):
                    raise ConfigurationError('Plan review findings remain after the replan limit')
                return True
            project.pop('replan', None)
            project['mode'] = 'tasks'
            self._state.event(conn, root['root_id'], 'project_plan_approved', dict(task_id=row['task_id'], reviewer=reviewer, generation=gen))
            return True
        if mode == 'plan_correction':
            return self._plan_correction(conn, root, definition, context, project)
        if mode == 'tasks':
            task = self._current(project)
            if task is None and refs.authoritative(project.get('reference_records', [])):
                left = self._bible_contradictions(project, context)
                if left:
                    findings = [f"F{i}|BLOCKER|-|{c['document']}|contradicts {c['requirement']}: {c['text']}" for i, c in enumerate(left[:10], 1)]
                    if not self._replan(conn, root, project, None, 'The style bible still contradicts an approved reference', findings, []):
                        raise ConfigurationError('Style bible still contradicts approved reference ' + left[0]['requirement'] + ' after the replan limit')
                    return True
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
        verifier = self._scoped_verifier(verifier, task)
        blockers = tool_blockers(verifier.metadata)
        if any(v == 'unverified:environment' for v in verifier.metadata['ac_results'].values()) or blockers:
            raise ProjectBlocked('Verification requires unavailable environment or tools' + (': ' + '; '.join(blockers) if blockers else ''))
        preliminary = self._evaluate(writer, [verifier], work, definition, context, project)
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
            human_approved = bool(refs.authoritative(project.get('reference_records', [])))
            if profile == 'art-reviewer':
                instructions += '\n' + COMPARISON + ('\n' + APPROVED_COMPARISON if human_approved else '')
            if profile == 'art-reviewer' and task['id'] != 'integration' and not human_approved:
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
            # With a human-approved reference no score substitutes for the requirement-by-requirement judgement against the original image.
            close_enough = profile != 'art-reviewer' or task['id'] == 'integration' or human_approved or validate_similarity(result)
            if profile == 'art-reviewer' and close_enough:
                record = validate_comparison(profile, result, project['plans'], task['id'] == 'integration', human_approved)
                if human_approved:
                    refs.validate_reference_comparison(record, project['reference_records'])
            readers.append(result)
            rows.append(row)
        if waiting:
            return False
        decision = self._evaluate(writer, readers, work, definition, context, project)
        if decision.decision == 'repair' and not self._spec_check(conn, root, definition, context, project, task, work, cycle, prefix,
                                                                   readers, decision, [*inputs, verifier_row['task_id']]):
            return False
        return self._decision(conn, root, project, task, writer, readers, decision, rows, definition, reviewed=True)

    def _evaluate(self, writer, readers, work, definition, context, project):
        """The gate decision with the product repair budget only: orchestration recoveries never count against it."""
        product_used, _ = budget_used(work)
        limit = definition.max_repairs + work.get('extra_repairs', 0)
        args = dict(context={**context, 'unity_ci': False, 'waivers': project.get('waivers', [])})
        decision = evaluate_cycle(writer, readers, work.get('last_gate'), limit, product_used, **args)
        if decision.decision == 'human_review' and decision.reason == REPAIR_LIMIT and repair_origin(decision.blocking) == 'orchestration':
            decision = evaluate_cycle(writer, readers, work.get('last_gate'), 10 ** 6, 0, **args)  # not a product defect: the product budget does not apply
        return decision

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
            if exhausted and work.get('on_exhaustion') == 'human_review':
                # A human chose, in a recorded decision, to review this task instead of replanning or granting another repair.
                self._terminal(conn, root, project, 'human_review', 'Repair budget exhausted after a granted extra repair; human review was requested instead of a replan or another repair')
                return True
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
            origin = repair_origin(decision.blocking)
            if 'charges' not in work:  # keep a recorded task's earlier repairs on the audit trail
                work['charges'] = [dict(cycle=i, kind='product', reason='recorded before charges existed') for i in range(work['cycle'])]
            if origin == 'orchestration' and budget_used(work)[1] >= MAX_ORCHESTRATION_RECOVERIES:
                self._terminal(conn, root, project, 'human_review', 'Orchestration recovery limit reached: ' + '; '.join(decision.blocking)[:300])
                return True
            charge = dict(cycle=work['cycle'], kind=origin, reason=(origin + ' repair for: ' + '; '.join(decision.blocking))[:400])
            work['charges'].append(charge)
            self._state.event(conn, root['root_id'], 'project_repair_charged', dict(task=task['id'], charge=charge, used=list(budget_used(work)),
                              product_limit=definition.max_repairs + work.get('extra_repairs', 0), orchestration_limit=MAX_ORCHESTRATION_RECOVERIES))
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
    def _scoped_verifier(verifier, task):
        """Only this task's acceptance IDs are judged. A verifier that also lists other project IDs (task text often says "ac_status covers
        AC1..ACn") is not blocked by criteria that belong to other tasks; what it reported for them is kept, but ignored. A task ID it
        omits still fails the gate's coverage check."""
        results = verifier.metadata.get('ac_results') if verifier.valid else None
        if not isinstance(results, dict) or set(results) <= set(task['acceptance']):
            return verifier
        kept = {ac: outcome for ac, outcome in results.items() if ac in task['acceptance']}
        ignored = {ac: outcome for ac, outcome in results.items() if ac not in task['acceptance']}
        return replace(verifier, metadata={**verifier.metadata, 'ac_results': kept, 'ac_results_ignored': ignored})

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
        if decided['plan_correction'] and 'plan_review' not in (project.get('mode'), project.get('resume_mode')):
            raise ConfigurationError('plan_correction applies to a plan-review stop; this project did not stop there')
        awaiting = project.get('awaiting')
        if decisions and awaiting and not project.get('terminal'):
            raise ConfigurationError('Waivers and constraints apply to a blocked stage, not to plan approval')
        if root['phase'] == 'blocked' and awaiting and not project.get('terminal'):
            # Approval is an explicit, bound decision. 'REJECT: <feedback>' returns the plan to the director; only the exact phrase
            # "APPROVE <root> <plan sha12> <references digest12|none>" approves. Any other note (a recovery note, a retry reason) approves nothing.
            profile, text = awaiting['profile'], note.strip()
            rejected = text.upper().startswith('REJECT:')
            if rejected and not text[7:].strip():
                raise ConfigurationError('A rejection requires feedback for the director')
            if not rejected:
                phrase = self._approval_phrase(root['root_id'], project)
                if not (text == phrase or text.startswith(phrase + ' ')):
                    raise ConfigurationError('This root awaits a human decision on the art-director plan. Approve with exactly "' + phrase + '" (optionally followed by a comment), '
                                             'or reject with "REJECT: <feedback>". A recovery note never approves a plan.')
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
        exhausted = {k: v for k, v in project.get('handoff_retries', {}).items() if v >= (MAX_SCAN_RETRIES if k.endswith(':scan') else MAX_HANDOFF_RETRIES)}
        exhausted_plan = {k: v for k, v in project.get('plan_validation_retries', {}).items() if v >= MAX_PLAN_VALIDATION_RETRIES}
        if decided['extra_handoff_retries'] and not (exhausted or exhausted_plan):
            raise ConfigurationError('extra_handoff_retries applies to a stage whose handoff or plan-correction retries are exhausted; none is')
        stopped = ('blocked', 'human_review') if reevaluate or decided['extra_handoff_retries'] else ('blocked',)
        if root['phase'] not in stopped or project.get('terminal', {}).get('phase') not in stopped:
            raise ConfigurationError('Only an infrastructure-blocked project can resume; changed scope requires a new task')
        project.update(mode=project['resume_mode'], active_keys=[], recoveries=project.get('recoveries', 0)+1, recovery_note=note)
        if decided['extra_handoff_retries']:
            # A bounded, audited human grant: the exhausted budgets get this many attempts back. Approvals, the approved plan and every other state stay as they are.
            grant = decided['extra_handoff_retries']
            for key, value in exhausted.items():
                project['handoff_retries'][key] = max(0, (MAX_SCAN_RETRIES if key.endswith(':scan') else MAX_HANDOFF_RETRIES) - grant)
            for key in exhausted_plan:
                project['plan_validation_retries'][key] = max(0, MAX_PLAN_VALIDATION_RETRIES - grant)
            project.setdefault('orchestration_log', []).append(dict(kind='human_handoff_grant', amount=grant, budgets=sorted([*exhausted, *('plan:' + k for k in exhausted_plan)]),
                                                                   reason=note.strip()[:500], at=int(time.time())))
        project.setdefault('scan_resolved', []).extend(i for i in re.findall(r'SCAN-BENIGN ([0-9a-f]{8})', note) if i not in project.get('scan_resolved', []))
        if project.get('references_digest'):
            task = self._board.get_task(conn, root['root_id'])
            current = refs.load_references(self._controller._context(task)['project_dir'])['digest']
            if current != project['references_digest']:
                phrase = 'APPROVE-REFERENCES ' + current[:12]
                if phrase not in note:
                    raise ConfigurationError('The approved references changed since the run started. A human must re-approve them: include "' + phrase + '" in the resume note. '
                                             'Recovery alone never re-approves references.')
                project.pop('references_digest', None)
        project.pop('terminal', None);project.pop('retro', None)
        known = {w['id'] for w in project.setdefault('waivers', [])}
        project['waivers'].extend(w for w in decided['waivers'] if w['id'] not in known)
        stored = [constraint_view(c) for c in project.setdefault('constraints', [])]  # decisions recorded before ids existed get one now
        project['constraints'] = stored + [c for c in decided['constraints'] if c['id'] not in {k['id'] for k in stored}]
        if decided['plan_correction']:
            project['plan_class_overrides'] = dict(gen=project.get('gen', 0), ids=decided['plan_correction'], note=note.strip()[:500], at=int(time.time()))
        if decided['extra_replans']:
            grants = project.setdefault('replan_grants', dict(granted=0, consumed=0, log=[]))
            grants['granted'] += decided['extra_replans']
            grants['log'].append(dict(kind='granted', amount=decided['extra_replans'], reason=note.strip()[:500], at=int(time.time())))
        if decided['on_exhaustion'] and 'work' in project:
            project['work']['on_exhaustion'] = decided['on_exhaustion']
        if decided['extra_repairs']:
            # Granted to the task in progress only: it lives in that task's work record and disappears with it.
            project['work']['extra_repairs'] = project['work'].get('extra_repairs', 0) + decided['extra_repairs']
        if decisions:
            self._state.event(conn, root['root_id'], 'human_decision', dict(note=note, waivers=[w['id'] for w in decided['waivers']],
                              constraints=decided['constraints'], extra_repairs=decided['extra_repairs'],
                              extra_replans=decided['extra_replans'], extra_handoff_retries=decided['extra_handoff_retries'], on_exhaustion=decided['on_exhaustion'], plan_correction=decided['plan_correction'],
                              execution_version=2))
        gen = project.get('gen', 0)
        if 'work' in project:
            work = project['work']
            task = self._current(project)
            prefix = self._prefix(project, task)
            if decisions and work['step'] == 'repairing' and work['repairs'] and work['cycle'] > 0 and not self._repair_done(conn, root, prefix, work):
                # The repairs were dispatched against findings the decision may have changed: retire the stalled repair and
                # judge the evidence that already exists again, instead of repeating verification or review work. The stalled card is left
                # on the board (blocked, harmless): archiving needs its own transaction, which this one already holds.
                work.update(step='reviewing', cycle=work['cycle'] - 1, repairs=[])
                if work.get('charges'):
                    work['charges'].pop()  # the repair that never ran was never spent
                work.pop('repair_findings', None)
                project['retry_keys'] = []
            elif reevaluate:
                # Judge the evidence that already exists again under the current rules: no stage is retried or repeated.
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
        if reevaluate:
            project['retry_keys'] = []  # whatever the stopped mode, judge the existing evidence instead of retrying a stage
        project.setdefault('orchestration_log', []).append(dict(kind='human_resume', reevaluate=bool(reevaluate), retry_keys=list(project.get('retry_keys', [])), at=int(time.time())))
        self._save(conn, root, project)
        conn.execute("UPDATE factory_workflow_roots SET phase='project',reason='' WHERE root_id=?", (root['root_id'],))
        self._state.event(conn, root['root_id'], 'human_resume', dict(note=note, execution_version=2))
        self._board._append_event(conn, root['root_id'], 'workflow_resumed', dict(note=note))
