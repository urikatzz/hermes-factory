"""Synthetic operator envelopes for importer tests; no worker calls."""
from pathlib import Path
from factory_ecc.files import digest, write_json
from factory_ecc.tasksets import find_case, source_manifest


def variant(identifier='baseline'):
    def stage(kind, profile):
        return dict(key=kind, kind=kind, profile=profile, instructions='')
    return dict(id=identifier, workflow=dict(template_id='fixture', revision=1, name='Fixture',
        description='', task_type='bug', prepare=stage('prepare','architect'),
        implement=stage('implement','developer'), repair=stage('repair','fixer'),
        verify=stage('verify','verifier'), reviewers=[stage('review','claude-reviewer')], max_repairs=3),
        roles={p: dict(provider='test-provider', model='synthetic-model', effort='medium')
               for p in ('architect','developer','fixer','verifier','claude-reviewer')})


def trial(root, taskset, trial_id='1', variant_id='baseline', case_id='bug'):
    case = find_case(taskset, case_id)
    prefix = f'{variant_id}-{case_id}-{trial_id}'
    source = root / prefix / 'source'
    source.mkdir(parents=True)
    (source / 'solution.py').write_text('def answer():\n    return 42\n')
    manifest = source_manifest(source)
    run_id = f'writer-{prefix}'
    reviewer = dict(profile='claude-reviewer', task_id='review-'+prefix, run_id='review-run-'+prefix,
                    outcome='completed', verdict='NO_BLOCKING_FINDINGS', manifest_sha12='a'*12)
    writer = dict(profile='developer', task_id='write-'+prefix, run_id=run_id,
                  outcome='completed', verdict='DONE', manifest_sha12='a'*12)
    verifier = dict(profile='verifier', task_id='verify-'+prefix, run_id='verify-run-'+prefix,
                    outcome='completed', verdict='PASS', manifest_sha12='a'*12,
                    ac_results={key:'pass' for key in case['acceptance']})
    grades = dict(schema='factory-ecc-grades/v1', case_id=case_id, taskset_digest=taskset['digest'],
                  manifest_sha256=manifest, grader_digest=taskset['files'][case['grader']],
                  acceptance=list(case['acceptance']), ac_results={key:'pass' for key in case['acceptance']})
    gate = dict(schema='factory-ecc-gate/v1', board='fixture-board', root_id='root-'+prefix,
                captured_variant=variant(variant_id), source_manifest_sha256=manifest,
                factory_manifest_sha12='a'*12, decision=dict(decision='pass',reason='All checks passed',blocking=[],waived=[]),
                repairs_used=0, writer=writer, verifier=verifier, reviewers=[reviewer],
                attempts_complete=True, writer_attempts=[dict(task_id=writer['task_id'],run_id=run_id,outcome='completed')])
    references = {}
    for name, document in (('grades',grades),('gate',gate)):
        path = root / prefix / (name+'.json')
        write_json(path, document)
        import hashlib
        references[name] = dict(path=path.relative_to(root).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return dict(trial_id=trial_id, variant_id=variant_id, case_id=case_id,
                board='fixture-board', root_id=gate['root_id'], writer_run_id=run_id,
                manifest_sha256=manifest, candidate_source=source.relative_to(root).as_posix(),
                terminal_outcome='completed', repairs=0, elapsed_seconds=12.5,
                evidence=references, sessions=[])


def results(taskset, trials, variants=None):
    return dict(schema='factory-ecc-results/v1', taskset_digest=taskset['digest'], synthetic=True,
                variants=variants or [variant()], trials=trials)
