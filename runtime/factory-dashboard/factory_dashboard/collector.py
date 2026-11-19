"""Read explicitly selected databases and evidence; never invoke Hermes itself."""
from datetime import datetime, timezone
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import sqlite3

from .models import Snapshot

_TASK = 'id title skills reasoning_effort status assignee created_at started_at completed_at current_run_id last_failure_error block_kind branch_name result max_runtime_seconds'.split()
_RUN = 'id task_id profile status started_at ended_at outcome summary error metadata max_runtime_seconds last_heartbeat_at'.split()
_EVENT = 'id task_id run_id kind created_at payload'.split()
_SESSION = 'id model model_config billing_provider input_tokens output_tokens cache_read_tokens cache_write_tokens reasoning_tokens estimated_cost_usd actual_cost_usd cost_status cost_source'.split()
_REQUIRED = {'tasks': {'id','title','status','assignee','created_at'},
             'task_runs': {'id','task_id','profile','metadata','status','started_at','ended_at','outcome','summary','error'},
             'task_events': set(_EVENT)}


def _project_header(body):
    """Project directory and mode named in a Factory task header; empty for other tasks."""
    header = (body or '').partition('REQUEST:')[0]
    fields = {}
    for line in header.splitlines():
        key, sep, value = line.partition(':')
        if sep:
            fields[key.strip()] = value.strip()
    directory = fields.get('PROJECT_DIR') or fields.get('PROJECT') or ''
    return {'project_dir': directory if directory.startswith('/') else None, 'project_mode': fields.get('PROJECT_MODE')}


def now():
    return datetime.now(timezone.utc).isoformat()


def strict_json(text):
    def reject_constant(value):
        raise ValueError('Nonfinite JSON constant')
    def finite_float(value):
        parsed=float(value)
        if not math.isfinite(parsed):
            raise ValueError('Nonfinite JSON number')
        return parsed
    return json.loads(text,parse_constant=reject_constant,parse_float=finite_float)


class SourceReadError(RuntimeError):
    """The selected board cannot supply a supported snapshot."""


def _has_symlink(path):
    return any(p.is_symlink() for p in (path, *path.parents))


