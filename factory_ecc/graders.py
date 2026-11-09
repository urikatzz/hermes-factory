"""Prepare grading inputs; candidate code is never executed on the host."""
from pathlib import Path
import shutil

from .files import contained, write_json
from .tasksets import find_case, load_taskset, source_files, source_manifest


def prepare_grading(taskset, case_id, candidate, output):
    fresh = load_taskset(taskset['root'])
    if fresh['digest'] != taskset['digest']:
        raise ValueError('Taskset changed during grading preparation')
    case = find_case(fresh, case_id)
    files = source_files(candidate)
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Symlinked output')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for relative in files:
        target = output / 'candidate' / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(contained(candidate, relative), target)
    manifest = source_manifest(output / 'candidate')
    if manifest != source_manifest(candidate):
        raise ValueError('Candidate changed during grading preparation')
    trusted = output / 'trusted'
    trusted.mkdir(mode=0o700)
    shutil.copyfile(contained(fresh['root'], case['grader']), trusted / 'grader.py')
    identity = dict(schema='factory-ecc-grading-job/v1', taskset_digest=fresh['digest'],
                    case_id=case_id, manifest_sha256=manifest,
                    grader_digest=fresh['files'][case['grader']], acceptance=list(case['acceptance']))
    write_json(trusted / 'job.json', identity, exclusive=True)
    return identity
