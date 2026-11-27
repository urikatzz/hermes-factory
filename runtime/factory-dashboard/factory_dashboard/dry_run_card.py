"""Dry-run card generation: build the exact card a resume would create, without creating anything.

The production controller cannot be wrapped in one rolled-back transaction (its writes use their own BEGIN IMMEDIATE / COMMIT and refuse nesting), so the
isolation is stricter than a rollback: the live board is read once through SQLite's backup API into a scratch directory, the unmodified production controller
resumes that snapshot, and the cards it creates are read back and verified. No live task, stage, budget, event or file can change, and the gateway's dispatcher only
watches the registered live board, so no simulated card can ever be claimed. `fingerprint_*` prove it: they are taken before and after and must be equal.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import tempfile
from contextlib import closing

LOGICAL_TABLES = ('tasks', 'task_runs', 'task_events', 'task_links', 'factory_workflow_roots', 'factory_workflow_stages', 'factory_workflow_recovery',
                  'factory_workflow_events', 'factory_project_execution')
SKIP_DIRS = {'.git', 'logs', '__pycache__'}


def fingerprint_db(path):
    """A content hash of the board's logical state, read-only (the live database file itself is busy and changes bytes without changing meaning)."""
    digest = hashlib.sha256()
    counts = {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in LOGICAL_TABLES:
            if table not in names:
                continue
            rows = conn.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall() if table != 'factory_project_execution' else conn.execute(f'SELECT * FROM {table}').fetchall()
            counts[table] = len(rows)
            digest.update(table.encode())
            digest.update(json.dumps(rows, default=str, sort_keys=True).encode())
    return dict(sha256=digest.hexdigest(), rows=counts)


def fingerprint_tree(root, *, skip_names=()):
    """(relative path -> size and sha256) of every file under root, skipping VCS/log directories and named files."""
    out = {}
    root = Path(root)
    if not root.exists():
        return out
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in skip_names or name.startswith('kanban.db'):
                continue
            path = Path(current) / name
            try:
                out[str(path.relative_to(root))] = [path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()[:16]]
            except OSError:
                out[str(path.relative_to(root))] = ['unreadable', '']
    return out


def snapshot_board(db_path, scratch):
    """Copy the live board with SQLite's backup API (a consistent read) into scratch; returns the copy's path."""
    target = Path(scratch) / 'kanban.db'
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as copy:
        source.backup(copy)
    return target


def new_tasks(copy_path, known_ids):
    with closing(sqlite3.connect(copy_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute('SELECT id, assignee, status, title, body FROM tasks ORDER BY created_at, id') if r['id'] not in known_ids]


def known_task_ids(db_path):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        return {r[0] for r in conn.execute('SELECT id FROM tasks')}


CHECK_LINE = re.compile(r'`fw\.py check PROJECT_DIR ([^`]+)`')


def header_value(body, name):
    match = re.search(r'^' + name + r' ([^\s]+)', body, re.M) or re.search(r'\b' + name + r' ([^\s]+)', body)
    return match.group(1) if match else None


def parse_start_check(body):
    """The owned start-check argument list on a card, or None. Arguments are shell-split exactly as written."""
    match = CHECK_LINE.search(body)
    return shlex.split(match.group(1)) if match else None


def snapshot_manifest_sha12(path):
    import tarfile
    try:
        with tarfile.open(path, 'r:gz') as tar:
            member = tar.getmember('.factory/SHA256SUMS')
            return hashlib.sha256(tar.extractfile(member).read()).hexdigest()[:12]
    except Exception:
        return None


def verify_card(body, expected_baseline, expected_owned):
    """The facts a repair card must satisfy before an artist is dispatched on it. Every item is a separate boolean so a failure names itself."""
    args = parse_start_check(body) or []

    def option(name):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None
    owned = [p for p in (option('--owned') or '').split(',') if p]
    tgz = option('--baseline-tgz')
    checks = dict(
        header_baseline=header_value(body, 'BASELINE') == expected_baseline,
        header_manifest=header_value(body, 'MANIFEST') == expected_baseline,
        explicit_expect=option('--expect') == expected_baseline,
        snapshot_named_for_baseline=bool(tgz) and os.path.basename(tgz) == 'src-%s.tgz' % expected_baseline,
        snapshot_content_matches=bool(tgz) and snapshot_manifest_sha12(tgz) == expected_baseline,
        owned_exact=sorted(owned) == sorted(expected_owned) and len(owned) == len(set(owned)),
        owned_line_present=bool(args),
    )
    return dict(ok=all(checks.values()), checks=checks, args=args)


def run_start_check(body, fw_path, project_dir=None):
    """Run the card's exact start-check command against the real project directory (read-only for fw.py check). Returns (exit code, parsed JSON or text)."""
    args = parse_start_check(body)
    if args is None:
        return None, 'no start-check line on the card'
    directory = project_dir or re.search(r'^PROJECT_DIR (.+)$', body, re.M).group(1).strip()
    done = subprocess.run(['python3', str(fw_path), 'check', directory, *args], capture_output=True, text=True, timeout=120)
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        return done.returncode, done.stdout + done.stderr


def scratch_dir():
    return tempfile.mkdtemp(prefix='dry-run-card-')
