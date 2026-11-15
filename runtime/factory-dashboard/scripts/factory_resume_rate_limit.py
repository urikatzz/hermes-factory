#!/usr/bin/env python3
"""Auto-resume Factory workflow roots that paused only because a provider rate limit hit (no LLM, zero tokens).

A project root whose stage worker died on HTTP 429 / usage limit is parked as infrastructure-blocked. This job retries it
through the supported controller resume (never by editing the board) after a cool-down, a bounded number of times.
Human gates (plan approval), real defects and non-rate-limit blocks are left alone. Prints one line per action.
Usage: factory_resume_rate_limit.py [--dry-run]"""
import json, os, re, sqlite3, subprocess, sys, time
from pathlib import Path

HOME = Path(os.environ.get('HERMES_HOME', Path.home() / '.hermes'))
DB = HOME / 'kanban.db'
STATE = HOME / 'state/factory/rate-limit-resume.json'
RESUME = HOME / 'factory-dashboard/scripts/resume_factory_workflow.py'
PYTHON = HOME / 'hermes-agent/venv/bin/python'
LIMIT = re.compile(r'rate.?limit|HTTP 429|usage limit|too many requests|overloaded', re.I)
COOLDOWN = 600          # seconds between resumes of one root
MIN_AGE = 300           # seconds the latest rate-limit crash must have aged before the first retry
MAX_RESUMES = 24        # per root (about 4 hours of retries at the cool-down)
DRY = '--dry-run' in sys.argv


def main():
    if not DB.exists():
        return
    try:
        st = json.loads(STATE.read_text())
    except (OSError, ValueError):
        st = {}
    now = time.time()
    out = []
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=10)
    try:
        roots = conn.execute("SELECT root_id FROM factory_workflow_roots WHERE phase='blocked'").fetchall()
        for (root,) in roots:
            row = conn.execute('SELECT document FROM factory_project_execution WHERE root_id=?', (root,)).fetchone()
            task = conn.execute('SELECT status FROM tasks WHERE id=?', (root,)).fetchone()
            if not row or not task or task[0] == 'archived':
                continue
            project = json.loads(row[0])
            if project.get('awaiting') or project.get('terminal', {}).get('phase') != 'blocked':
                continue   # human gate or not an infrastructure block
            ev = conn.execute("SELECT e.payload, e.created_at FROM task_events e JOIN tasks t ON t.id=e.task_id "
                              "WHERE t.title LIKE ? AND e.kind IN ('crashed','gave_up') ORDER BY e.created_at DESC, e.rowid DESC LIMIT 1",
                              (f'%({root})%',)).fetchone()
            if not ev or not LIMIT.search(ev[0] or ''):
                continue   # not a rate limit: leave it to a human / the other watchdog
            entry = st.setdefault(root, {'count': 0, 'last': 0})
            if entry['count'] >= MAX_RESUMES:
                continue
            if now - ev[1] < MIN_AGE or now - entry['last'] < COOLDOWN:
                continue
            if DRY:
                out.append(f'[dry-run] would resume {root} after a provider rate limit (attempt {entry["count"] + 1})')
                continue
            res = subprocess.run([str(PYTHON), str(RESUME), '--hermes-source', str(HOME / 'hermes-agent'), '--board-db', str(DB),
                                  '--new-project-root', str(Path.home() / 'factory'), '--root', root, '--note',
                                  f'Auto-resume after provider rate limit (attempt {entry["count"] + 1})'],
                                 capture_output=True, text=True, timeout=120)
            entry['count'] += 1
            entry['last'] = now
            tail = (res.stdout.strip().splitlines() or [''])[-1] or (res.stderr.strip().splitlines() or [''])[-1]
            out.append(f'resumed {root} after a rate limit (attempt {entry["count"]}): {tail[:120]}')
            if entry['count'] >= MAX_RESUMES:
                out.append(f'NEEDS YOU ({root}): still rate limited after {MAX_RESUMES} automatic resumes')
    finally:
        conn.close()
    if not DRY and out:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=1))
    print('\n'.join(out))


if __name__ == '__main__':
    main()
