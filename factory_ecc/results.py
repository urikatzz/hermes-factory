"""Validate operator-imported benchmark evidence; never execute candidate code."""
import hashlib
import math
from pathlib import Path
import re

from .files import contained, read_json
from .tasksets import find_case, source_manifest
from .trial_set import TrialSet

HEX64 = re.compile(r'[a-f0-9]{64}\Z')
HEX12 = re.compile(r'[a-f0-9]{12}\Z')
COUNTERS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')


def fields(value, required, label):
    if not isinstance(value, dict) or set(value) != set(required.split()):
        raise ValueError(f'{label}: invalid or unknown fields')


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f'{label}: expected nonempty bounded text')


def identity(value, label):
    if type(value) is int and value > 0:
        return
    text(value, label)


def number(value, label, *, integer=False):
    if value is None:
        return
    types = (int,) if integer else (int, float)
    if type(value) not in types or (isinstance(value,float) and not math.isfinite(value)) or value < 0:
        raise ValueError(f'{label}: expected nonnegative finite number or null')


def sha(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(label + ': invalid digest')


def validate_variant(variant):
    fields(variant, 'id workflow roles', 'variant')
    text(variant['id'], 'variant ID')
    workflow = variant['workflow']
    fields(workflow, 'template_id revision name description task_type prepare implement reviewers verify repair max_repairs', 'workflow')
    text(workflow['template_id'], 'template ID')
    if type(workflow['revision']) is not int or workflow['revision'] < 1:
        raise ValueError('Invalid captured workflow revision')
    text(workflow['name'], 'workflow name')
    if not isinstance(workflow['description'], str) or workflow['task_type'] not in ('bug', 'feature', 'chore'):
        raise ValueError('Invalid captured workflow')
    if type(workflow['max_repairs']) is not int or not 0 <= workflow['max_repairs'] <= 3:
        raise ValueError('Invalid captured repair limit')
    if not isinstance(workflow['reviewers'], list) or not workflow['reviewers']:
        raise ValueError('Missing captured review panel')
    profiles, keys = [], set()
    for kind, stage in [(k, workflow[k]) for k in ('prepare','implement','verify','repair')] + [('review',s) for s in workflow['reviewers']]:
        fields(stage, 'key kind profile instructions', 'stage')
        text(stage['key'], 'stage key'); text(stage['profile'], 'stage profile')
        if stage['key'] in keys or stage['kind'] != kind or not isinstance(stage['instructions'], str) or len(stage['instructions']) > 4000:
            raise ValueError('Invalid captured stage')
        keys.add(stage['key']); profiles.append(stage['profile'])
    reviewers = [s['profile'] for s in workflow['reviewers']]
    if len(set(reviewers)) != len(reviewers) or not set(reviewers) & {'claude-reviewer','codex-reviewer'}:
        raise ValueError('Invalid captured code review panel')
    writers = {workflow[k]['profile'] for k in ('implement','repair')}
    if writers & (set(reviewers) | {workflow['verify']['profile']}):
        raise ValueError('Writer/reviewer independence is missing')
    if not isinstance(variant['roles'], dict) or not set(profiles) <= set(variant['roles']):
        raise ValueError('Missing captured profile settings')
    for role, settings in variant['roles'].items():
        text(role, 'role'); fields(settings, 'provider model effort', 'role settings')
        text(settings['provider'], 'provider'); text(settings['model'], 'model')
        if settings['effort'] is not None:
            text(settings['effort'], 'effort')


def validate_sessions(sessions):
    if not isinstance(sessions, list):
        raise ValueError('Invalid session list')
    for session in sessions:
        fields(session, 'id actual_usd estimate_usd included ' + ' '.join(COUNTERS), 'session')
        text(session['id'], 'scoped session ID')
        if type(session['included']) is not bool:
            raise ValueError('Session included must be explicit boolean')
        for key in ('actual_usd','estimate_usd'):
            number(session[key], key)
        for key in COUNTERS:
            number(session[key], key, integer=True)


def evidence_file(root, reference):
    if reference is None:
        return None
    fields(reference, 'path sha256', 'evidence reference')
    sha(reference['sha256'], HEX64, 'evidence')
    path = contained(root, reference['path'])
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 2_097_152:
        raise ValueError('Evidence must be a bounded regular JSON file')
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference['sha256']:
        raise ValueError('Evidence bytes differ from imported digest')
    return read_json(path)


def validate_grades(grades, trial, case, taskset):
    fields(grades, 'schema case_id taskset_digest manifest_sha256 grader_digest acceptance ac_results', 'grades')
    expected = dict(schema='factory-ecc-grades/v1',case_id=case['id'],taskset_digest=taskset['digest'],
                    manifest_sha256=trial['manifest_sha256'], grader_digest=taskset['files'][case['grader']])
    if any(grades[k] != v for k,v in expected.items()):
        raise ValueError('Grade identity does not match pinned taskset and candidate')
    if not isinstance(grades['acceptance'], list) or set(grades['acceptance']) != set(case['acceptance']) or len(grades['acceptance']) != len(case['acceptance']):
        raise ValueError('Grade acceptance identity differs from taskset')
    outcomes = grades['ac_results']
    if not isinstance(outcomes, dict) or set(outcomes) != set(case['acceptance']) or any(v not in ('pass','fail') for v in outcomes.values()):
        raise ValueError('Invalid deterministic acceptance results')
    return all(v == 'pass' for v in outcomes.values())


def validate_gate(gate, trial, variant, case):
    fields(gate, 'schema board root_id captured_variant source_manifest_sha256 factory_manifest_sha12 decision repairs_used writer verifier reviewers attempts_complete writer_attempts', 'gate')
    expected = dict(schema='factory-ecc-gate/v1',board=trial['board'],root_id=trial['root_id'],
                    captured_variant=variant, source_manifest_sha256=trial['manifest_sha256'],repairs_used=trial['repairs'])
    if any(gate[k] != v for k,v in expected.items()):
        raise ValueError('Gate identity or captured variant differs from trial')
    if type(gate['repairs_used']) is not int or gate['repairs_used'] < 0:
        raise ValueError('Gate repair count must be a recorded nonnegative integer')
    sha(gate['factory_manifest_sha12'], HEX12, 'Factory manifest')
    decision = gate['decision']
    fields(decision, 'decision reason blocking waived', 'gate decision')
    if decision['decision'] not in ('pass','repair','blocked','human_review','wait') or not isinstance(decision['reason'], str):
        raise ValueError('Invalid gate decision')
    if any(not isinstance(decision[k], list) or any(not isinstance(v,str) for v in decision[k]) for k in ('blocking','waived')):
        raise ValueError('Invalid gate findings')
    if type(gate['attempts_complete']) is not bool or not isinstance(gate['writer_attempts'], list):
        raise ValueError('Missing attempt coverage evidence')
    attempt_ids, attempt_outcomes = set(), {}
    for attempt in gate['writer_attempts']:
        fields(attempt, 'task_id run_id outcome', 'attempt')
        identity(attempt['task_id'], 'attempt task'); identity(attempt['run_id'], 'attempt run')
        pair = (attempt['task_id'],attempt['run_id'])
        if pair in attempt_ids or attempt['outcome'] not in ('completed','failed','blocked','error','cancelled'):
            raise ValueError('Duplicate or invalid writer attempt')
        attempt_ids.add(pair)
        attempt_outcomes[pair] = attempt['outcome']
    if not isinstance(gate['reviewers'], list):
        raise ValueError('Invalid reviewer evidence')
    complete, positive, negative = True, True, bool(decision['blocking'])
    expected_writer = variant['workflow']['repair' if (trial['repairs'] or 0) > 0 else 'implement']['profile']
    actors = [(gate['writer'], expected_writer, 'DONE'), (gate['verifier'],variant['workflow']['verify']['profile'],'PASS')]
    expected_reviewers = [s['profile'] for s in variant['workflow']['reviewers']]
    actual_reviewers = []
    for reviewer in gate['reviewers']:
        if not isinstance(reviewer, dict):
            raise ValueError('Invalid reviewer record')
        text(reviewer.get('profile'), 'reviewer profile')
        actual_reviewers.append(reviewer.get('profile'))
        actors.append((reviewer,reviewer.get('profile'),'NO_BLOCKING_FINDINGS'))
    if len(actual_reviewers) != len(set(actual_reviewers)) or set(actual_reviewers) - set(expected_reviewers):
        raise ValueError('Duplicate or unexpected reviewer')
    if set(actual_reviewers) != set(expected_reviewers):
        complete = False
    run_ids, task_ids = set(), set()
    for actor, expected_profile, verdict in actors:
        if actor is None:
            complete = False
            continue
        required = 'profile task_id run_id outcome verdict manifest_sha12'
        if actor is gate['verifier']:
            required += ' ac_results'
        fields(actor, required, 'stage evidence')
        identity(actor['task_id'], 'stage task'); identity(actor['run_id'], 'stage run')
        if actor['profile'] != expected_profile or actor['manifest_sha12'] != gate['factory_manifest_sha12']:
            raise ValueError('Stage profile or manifest contradicts gate')
        if actor['run_id'] in run_ids or actor['task_id'] in task_ids:
            raise ValueError('Independent stages must have distinct task/run identities')
        run_ids.add(actor['run_id']); task_ids.add(actor['task_id'])
        if actor['outcome'] not in ('completed','failed','blocked','error','cancelled'):
            raise ValueError('Invalid stage outcome')
        allowed_verdicts = ('PASS','FAIL') if actor is gate['verifier'] else (
            ('DONE','BLOCKED') if actor is gate['writer'] else ('NO_BLOCKING_FINDINGS','CHANGES_REQUIRED'))
        if actor['verdict'] not in allowed_verdicts:
            raise ValueError('Invalid stage verdict')
        if actor['outcome'] != 'completed':
            complete = False
        positive = positive and actor['verdict'] == verdict
        negative = negative or actor['verdict'] != verdict
    if gate['writer'] is not None:
        writer = gate['writer']
        if writer['run_id'] != trial['writer_run_id']:
            raise ValueError('Writer run identity differs from trial')
        pair = (writer['task_id'],writer['run_id'])
        if pair in attempt_outcomes and attempt_outcomes[pair] != writer['outcome']:
            raise ValueError('Writer outcome contradicts the same recorded task/run attempt')
        if gate['attempts_complete'] and (writer['task_id'],writer['run_id']) not in attempt_ids:
            raise ValueError('Complete attempt history omits the reviewed writer')
    if gate['verifier'] is not None:
        outcomes = gate['verifier']['ac_results']
        if not isinstance(outcomes,dict) or set(outcomes) != set(case['acceptance']) or any(
                v not in ('pass','fail','unverified:code','unverified:harness','unverified:environment') for v in outcomes.values()):
            raise ValueError('Verifier acceptance identity differs from taskset')
        positive = positive and all(v == 'pass' for v in outcomes.values())
        negative = negative or any(v in ('fail','unverified:code','unverified:harness') for v in outcomes.values())
    passed = complete and positive and decision['decision'] == 'pass' and not decision['blocking']
    first = None if not gate['attempts_complete'] or trial['repairs'] is None else (
        passed and trial['repairs'] == 0 and len(gate['writer_attempts']) == 1
        and gate['writer_attempts'][0]['outcome'] == 'completed')
    return complete, passed, first, negative


def load_trials(taskset, results_path, evidence_root):
    document = read_json(results_path)
    fields(document, 'schema taskset_digest synthetic variants trials', 'results')
    if document['schema'] != 'factory-ecc-results/v1' or document['taskset_digest'] != taskset['digest']:
        raise ValueError('Unsupported results schema or mismatched taskset digest')
    if type(document['synthetic']) is not bool or not isinstance(document['variants'],list) or not isinstance(document['trials'],list):
        raise ValueError('Explicit result provenance, variants and trials required')
    variants = {}
    for variant in document['variants']:
        validate_variant(variant)
        if variant['id'] in variants:
            raise ValueError('Duplicate/conflicting variant definition')
        variants[variant['id']] = variant
    seen, linked_roots, session_records, rows = set(), set(), {}, []
    for trial in document['trials']:
        fields(trial, 'trial_id variant_id case_id board root_id writer_run_id manifest_sha256 candidate_source terminal_outcome repairs elapsed_seconds evidence sessions', 'trial')
        text(trial['trial_id'],'trial ID'); text(trial['variant_id'],'variant ID')
        case = find_case(taskset,trial['case_id'])
        if trial['variant_id'] not in variants:
            raise ValueError('Unknown trial variant')
        key = (trial['variant_id'],trial['case_id'],trial['trial_id'])
        if key in seen:
            raise ValueError('Duplicate trial identity')
        seen.add(key)
        for field in ('board','root_id','writer_run_id'):
            if trial[field] is not None:
                identity(trial[field],field)
        if trial['root_id'] is not None:
            root_key = (trial['board'],trial['root_id'])
            if root_key in linked_roots:
                raise ValueError('One Factory root cannot count as multiple independent trials')
            linked_roots.add(root_key)
        number(trial['repairs'],'repairs',integer=True); number(trial['elapsed_seconds'],'elapsed seconds')
        if trial['repairs'] is not None and trial['repairs'] > variants[trial['variant_id']]['workflow']['max_repairs']:
            raise ValueError('Trial exceeds captured repair limit')
        if trial['terminal_outcome'] not in ('completed','failed','infrastructure_blocked','incomplete'):
            raise ValueError('Unknown terminal outcome')
        fields(trial['evidence'],'grades gate','trial evidence')
        validate_sessions(trial['sessions'])
        for session in trial['sessions']:
            if session['id'] in session_records and session_records[session['id']] != session:
                raise ValueError('Conflicting usage for a shared session')
            session_records[session['id']] = session
        source_known = False
        if trial['manifest_sha256'] is not None:
            sha(trial['manifest_sha256'], HEX64, 'candidate manifest')
        if trial['candidate_source'] is not None:
            source = contained(evidence_root,trial['candidate_source'])
            if source.exists():
                if trial['manifest_sha256'] != source_manifest(source):
                    raise ValueError('Candidate source manifest mismatch')
                source_known = True
        grades = evidence_file(evidence_root,trial['evidence']['grades'])
        gate = evidence_file(evidence_root,trial['evidence']['gate'])
        grade_pass = validate_grades(grades,trial,case,taskset) if grades is not None else None
        gate_complete, gate_pass, first, gate_negative = validate_gate(gate,trial,variants[trial['variant_id']],case) if gate is not None else (False,False,None,False)
        classification = trial['terminal_outcome']
        all_evidence = source_known and grades is not None and gate is not None
        identities_known = all(trial[k] is not None for k in ('board','root_id','writer_run_id','repairs'))
        evidence_complete = all_evidence and identities_known and gate_complete
        # Affirmative failures stay in the denominator even when other coverage is missing.
        known_failure = source_known and (grade_pass is False or gate_negative)
        if classification in ('completed','failed') and known_failure:
            classification = 'failed'
        elif classification == 'completed':
            if not all_evidence or not identities_known or not gate_complete:
                classification = 'incomplete'
            elif grade_pass and gate_pass:
                classification = 'success'
            else:
                classification = 'failed'
        elif classification == 'failed':
            if not all_evidence or not identities_known:
                classification = 'incomplete'
            elif grade_pass and gate_pass:
                raise ValueError('Failed terminal outcome contradicts passing evidence')
        if classification not in ('success','failed'):
            first = None
        elif classification == 'failed' and first is not None:
            first = False
        rows.append({**trial,'classification':classification,'first_attempt':first,'evidence_complete':evidence_complete})
    return TrialSet(rows,list(variants.values()),document['synthetic'],taskset['digest'])
