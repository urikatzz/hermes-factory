#!/usr/bin/env bash
# Preview by default; --apply creates missing jobs PAUSED with local-only delivery.
# Existing jobs are preserved. Webhook registration requires a tested adapter.
set -euo pipefail
TRAILZ_HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
TRAILZ_PYTHON="${TRAILZ_PYTHON:-$HOME/.hermes/hermes-agent/venv/bin/python}"
export PATH="$HOME/.local/bin:$PATH"
exec "$TRAILZ_PYTHON" - "$TRAILZ_HERMES_HOME" "$@" <<'PY'
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description='Preview Trailz jobs; --apply creates missing jobs paused.')
parser.add_argument('hermes_home', type=Path)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = args.hermes_home.expanduser().resolve()
jobs = [
    ('Community: Discord Scan #Chat', '0 5,13,20 * * *', 'trailz-community',
     'Scan Trailz Discord #chat (1303113897208709172) using trailz-community. '
     'Use the configured cursor; report missing prerequisites. Return only [SILENT] if nothing changed.'),
    ('Support: Zendesk Tickets', '0 * * * *', 'trailz-support',
     'Sweep new/open/pending support_request tickets using trailz-support. '
     'Reconcile prior notes before retries; draft locally if safe write prerequisites are unavailable. '
     'Return only [SILENT] if no action is needed.'),
]

def prepare():
    path = root / 'cron/jobs.json'
    data = json.loads(path.read_text()) if path.exists() else {'jobs': []}
    existing = data['jobs']
    missing = []
    for name, schedule, skill, prompt in jobs:
        matches = [job for job in existing if job.get('name') == name]
        if len(matches) > 1:
            raise SystemExit(f'Duplicate jobs named {name!r}; resolve them before setup.')
        if matches:
            print(f'Preserving existing job: {name}')
            continue
        if not (root / 'skills/trailz' / skill / 'SKILL.md').is_file():
            raise SystemExit(f'Missing skill: {skill}')
        print(f'Create PAUSED, delivery local: {name} ({schedule}; Hermes configured timezone)')
        missing.append((name, schedule, skill, prompt))
    return missing

if args.apply:
    # Serialize reruns of this installer; Hermes owns locking its job store.
    with (root / '.trailz-setup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name, schedule, skill, prompt in prepare():
            subprocess.run(['hermes', 'cron', 'create', schedule, prompt,
                            '--name', name, '--skill', skill, '--deliver', 'local',
                            '--paused', '--paused-reason', 'Trailz integrations require verification'],
                           check=True)
else:
    prepare()
    print('Preview only. Run with --apply to create the missing paused jobs.')
print('Before resuming: connect Discord/Zendesk, verify shared state and tools, and select delivery in Hermes.')
print('Webhook not registered: verify signature format, event payload, filtering, and serialized writes first.')
PY
