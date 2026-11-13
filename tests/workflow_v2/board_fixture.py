"""Small SQLite board adapter; exercise the real state, guard and handoff code."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'runtime/factory-dashboard'))
sys.path.append(str(Path.home() / '.hermes/hermes-agent'))

from factory_dashboard.workflow_guards import controller_context
from factory_dashboard.workflow_state import WorkflowState


@dataclass
class Task:
    id: str
    title: str
    body: str
    assignee: str
    status: str
    current_run_id: int | None = None


@dataclass
class Run:
    id: int
    task_id: str
    profile: str
    claim_lock: str
    outcome: str
    summary: str
    metadata: dict


@dataclass
class Attachment:
    stored_path: str


class Board:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.conn = sqlite3.connect(self.directory / 'board.db')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,body TEXT,assignee TEXT,status TEXT,
                current_run_id INTEGER,completed_at INTEGER,result TEXT,block_kind TEXT,
                consecutive_failures INTEGER DEFAULT 0);
            CREATE TABLE task_runs(id INTEGER PRIMARY KEY,task_id TEXT,profile TEXT,claim_lock TEXT,
                outcome TEXT,summary TEXT,metadata TEXT);
            CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,run_id INTEGER,kind TEXT);
            CREATE TABLE attachments(task_id TEXT,stored_path TEXT);
        ''')
        self.cards = {}

    @contextmanager
    def write_txn(self, conn, allow_nested=False):
        with conn:
            yield

    def create_task(self, conn, **card):
        tid = f't_{len(self.cards)+1:08x}'
        self.cards[tid] = card
        conn.execute('INSERT INTO tasks(id,title,body,assignee,status) VALUES(?,?,?,?,?)',
                     (tid, card['title'], card['body'], card['assignee'], 'ready'))
        context = controller_context(conn)
        if context and context[2]:
            WorkflowState().register_stage(conn, tid, context[1], context[2], context[3], context[4])
        self._append_event(conn, tid, 'created', {})
        return tid

    def get_task(self, conn, tid):
        row = conn.execute('SELECT id,title,body,assignee,status,current_run_id FROM tasks WHERE id=?', (tid,)).fetchone()
        return Task(**dict(row)) if row else None

    def get_run(self, conn, rid):
        row = conn.execute('SELECT * FROM task_runs WHERE id=?', (rid,)).fetchone()
        return Run(**{**dict(row), 'metadata': json.loads(row['metadata'])}) if row else None

    def list_attachments(self, conn, tid):
        return [Attachment(r[0]) for r in conn.execute('SELECT stored_path FROM attachments WHERE task_id=?', (tid,))]

    def _append_event(self, conn, tid, kind, data):
        conn.execute('INSERT INTO task_events(task_id,kind) VALUES(?,?)', (tid, kind))

    def block_task(self, conn, tid, *, reason, kind, expected_run_id=None):
        conn.execute("UPDATE tasks SET status='blocked',block_kind=?,result=? WHERE id=?",(kind,reason,tid))
        self._append_event(conn,tid,'blocked',dict(reason=reason))
        return True

    def ready(self):
        return [dict(row) for row in self.conn.execute("SELECT s.* FROM factory_workflow_stages s JOIN tasks t ON t.id=s.task_id WHERE t.status='ready' ORDER BY t.rowid")]

    def complete(self, stage, **overrides):
        conn = self.conn
        tid = stage['task_id']
        task = self.get_task(conn, tid)
        kind = stage['kind']
        verdict = {'prepare': 'DONE', 'implement': 'DONE', 'repair': 'DONE', 'verify': 'PASS', 'review': 'NO_BLOCKING_FINDINGS'}[kind]
        manifest = 'abcdef123456' if kind != 'prepare' else 'none'
        metadata = dict(contract='factory-worker/v2', workflow_contract='factory-workflow/v1',
                        root=stage['root_id'], stage_key=stage['stage_key'], cycle=stage['cycle']+1,
                        stage=kind.upper(), verdict=verdict, manifest_sha12=manifest,
                        ac_ids=['AC1'], ac_results={'AC1': 'pass'}, release_audit='PASS',
                        publish_commands=['git status'], findings=[], checks_failed=0)
        report = self.directory / (stage['stage_key'] + f'-{stage["cycle"]}')
        report.mkdir(exist_ok=True)
        artifacts = []
        if kind in ('prepare', 'review', 'verify'):
            plan = report / ('RETRO.md' if stage['profile'] == 'factory-retro' else 'PLAN-REVIEW.md' if stage['stage_key'] == 'project-plan-review'
                             else 'PLAN.md' if kind == 'prepare' else 'report.md')
            plan.write_text('AC1: Expected behavior\n')
            artifacts.append(str(plan))
        if kind == 'verify':
            archive = report / ('src-' + manifest + '.tgz')
            archive.write_bytes(b'fixture')
            artifacts.append(str(archive))
        metadata['artifacts'] = artifacts
        metadata.update(overrides)
        rid = conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM task_runs').fetchone()[0]
        summary = f'VERDICT={metadata["verdict"]} STAGE={metadata["stage"]} CYCLE={metadata["cycle"]} MANIFEST={metadata["manifest_sha12"]}'
        conn.execute('INSERT INTO task_runs VALUES(?,?,?,?,?,?,?)', (rid, tid, task.assignee, 'owned', 'completed', summary, json.dumps(metadata)))
        conn.execute("UPDATE tasks SET status='done',current_run_id=? WHERE id=?", (rid, tid))
        conn.execute('UPDATE factory_workflow_stages SET active_run_id=? WHERE task_id=?', (rid, tid))
        conn.execute('INSERT INTO task_events(task_id,run_id,kind) VALUES(?,?,?)', (tid, rid, 'spawned'))
        for path in metadata['artifacts']:
            conn.execute('INSERT INTO attachments VALUES(?,?)', (tid, path))
        self._append_event(conn, tid, 'completed', {})
        conn.commit()
        return metadata
