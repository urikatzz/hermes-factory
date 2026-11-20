#!/usr/bin/env python3
"""Run every test suite and report failures by test id; optionally prove a change adds none against a baseline git ref.

  python3 scripts/run_all_tests.py                      # run all suites, print failing ids as JSON
  python3 scripts/run_all_tests.py --baseline HEAD      # also run the same suites on a clean checkout of HEAD and diff the failures
Use the Hermes Python (PyYAML installed) so no suite is skipped: ~/.hermes/hermes-agent/venv/bin/python.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
SUITES = ('art', 'audio', 'ecc', 'factory_art_type', 'production', 'secrets', 'workflow_v2')
LINE = re.compile(r'^(FAIL|ERROR): (\S+) \(([^)]+)\)')


def run_suite(root, suite):
    folder = root / 'tests' / suite
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(root / p) for p in ('runtime/factory-dashboard', 'scripts', '.')))
    done = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', '.', '-p', 'test_*.py'], cwd=folder, env=env, capture_output=True, text=True)
    output = done.stderr + done.stdout
    failures = sorted({f'{suite}:{match.group(3).split(" ")[0]}.{match.group(2)}' for match in map(LINE.match, output.splitlines()) if match})
    ran = re.search(r'Ran (\d+) tests?', output)
    skipped = re.search(r'skipped=(\d+)', output)
    return dict(suite=suite, ran=int(ran.group(1)) if ran else 0, skipped=int(skipped.group(1)) if skipped else 0, exit=done.returncode, failures=failures)


def run_all(root):
    return [run_suite(root, suite) for suite in SUITES]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--baseline', help='git ref to run the same suites on (a temporary worktree) and compare with')
    args = parser.parse_args()
    current = run_all(REPO)
    result = dict(python=sys.version.split()[0], current=current)
    if args.baseline:
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / 'baseline'
            subprocess.run(['git', 'worktree', 'add', '--detach', str(tree), args.baseline], cwd=REPO, check=True, capture_output=True)
            try:
                baseline = run_all(tree)
            finally:
                subprocess.run(['git', 'worktree', 'remove', '--force', str(tree)], cwd=REPO, capture_output=True)
        before = {f for suite in baseline for f in suite['failures']}
        after = {f for suite in current for f in suite['failures']}
        result.update(baseline=baseline, baseline_ref=args.baseline, new_failures=sorted(after - before), fixed=sorted(before - after), preexisting=sorted(before & after))
    print(json.dumps(result, indent=2))
    if args.baseline:
        return 1 if result['new_failures'] else 0
    return 1 if any(s['failures'] for s in current) else 0


if __name__ == '__main__':
    sys.exit(main())
