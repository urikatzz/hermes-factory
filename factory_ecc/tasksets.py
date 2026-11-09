"""Pinned tasksets and credential-free benchmark input preparation."""
import hashlib
from pathlib import Path
import shutil
import stat

from .files import contained, digest, read_json, write_json

MAX_FILES = 100
MAX_BYTES = 1_048_576


def source_files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Source must be a real directory')
    files, total = {}, 0
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('Links and special source files are unsupported')
        if path.is_dir():
            continue
        if path.stat().st_nlink != 1:
            raise ValueError('Hardlinked source files are unsupported')
        total += path.stat().st_size
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError('Fixture source exceeds benchmark limits')
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError('Source is empty')
    return files


def source_manifest(root):
    return digest(source_files(root))


def load_taskset(root):
    root = Path(root).resolve(strict=True)
    document = read_json(contained(root, 'taskset.json'))
    if set(document) != {'schema', 'version', 'digest', 'cases', 'files'} or document['schema'] != 'factory-ecc-taskset/v1':
        raise ValueError('Unsupported taskset schema')
    if type(document['version']) is not int or document['version'] < 1:
        raise ValueError('Invalid taskset version')
    if document['digest'] != digest({k: v for k, v in document.items() if k != 'digest'}):
        raise ValueError('Taskset digest mismatch')
    if not isinstance(document['files'], dict) or len(document['files']) > MAX_FILES:
        raise ValueError('Invalid taskset files')
    total = 0
    for relative, expected in document['files'].items():
        path = contained(root, relative)
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('Missing or hardlinked taskset file')
        total += path.stat().st_size
        if total > MAX_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Taskset file digest/size mismatch: ' + relative)
    cases = document['cases']
    if not isinstance(cases, list) or not cases:
        raise ValueError('Taskset has no cases')
    seen = set()
    referenced = set()
    for case in cases:
        if set(case) != {'id', 'task_type', 'prompt', 'acceptance', 'source', 'grader'}:
            raise ValueError('Invalid case fields')
        if case['id'] in seen or case['id'] not in ('bug', 'feature', 'chore'):
            raise ValueError('Unknown or duplicate case ID')
        seen.add(case['id'])
        if case['task_type'] != case['id'] or not isinstance(case['prompt'], str) or not case['prompt']:
            raise ValueError('Invalid task prompt/type')
        if not isinstance(case['acceptance'], dict) or not case['acceptance'] or any(
                not key.startswith('AC') or not isinstance(value, str) or not value for key, value in case['acceptance'].items()):
            raise ValueError('Invalid acceptance criteria')
        if not isinstance(case['source'], list) or not case['source']:
            raise ValueError('Missing source files')
        for relative in case['source']:
            if not relative.startswith(f"cases/{case['id']}/source/") or relative not in document['files']:
                raise ValueError('Invalid case source path')
            referenced.add(relative)
        if not case['grader'].startswith('graders/') or case['grader'] not in document['files']:
            raise ValueError('Invalid grader path')
        referenced.add(case['grader'])
    if referenced != set(document['files']):
        raise ValueError('Unreferenced taskset files')
    return {**document, 'root': root}


def find_case(taskset, case_id):
    for case in taskset['cases']:
        if case['id'] == case_id:
            return case
    raise ValueError('Unknown case: ' + str(case_id))


def prepare_case(taskset, case_id, output):
    # Reload pinned bytes so a source change after loading cannot escape detection.
    fresh = load_taskset(taskset['root'])
    case = find_case(fresh, case_id)
    if fresh['digest'] != taskset['digest'] or case != find_case(taskset, case_id):
        raise ValueError('Taskset changed during preparation')
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Symlinked output')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for relative in case['source']:
        suffix = Path(relative).relative_to(f'cases/{case_id}/source')
        target = output / 'source' / suffix
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(contained(fresh['root'], relative), target)
    public = dict(case_id=case_id, taskset_digest=fresh['digest'], prompt=case['prompt'],
                  acceptance=case['acceptance'], task_type=case['task_type'])
    write_json(output / 'task.json', public, exclusive=True)
    return public