class SnapshotCollector:
    def __init__(self, source_paths):
        def source_file(path):
            return path.parent.resolve() / path.name if path is not None else None
        self._paths = replace(source_paths, board_db=source_file(source_paths.board_db),
            hermes_home=source_paths.hermes_home.resolve(), published_state=source_file(source_paths.published_state),
            evidence_root=source_file(source_paths.evidence_root))

    def collect(self):
        # All per-collection state is local, so the collector can be reused.
        sources, warnings = [], []

        def warn(source, kind, record=None):
            warnings.append({'source':str(source), 'kind':kind, 'record':record})

        def database(path, selections, required, optional=False):
            source = {'path':str(path), 'read_at':now(), 'status':'ok'}
            sources.append(source)
            try:
                if _has_symlink(path):
                    raise ValueError('Symlinked database path')
                info=path.stat()
                identity=f'{info.st_dev}:{info.st_ino}'
                source['database_identity']=identity
                conn = sqlite3.connect(path.absolute().as_uri()+'?mode=ro', uri=True, timeout=2)
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute('PRAGMA query_only=ON')
                    conn.execute('BEGIN')
                    result = {}
                    for table, selected in selections.items():
                        columns = {r['name'] for r in conn.execute('PRAGMA table_info('+table+')')}
                        if not required[table] <= columns:
                            raise ValueError('Unsupported schema: '+table)
                        missing = set(selected)-columns
                        if missing:
                            warn(path,'missing_columns:'+table+':'+','.join(sorted(missing)))
                        # Names here are fixed code literals; no metadata enters SQL.
                        actual = [c for c in selected if c in columns]
                        # Only the request header of a task body is read, to learn which project directory a run works in.
                        head = ',substr(body,1,2000) AS _body_head' if table == 'tasks' and 'body' in columns else ''
                        rows = [dict(r) for r in conn.execute('SELECT '+','.join(actual)+head+' FROM '+table)]
                        result[table] = [{c:r.get(c) for c in selected} for r in rows]
                        if head:
                            for out, row in zip(result[table], rows):
                                out.update(_project_header(row.get('_body_head')))
                    after=path.stat()
                    if (after.st_dev,after.st_ino)!=(info.st_dev,info.st_ino):
                        raise OSError('Database identity changed during collection')
                    result['_database_identity']=identity
                    return result
                finally:
                    conn.close()
            except (OSError, ValueError, sqlite3.Error) as error:
                source['status'] = 'unavailable'
                source['error'] = type(error).__name__
                warn(path,'source_unavailable:'+type(error).__name__)
                if not optional:
                    raise SourceReadError('Cannot read supported board at '+str(path)+' ('+type(error).__name__+')') from error
                return None

        board = database(self._paths.board_db, {'tasks':_TASK,'task_runs':_RUN,'task_events':_EVENT}, _REQUIRED)
        for table, field in (('task_runs','metadata'),('task_events','payload')):
            for row in board[table]:
                try:
                    value = strict_json(row[field]) if row[field] is not None else {}
                    if not isinstance(value,dict):
                        raise ValueError('Expected object')
                    row[field] = value
                except (ValueError, TypeError):
                    warn(self._paths.board_db,'invalid_'+field,row['id'])
                    row[field] = {}
        sessions = []
        profiles = sorted({str(r['profile']) for r in board['task_runs'] if r['metadata'].get('worker_session_id')})
        for profile in profiles:
            if not re.fullmatch(r'[A-Za-z0-9_-]+',profile):
                warn('profile','invalid_profile',profile)
                continue
            home = self._paths.hermes_home
            path = home/'state.db' if profile=='default' else home/'profiles'/profile/'state.db'
            rows = database(path, {'sessions':_SESSION}, {'sessions':{'id'}}, optional=True)
            if rows:
                wanted = {r['metadata'].get('worker_session_id') for r in board['task_runs']
                          if r['profile']==profile and isinstance(r['metadata'].get('worker_session_id'),str)}
                for session in rows['sessions']:
                    if session['id'] in wanted:
                        try:
                            config=strict_json(session.get('model_config') or '{}')
                            reasoning=config.get('reasoning_config') if isinstance(config,dict) else None
                            session['model_config']={'reasoning_config':reasoning} if isinstance(reasoning,dict) else {}
                        except (ValueError,TypeError):
                            session['model_config']={}
                        sessions.append({**session,'profile':profile,'database':str(path.absolute()),
                                         'database_identity':rows['_database_identity']})
        published = {}
        p = self._paths.published_state
        if p is not None:
            sources.append({'path':str(p),'read_at':now(),'status':'ok'})
            try:
                if _has_symlink(p): raise ValueError('Symlinked state')
                data=strict_json(p.read_text())
                if not isinstance(data,dict): raise ValueError('Invalid state')
                published={k:{'url':v.get('url')} for k,v in data.items() if isinstance(v,dict)}
            except (OSError,ValueError,TypeError) as error:
                sources[-1]['status']='unavailable'
                warn(p,'source_unavailable:'+type(error).__name__)
        evidence = []
        root = self._paths.evidence_root
        if root is not None:
            sources.append({'path':str(root),'read_at':now(),'status':'ok'})
            known={(r['task_id'],str(r['id'])) for r in board['task_runs']}
            try:
                if _has_symlink(root) or not root.is_dir(): raise ValueError('Invalid evidence root')
                for directory in sorted(root.iterdir()):
                    if directory.is_symlink():
                        warn(directory,'symlink_evidence');continue
                    if not directory.is_dir(): continue
                    path=directory/'attempt.json'
                    try:
                        if path.is_symlink(): raise ValueError('Symlink evidence')
                        data=strict_json(path.read_text())
                        identity=data['identity']
                        if identity.get('board')!=self._paths.board_id or (identity.get('task_id'),str(identity.get('run_id'))) not in known:
                            raise ValueError('Evidence identity mismatch')
                        events=data.get('events',[])
                        if not isinstance(events,list) or not all(isinstance(e,dict) for e in events): raise ValueError('Invalid events')
                        fields={'timestamp','phase','exit_reason','cleanup_outcome','policy_revision','images','result_path','message'}
                        evidence.append({'identity':{k:identity.get(k) for k in ('board','task_id','run_id')},
                            'events':[{k:v for k,v in e.items() if k in fields} for e in events],
                            'result':{k:v for k,v in data.get('result',{}).items() if k in fields}})
                    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
                        warn(path,'invalid_evidence:'+type(error).__name__)
            except (OSError,ValueError) as error:
                sources[-1]['status']='unavailable';warn(root,'source_unavailable:'+type(error).__name__)
        return Snapshot(self._paths.board_id,now(),tuple(sources),tuple(board['tasks']),tuple(board['task_runs']),
                        tuple(board['task_events']),tuple(sessions),published,tuple(evidence),tuple(warnings))
