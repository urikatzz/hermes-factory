"""Narrow existing-Hermes queue adapter; never starts intake or workers."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote
from .model_policy import ConfigurationError

class HermesIntake:
    def __init__(self,board_path,board_id,repos_path,create_task,connect_board):
        self._path=Path(board_path).resolve();self._board=board_id;self._repos=Path(repos_path)
        self._create=create_task;self._connect=connect_board

    def list_projects(self):
        data=json.loads(self._repos.read_text())
        result=[]
        for alias,info in data.get('repos',{}).items():
            path=info.get('path') or info.get('dir')
            if isinstance(path,str) and Path(path).is_dir():result.append({'id':alias,'label':alias})
        return [*result,{'id':'new','label':'New project'}]

    def _lookup(self,key):
        with closing(sqlite3.connect('file:'+quote(str(self._path))+'?mode=ro',uri=True)) as c:
            row=c.execute('SELECT id FROM tasks WHERE idempotency_key=? ORDER BY created_at LIMIT 1',(key,)).fetchone()
            return row[0] if row else None

    def lookup_ticket(self,identity):return self._lookup('factory-submit-'+identity)
    def lookup_root(self,ticket_id):return self._lookup('intake-'+ticket_id) if ticket_id else None

    def cancel_unqueued(self, identity, cancel):
        # Serialize cancellation against the same board write lock used by creation.
        with closing(self._connect(self._path, board=self._board)) as conn:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT id FROM tasks WHERE idempotency_key=?', ('factory-submit-' + identity,)).fetchone()
                if row:
                    return row[0]
                cancel()
                return None

    def create_ticket(self,payload,identity):
        if payload['project'] not in {p['id'] for p in self.list_projects()}:raise ConfigurationError('Project unavailable')
        envelope = {
            'PROJECT': payload['project'], 'TYPE': payload['type'],
            'ACCEPTANCE': payload['acceptance'], 'REQUEST': payload['prompt'],
        }
        version = 'v2'
        if payload.get('workflow_id'):
            envelope['WORKFLOW'] = {'id': payload['workflow_id'], 'revision': payload['workflow_revision']}
            version = 'v3'
        body = 'FACTORY_TICKET ' + version + '\n' + json.dumps(envelope, ensure_ascii=False)
        with closing(self._connect(self._path,board=self._board)) as c:
            return self._create(c,title='TICKET: '+payload['title'],body=body,triage=True,created_by='factory-ticket',
                                idempotency_key='factory-submit-'+identity,board=self._board)
