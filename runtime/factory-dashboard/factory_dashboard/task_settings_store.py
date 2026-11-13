"""Private SQLite sidecar with immutable snapshots and durable submission identities."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid
from .model_policy import ConfigurationError
from .policy_store import RevisionConflict
from .task_settings import DefaultsRevision, RoleSettings, TaskSnapshot


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

class TaskSettingsStore:
    def __init__(self,path,*,create=True):
        self.path=Path(path).absolute()
        if self.path.is_symlink():raise ConfigurationError('Symlinked settings store')
        if create:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
            with self._connect() as c:
                if c.execute('PRAGMA user_version').fetchone()[0] > 1:
                    raise ConfigurationError('Unsupported newer settings database version')
                c.executescript('''
                CREATE TABLE IF NOT EXISTS factory_defaults(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, roles TEXT NOT NULL);
                INSERT OR IGNORE INTO factory_defaults VALUES(1,0,'{}');
                CREATE TABLE IF NOT EXISTS factory_snapshots(id TEXT PRIMARY KEY, board TEXT NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS factory_tasks(board TEXT NOT NULL,task_id TEXT NOT NULL,snapshot_id TEXT NOT NULL REFERENCES factory_snapshots(id),kind TEXT NOT NULL,PRIMARY KEY(board,task_id));
                CREATE TABLE IF NOT EXISTS factory_submissions(board TEXT NOT NULL,submission_id TEXT NOT NULL,payload TEXT NOT NULL,snapshot_id TEXT NOT NULL REFERENCES factory_snapshots(id),ticket_id TEXT,PRIMARY KEY(board,submission_id));
                CREATE TABLE IF NOT EXISTS factory_activation(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,enabled INTEGER NOT NULL);
                INSERT OR IGNORE INTO factory_activation VALUES(1,0,0);
                CREATE TABLE IF NOT EXISTS factory_cancelled(board TEXT NOT NULL, submission_id TEXT NOT NULL, PRIMARY KEY(board,submission_id));
                PRAGMA user_version=1;
                ''')

    @contextmanager
    def _connect(self):
        from urllib.parse import quote
        c=sqlite3.connect('file:'+quote(str(self.path))+'?mode=rw',uri=True,timeout=10)
        c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:yield c
        finally:c.close()

    @staticmethod
    def _defaults(c):
        r=c.execute('SELECT revision,roles FROM factory_defaults WHERE id=1').fetchone()
        return DefaultsRevision(r['revision'],{k:RoleSettings(**v) for k,v in json.loads(r['roles']).items()})

    def read_defaults(self):
        with self._connect() as c:return self._defaults(c)

    def seed_defaults(self,roles):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if self._defaults(c).roles:return
            c.execute('UPDATE factory_defaults SET revision=1,roles=? WHERE id=1',(encode({k:asdict(v) for k,v in roles.items()}),))

    def save_default(self,role,settings,expected_revision):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE');old=self._defaults(c)
            if type(expected_revision) is not int or old.revision!=expected_revision:raise RevisionConflict('Defaults changed; reload and review')
            if role not in old.roles:raise ConfigurationError('Unknown Factory role')
            roles=dict(old.roles);roles[role]=settings
            c.execute('UPDATE factory_defaults SET revision=revision+1,roles=? WHERE id=1',(encode({k:asdict(v) for k,v in roles.items()}),))
            return self._defaults(c)

    def _create_snapshot(self,c,board,origin,legacy=None,workflow_selection=None):
        defaults=self._defaults(c)
        if not defaults.roles:raise ConfigurationError('Factory defaults are not initialized')
        data=dict(id=str(uuid.uuid4()),board=board,defaults_revision=defaults.revision,created_at=datetime.now(timezone.utc).isoformat(),origin=origin,
                  roles={k:asdict(v) for k,v in defaults.roles.items()},legacy_card_settings={k:asdict(v) for k,v in (legacy or {}).items()})
        from .workflow_capture import WorkflowCapture
        workflow_enabled = WorkflowCapture.enabled(c)
        if not workflow_enabled and any(key in (workflow_selection or {}) for key in ('workflow_id', 'workflow_revision', 'workflow_defaults_revision')):
            raise ConfigurationError('Workflow execution is not enabled; reload task settings')
        if workflow_enabled:
            from .workflow_templates import WorkflowTemplates
            # Reuse this transaction; constructing services here would take another write lock.
            capture = WorkflowCapture(self, WorkflowTemplates(self))
            data['workflow'] = asdict(capture.preview(workflow_selection or {}, c))
        c.execute('INSERT INTO factory_snapshots VALUES(?,?,?)',(data['id'],board,encode(data)))
        return data['id']

    def capture_task(self,board,task_id,origin,legacy=None,*,workflow_selection=None):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT snapshot_id FROM factory_tasks WHERE board=? AND task_id=?',(board,task_id)).fetchone()
            if old:return old[0]
            sid=self._create_snapshot(c,board,origin,legacy,workflow_selection)
            c.execute('INSERT INTO factory_tasks VALUES(?,?,?,?)',(board,task_id,sid,'root'))
            return sid

    def prepare_submission(self,board,payload):
        identity=str(uuid.UUID(payload['submission_id']));canonical=encode(payload)
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM factory_submissions WHERE board=? AND submission_id=?',(board,identity)).fetchone()
            if old:
                if c.execute('SELECT 1 FROM factory_cancelled WHERE board=? AND submission_id=?',(board,identity)).fetchone():raise ConfigurationError('Submission was cancelled; use a new request identity')
                if old['payload']!=canonical:raise ConfigurationError('Submission identity already belongs to a different request')
                return dict(old)
            revision=payload['defaults_revision']
            if type(revision) is not int or revision!=self._defaults(c).revision:raise RevisionConflict('Defaults changed; review the task settings again')
            sid=self._create_snapshot(c,board,'submission',workflow_selection=payload)
            c.execute('INSERT INTO factory_submissions VALUES(?,?,?,?,NULL)',(board,identity,canonical,sid))
            return dict(c.execute('SELECT * FROM factory_submissions WHERE board=? AND submission_id=?',(board,identity)).fetchone())

    def read_submission(self,board,identity):
        with self._connect() as c:
            row=c.execute('SELECT * FROM factory_submissions WHERE board=? AND submission_id=?',(board,identity)).fetchone()
            if not row:return None
            return {**dict(row),'cancelled':bool(c.execute('SELECT 1 FROM factory_cancelled WHERE board=? AND submission_id=?',(board,identity)).fetchone())}

    def cancel_submission(self, board, identity):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT ticket_id FROM factory_submissions WHERE board=? AND submission_id=?',(board,identity)).fetchone()
            if not row or row[0]:raise ConfigurationError('Submission cannot be cancelled')
            c.execute('INSERT OR IGNORE INTO factory_cancelled VALUES(?,?)',(board,identity))

    def list_submissions(self,board):
        with self._connect() as c:return [dict(r) for r in c.execute('SELECT * FROM factory_submissions WHERE board=?',(board,))]

    def bind_task(self,board,task_id,snapshot_id,kind,submission_id=None):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            snap=c.execute('SELECT board FROM factory_snapshots WHERE id=?',(snapshot_id,)).fetchone()
            if not snap or snap[0]!=board:raise ConfigurationError('Snapshot belongs to a different board')
            old=c.execute('SELECT snapshot_id FROM factory_tasks WHERE board=? AND task_id=?',(board,task_id)).fetchone()
            if old and old[0]!=snapshot_id:raise ConfigurationError('Task snapshot cannot be changed')
            c.execute('INSERT OR IGNORE INTO factory_tasks VALUES(?,?,?,?)',(board,task_id,snapshot_id,kind))
            if submission_id:
                old=c.execute('SELECT ticket_id,snapshot_id FROM factory_submissions WHERE board=? AND submission_id=?',(board,submission_id)).fetchone()
                if not old or old['snapshot_id']!=snapshot_id or old['ticket_id'] not in (None,task_id):raise ConfigurationError('Submission association mismatch')
                c.execute('UPDATE factory_submissions SET ticket_id=? WHERE board=? AND submission_id=?',(task_id,board,submission_id))

    def get_snapshot(self,snapshot_id):
        with self._connect() as c:
            row=c.execute('SELECT document FROM factory_snapshots WHERE id=?',(snapshot_id,)).fetchone()
            if not row:raise ConfigurationError('Snapshot missing')
            data=json.loads(row[0])
            for key in ('roles','legacy_card_settings'):data[key]={k:RoleSettings(**v) for k,v in data[key].items()}
            if data.get('workflow'):
                from .workflow_types import WorkflowDefinition
                data['workflow'] = WorkflowDefinition.from_document(data['workflow'])
            return TaskSnapshot(**data)

    def snapshot_for_task(self,board,task_id):
        with self._connect() as c:
            row=c.execute('SELECT snapshot_id FROM factory_tasks WHERE board=? AND task_id=?',(board,task_id)).fetchone()
        return self.get_snapshot(row[0]) if row else None

    def root_for_snapshot(self, board, snapshot_id):
        with self._connect() as c:
            row = c.execute("SELECT task_id FROM factory_tasks WHERE board=? AND snapshot_id=? AND kind='root' ORDER BY rowid LIMIT 1", (board, snapshot_id)).fetchone()
            return row[0] if row else None

    def read_activation(self):
        with self._connect() as c:
            row=dict(c.execute('SELECT revision,enabled FROM factory_activation WHERE id=1').fetchone());row['enabled']=bool(row['enabled']);return row

    def set_activation(self,enabled,expected_revision):
        with self._connect() as c:
            changed=c.execute('UPDATE factory_activation SET enabled=?,revision=revision+1 WHERE id=1 AND revision=?',(int(enabled),expected_revision))
            if changed.rowcount!=1:raise RevisionConflict('Activation state changed')
