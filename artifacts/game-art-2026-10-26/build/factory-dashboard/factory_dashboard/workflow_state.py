"""Factory execution identity stored atomically beside Hermes board tasks."""
from dataclasses import asdict
import json
from .model_policy import ConfigurationError
from .task_settings_store import encode


class WorkflowState:
    @staticmethod
    def exists(conn):
        return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name='factory_workflow_roots'").fetchone())

    def initialize(self, conn):
        conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_roots(root_id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL,definition TEXT NOT NULL,phase TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT \'\')')
        conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_stages(task_id TEXT PRIMARY KEY,root_id TEXT NOT NULL,stage_key TEXT NOT NULL,kind TEXT NOT NULL,profile TEXT NOT NULL,cycle INTEGER NOT NULL,evidence_retry INTEGER NOT NULL DEFAULT 0,active_run_id INTEGER,accepted_run_id INTEGER,UNIQUE(root_id,stage_key,cycle,evidence_retry))')
        conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_recovery(root_id TEXT PRIMARY KEY,last_event INTEGER NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_events(id INTEGER PRIMARY KEY,root_id TEXT NOT NULL,kind TEXT NOT NULL,document TEXT NOT NULL)')

    def ensure_root(self, conn, root_id, binding):
        self.initialize(conn)
        from hermes_cli.kanban_db_mutation_guard import register_policy
        register_policy(conn,root_id,'factory-workflow/v1')
        register_policy(conn,'*','factory-workflow/v1')
        conn.execute("INSERT OR IGNORE INTO factory_workflow_roots(root_id,snapshot_id,definition,phase) VALUES(?,?,?,'preparing')", (root_id, binding.snapshot_id, encode(asdict(binding.definition))))
        root = self.read_root(conn, root_id)
        if root['snapshot_id'] != binding.snapshot_id:
            raise ConfigurationError('workflow snapshot identity mismatch')

    def read_root(self, conn, root_id):
        if not self.exists(conn):
            return None
        row = conn.execute('SELECT * FROM factory_workflow_roots WHERE root_id=?', (root_id,)).fetchone()
        if not row:
            return None
        return {**dict(row), 'definition': json.loads(row['definition'])}

    def stage_for_task(self, conn, task_id):
        if not self.exists(conn):
            return None
        row = conn.execute('SELECT * FROM factory_workflow_stages WHERE task_id=?', (task_id,)).fetchone()
        return dict(row) if row else None

    def register_stage(self, conn, task_id, root_id, stage, cycle, evidence_retry=0):
        from hermes_cli.kanban_db_mutation_guard import register_policy
        register_policy(conn,task_id,'factory-workflow/v1')
        conn.execute('INSERT INTO factory_workflow_stages(task_id,root_id,stage_key,kind,profile,cycle,evidence_retry) VALUES(?,?,?,?,?,?,?)', (task_id, root_id, stage.key, stage.kind, stage.profile, cycle, evidence_retry))

    def event(self, conn, root_id, kind, document):
        conn.execute('INSERT INTO factory_workflow_events(root_id,kind,document) VALUES(?,?,?)', (root_id, kind, encode(document)))

    def pending_roots(self,conn,limit=100):
        # Board events are durable across restart and include claims, failures and completion.
        return [row[0] for row in conn.execute("""
            SELECT r.root_id FROM factory_workflow_roots r
            LEFT JOIN factory_workflow_recovery c ON c.root_id=r.root_id
            WHERE r.phase NOT IN ('delivered','human_review','blocked')
            AND (c.root_id IS NULL OR EXISTS (
                SELECT 1 FROM task_events e WHERE e.id>c.last_event
                AND (e.task_id=r.root_id OR e.task_id IN (
                    SELECT task_id FROM factory_workflow_stages s WHERE s.root_id=r.root_id))))
            ORDER BY r.root_id LIMIT ?
        """,(limit,))]

    def mark_reconciled(self,conn,root_id):
        # Called under the controller write lock, after materialization. No concurrent
        # event can be acknowledged before its transition has been examined.
        last=conn.execute('SELECT COALESCE(MAX(id),0) FROM task_events').fetchone()[0]
        conn.execute('INSERT INTO factory_workflow_recovery VALUES(?,?) ON CONFLICT(root_id) DO UPDATE SET last_event=excluded.last_event',(root_id,last))
