#!/usr/bin/env python3
"""Check, reapply and export the Factory's patches to the Hermes source tree.

The Factory depends on a few local changes to Hermes (the kanban mutation guard, task creation and worker-model hooks, the extra
hook names, and the kanban dashboard plugin). Hermes updates reset its source tree to an upstream commit, which silently removes
them. They are kept here, version controlled, as plain git patches against upstream, with a manifest of the files they produce.

    hermes_patches.py status [--json]      exit 0 all applied, 1 something missing but appliable, 2 a patch conflicts
    hermes_patches.py apply [--dry-run]    apply every missing patch that applies cleanly; never partially, never over a conflict
    hermes_patches.py export --tree PATH   rewrite patches and manifest from a tree that is upstream plus the patches (after resolving
                                           a conflict in a scratch `git worktree`), see README.md

The Hermes source defaults to $HERMES_SOURCE or ~/.hermes/hermes-agent. Nothing here restarts anything: a running gateway keeps the code it
loaded, so restart it after `apply`.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PATCHES = HERE / 'patches'
MANIFEST = HERE / 'manifest.json'
APPLIED, MISSING, CONFLICT = 'applied', 'missing', 'conflict'


def source_dir(arg=None):
    return Path(arg or os.environ.get('HERMES_SOURCE') or Path.home() / '.hermes' / 'hermes-agent').expanduser()


def git(source, *args, stdin=None):
    return subprocess.run(['git', '-C', str(source), *args], capture_output=True, text=True, input=stdin)


def load_manifest():
    return json.loads(MANIFEST.read_text())


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def patch_state(source, patch):
    """One patch against one tree: applied (files match the manifest, or the reverse patch applies despite upstream drift),
    missing (the forward patch applies cleanly) or conflict (neither)."""
    text = (PATCHES / (patch['id'] + '.patch')).read_text()
    files = patch['files']
    if all((source / f['path']).is_file() and sha256(source / f['path']) == f['sha256'] for f in files):
        return APPLIED, 'files match the manifest'
    if git(source, 'apply', '--reverse', '--check', '-', stdin=text).returncode == 0:
        return APPLIED, 'patch is present; the files differ from the manifest only by changes around it'
    check = git(source, 'apply', '--check', '-', stdin=text)
    if check.returncode == 0:
        return MISSING, 'absent, applies cleanly'
    return CONFLICT, (check.stderr.strip() or 'does not apply')[:400]


def status(source, manifest=None):
    manifest = manifest or load_manifest()
    head = git(source, 'rev-parse', 'HEAD').stdout.strip()
    result = []
    for patch in manifest['patches']:
        state, detail = patch_state(source, patch)
        result.append(dict(id=patch['id'], state=state, detail=detail, description=patch['description']))
    return dict(source=str(source), head=head, verified_with=manifest.get('verified_with', []),
                known_head=any(head.startswith(v[:12]) or v.startswith(head[:12]) for v in manifest.get('verified_with', [])) if head else False,
                patches=result, ok=all(p['state'] == APPLIED for p in result),
                missing=[p['id'] for p in result if p['state'] == MISSING], conflicts=[p['id'] for p in result if p['state'] == CONFLICT])


def exit_code(report):
    return 2 if report['conflicts'] else 1 if report['missing'] else 0


def cmd_status(args):
    report = status(source_dir(args.source))
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"Hermes source {report['source']} at {report['head'][:12]}" + ('' if report['known_head'] else '  (a commit these patches were not verified with)'))
        for p in report['patches']:
            print(f"  {p['state']:9} {p['id']}: {p['detail']}")
    return exit_code(report)


def python_files(patch):
    return [f['path'] for f in patch['files'] if f['path'].endswith('.py')]


def cmd_apply(args):
    source = source_dir(args.source)
    manifest = load_manifest()
    report = status(source, manifest)
    if report['conflicts']:
        print('Refusing to apply: ' + ', '.join(report['conflicts']) + ' conflict(s) with this Hermes version. Resolve in a scratch `git worktree` '
              'and run `export` (README.md); nothing was changed.', file=sys.stderr)
        return 2
    todo = [p for p in manifest['patches'] if p['id'] in report['missing']]
    if not todo:
        print('Nothing to apply: every patch is present.')
        return 0
    backup = Path.home() / '.hermes' / 'backups' / ('hermes-patches-' + time.strftime('%Y%m%dT%H%M%S'))
    for patch in todo:
        print(('would apply ' if args.dry_run else 'applying ') + patch['id'])
    if args.dry_run:
        return 0
    for patch in todo:
        for f in patch['files']:
            path = source / f['path']
            if path.is_file():
                target = backup / f['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    done = []

    def roll_back(reason):
        for earlier in reversed(done):
            git(source, 'apply', '--reverse', '-', stdin=(PATCHES / (earlier['id'] + '.patch')).read_text())
        print(reason + '; rolled back ' + str(len(done)) + ' patch(es), the tree is as it was.', file=sys.stderr)
        return 2

    for patch in todo:
        text = (PATCHES / (patch['id'] + '.patch')).read_text()
        result = git(source, 'apply', '-', stdin=text)
        if result.returncode:
            return roll_back('git apply failed for ' + patch['id'] + ': ' + result.stderr.strip())
        done.append(patch)
        try:
            for rel in python_files(patch):
                compile((source / rel).read_text(), rel, 'exec')  # syntax only; writes no bytecode into the Hermes tree
        except SyntaxError as exc:
            return roll_back(patch['id'] + ' left a file that does not compile (' + str(exc) + ')')
    after = status(source, manifest)
    note = ('Backed up replaced files to ' + str(backup) + '. ') if backup.exists() else ''
    print(note + 'Applied: ' + ', '.join(p['id'] for p in todo) + '. Restart the Hermes gateway to load them.')
    return 0 if after['ok'] else 2


def files_of(patch_text):
    """[(path, is_new)] in a git patch."""
    files = []
    for block in re.split(r'(?m)^diff --git ', patch_text)[1:]:
        match = re.match(r'a/(\S+) b/(\S+)', block)
        files.append((match.group(2), bool(re.search(r'(?m)^new file mode', block))))
    return files


def cmd_export(args):
    tree = Path(args.tree).expanduser().resolve()
    manifest = load_manifest()
    head = git(tree, 'rev-parse', 'HEAD').stdout.strip()
    for patch in manifest['patches']:
        for spec in patch['pathspecs']:
            git(tree, 'add', '-N', '--', spec)  # make new files visible to diff
        diff = git(tree, 'diff', '--no-color', 'HEAD', '--', *patch['pathspecs'])
        if diff.returncode or not diff.stdout.strip():
            print('No changes under ' + ', '.join(patch['pathspecs']) + ' for ' + patch['id'], file=sys.stderr)
            return 2
        (PATCHES / (patch['id'] + '.patch')).write_text(diff.stdout)
        patch['files'] = [dict(path=path, new=new, sha256=sha256(tree / path)) for path, new in files_of(diff.stdout)]
    manifest['verified_with'] = sorted({*manifest.get('verified_with', []), head})
    MANIFEST.write_text(json.dumps(manifest, indent=1) + '\n')
    print('Exported ' + str(len(manifest['patches'])) + ' patches against upstream ' + head[:12])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', help='Hermes source tree (default $HERMES_SOURCE or ~/.hermes/hermes-agent)')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('status'); s.add_argument('--json', action='store_true'); s.set_defaults(run=cmd_status)
    a = sub.add_parser('apply'); a.add_argument('--dry-run', action='store_true'); a.set_defaults(run=cmd_apply)
    e = sub.add_parser('export'); e.add_argument('--tree', required=True); e.set_defaults(run=cmd_export)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == '__main__':
    sys.exit(main())
