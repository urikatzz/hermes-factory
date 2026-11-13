"""Derive views only from established identities and recorded evidence."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
import json
import re
from statistics import median
from urllib.parse import urlsplit

_TOKENS = ('input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','reasoning_tokens')
_FAILED = {'FAIL','BLOCKED','CHANGES_REQUIRED'}


def number(value):
    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0:
        return value
    return None


def timestamp(value):
    numeric=number(value)
    if numeric is not None: return numeric
    if isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None: return None
            return number(parsed.timestamp())
        except ValueError: pass
    return None


def safe_url(value):
    if not isinstance(value,str) or any(ord(c)<32 for c in value): return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError: pass
    return None


def verdict(summary):
    match=re.match(r'^VERDICT=([A-Z_]+)\b',summary or '')
    return match[1] if match else None


def recorded_effort(session):
    config=(session or {}).get('model_config') or {}
    reasoning=config.get('reasoning_config') if isinstance(config,dict) else None
    if not isinstance(reasoning,dict):return None
    if reasoning.get('enabled') is False:return 'none'
    effort=reasoning.get('effort')
    return effort if effort in ('minimal','low','medium','high','xhigh','max','ultra') else None


def is_factory_root(task):
    if (task.get('title') or '').startswith('FACTORY:'):
        return True
    skills = task.get('skills') or []
    if isinstance(skills, str):
        try:
            skills = json.loads(skills)
        except (ValueError, TypeError):
            return False
    return task.get('assignee') == 'factory-orchestrator' and isinstance(skills, list) and 'software-factory' in skills


def _stage(title):
    clean=re.sub(r'\s*\(t_[0-9a-f]+\)\s*$','',title)
    clean=re.sub(r'^\[t_[0-9a-f]+\]\s*','',clean)
    match=re.match(r'^(PLAN|IMPLEMENT|FIX|REVERIFY|VERIFY|(?:CLAUDE|CODEX|SECURITY|UX|UI) (?:RE-)?REVIEW)(?:\s+c(\d+))?(?:\s|$)',clean)
    if not match:return {'label':clean,'cycle':None,'sort':(1,0,0,clean)}
    kind,cycle=match[1],int(match[2]) if match[2] else None
    rank={'PLAN':0,'IMPLEMENT':1,'FIX':2,'CLAUDE REVIEW':3,'CODEX REVIEW':4,'SECURITY REVIEW':5,'UX REVIEW':6,'UI REVIEW':7,'VERIFY':8,'REVERIFY':8}.get(kind,5)
    return {'label':kind,'cycle':cycle,'sort':(0,cycle or (0 if kind=='PLAN' else 1),rank,clean)}


def _usage(sessions, shared_count=0):
    result={'sessions':len(sessions),'shared_sessions':shared_count}
    for field in _TOKENS:
        values=[number(s.get(field)) for s in sessions]
        known=[v for v in values if v is not None]
        result[field]=sum(known) if known else None
        result[field+'_known_sessions']=len(known)
    included=[s for s in sessions if s.get('cost_status')=='included']
    actual=[number(s.get('actual_cost_usd')) for s in sessions]
    estimated=[number(s.get('estimated_cost_usd')) for s in sessions if s.get('cost_status')!='included']
    for key,values in (('actual',actual),('estimated',estimated)):
        known=[v for v in values if v is not None]
        result[key+'_usd']=sum(known) if known else None
        result[key+'_known_sessions']=len(known)
    result['included_sessions']=len(included)
    result['unknown_actual_sessions']=sum(number(s.get('actual_cost_usd')) is None and s.get('cost_status')!='included' for s in sessions)
    return result


class ReportBuilder:
    def build(self, snapshot):
        warnings=list(snapshot.warnings)
        session_index=defaultdict(list)
        for session in snapshot.sessions: session_index[(session.get('profile'),session.get('id'))].append(session)
        runs_by_task=defaultdict(list)
        references=defaultdict(set)
        aliases=defaultdict(set)
        linked={}
        sessions={}
        for run in snapshot.runs:
            runs_by_task[run['task_id']].append(run)
            metadata=run.get('metadata') or {}
            session_id=metadata.get('worker_session_id')
            lookup=(run.get('profile'),session_id) if isinstance(session_id,str) and session_id else None
            candidates=session_index.get(lookup,[])
            if lookup and len(candidates)==1:
                session=candidates[0]
                database_id=session.get('database_identity') or session['database']
                key=(database_id,session_id)
                linked[run['id']]=key
                references[key].add((run['task_id'],run['id']))
                aliases[key].add(run.get('profile'))
                sessions.setdefault(key,session)
            elif lookup and len(candidates)>1:
                warnings.append({'source':'sessions','kind':'ambiguous_session','record':run['id']})
        shared={key for key,refs in references.items() if len(refs)>1}

        def usage_for(runs):
            keys={linked[r['id']] for r in runs if r['id'] in linked}
            result=_usage([sessions[k] for k in keys if k not in shared],len(keys & shared))
            result.update(attempts=len(runs),linked_attempts=sum(r['id'] in linked for r in runs),
                          missing_attempts=sum(r['id'] not in linked for r in runs))
            return result

        events_by_task=defaultdict(list)
        for event in snapshot.events:
            events_by_task[event['task_id']].append({'source':'kanban','event_id':str(event['id']),
                'task_id':event['task_id'],'run_id':event.get('run_id'),'kind':event.get('kind'),
                'timestamp':timestamp(event.get('created_at')),'details':event.get('payload') or {}})
        evidence_by_task=defaultdict(list)
        valid_runs={(r['task_id'],str(r['id'])) for r in snapshot.runs}
        for record in snapshot.evidence:
            identity=record.get('identity',{})
            key=(identity.get('task_id'),str(identity.get('run_id')))
            if identity.get('board')!=snapshot.board_id or key not in valid_runs:
                warnings.append({'source':'sandbox','kind':'identity_mismatch'});continue
            evidence_by_task[key[0]].append(record)
            for index,event in enumerate(record.get('events',[])):
                events_by_task[key[0]].append({'source':'sandbox','event_id':str(index),
                    'task_id':key[0],'run_id':key[1],'kind':event.get('phase'),
                    'timestamp':timestamp(event.get('timestamp')),'details':{k:v for k,v in event.items() if k!='timestamp'}})

        def event_sort(event):
            eid=event['event_id']
            return (event['timestamp'] is None,event['timestamp'] or 0,event['source'],event['task_id'],
                    int(eid) if eid.isdigit() else -1,eid)

        generated=timestamp(snapshot.generated_at)

        def duration(start,end,record):
            start,end=timestamp(start),timestamp(end)
            if start is None or end is None:return None
            if end<start:
                warnings.append({'source':'timestamps','kind':'invalid_interval','record':record});return None
            return end-start

        def task_view(task):
            runs=sorted(runs_by_task[task['id']],key=lambda r:(timestamp(r.get('started_at')) is None,timestamp(r.get('started_at')) or 0,r['id']))
            attempts=[]
            artifacts=[]
            for run in runs:
                key=linked.get(run['id'])
                session=sessions.get(key)
                metadata=run.get('metadata') or {}
                manifest=metadata.get('manifest_sha12') or metadata.get('sha12')
                if isinstance(manifest,str):artifacts.append({'run_id':run['id'],'manifest':manifest})
                attempts.append({'id':run['id'],'task_id':task['id'],'profile':run.get('profile'),
                    'status':run.get('status'),'outcome':run.get('outcome'),'verdict':verdict(run.get('summary')),
                    'summary':run.get('summary'),'error':run.get('error'),
                    'dispatch_selection':metadata.get('worker_model_selection'),
                    'started_at':timestamp(run.get('started_at')),'ended_at':timestamp(run.get('ended_at')),
                    'duration_seconds':duration(run.get('started_at'),run.get('ended_at') if run.get('ended_at') is not None else generated if run.get('status')=='running' else None,run['id']),
                    'timeout_seconds':run.get('max_runtime_seconds'),'heartbeat_at':timestamp(run.get('last_heartbeat_at')),
                    'session_id':session.get('id') if session else None,'model':session.get('model') if session else None,
                    'provider':session.get('billing_provider') if session else None,
                    'effort':recorded_effort(session),
                    'task_effort_override':task.get('reasoning_effort'),
                    'usage_state':'shared' if key in shared else 'linked' if session else 'unavailable',
                    'usage':_usage([session]) if session else _usage([])})
            latest=runs[-1] if runs else {}
            v=verdict(latest.get('summary')) or verdict(task.get('result'))
            timeline=sorted(events_by_task[task['id']],key=event_sort)
            blockers=[e for e in timeline if e['kind']=='blocked']
            block_reason=(task.get('last_failure_error') or task.get('block_kind')) if task.get('status')=='blocked' else None
            if task.get('status')=='blocked' and blockers:
                block_reason=blockers[-1]['details'].get('reason') or block_reason
            stage=_stage(task.get('title') or '')
            return {'id':task['id'],'title':task.get('title'),'status':task.get('status'),'assignee':task.get('assignee'),
                'verdict':v,'stage':{k:v for k,v in stage.items() if k!='sort'},'attempts':attempts,'timeline':timeline,
                'usage':usage_for(runs),'execution_retries':max(0,len(runs)-1),'block_reason':block_reason,
                'block_kind':task.get('block_kind'),'branch':task.get('branch_name'),
                'created_at':timestamp(task.get('created_at')),'completed_at':timestamp(task.get('completed_at')),
                'duration_seconds':duration(task.get('created_at'),task.get('completed_at') if task.get('completed_at') is not None else generated if task.get('status') not in ('done','archived') else None,task['id']),
                'artifacts':artifacts,'sandbox':evidence_by_task[task['id']]}

        roots={t['id']:t for t in snapshot.tasks if is_factory_root(t)}
        children=defaultdict(list)
        unlinked=[]
        for task in snapshot.tasks:
            if task['id'] in roots:continue
            match=re.search(r'\(t_([0-9a-f]+)\)\s*$',task.get('title') or '') or re.match(r'^\[t_([0-9a-f]+)\]\s',task.get('title') or '')
            parent='t_'+match[1] if match else None
            if parent in roots:children[parent].append(task)
            else:unlinked.append(task_view(task))
        parents=[]
        for root_id,root in roots.items():
            parent=task_view(root)
            stages=sorted(children[root_id],key=lambda t:(_stage(t.get('title') or '')['sort'],timestamp(t.get('created_at')) or 0,t['id']))
            parent['stages']=[task_view(t) for t in stages]
            all_tasks=[root,*stages]
            all_runs=[r for t in all_tasks for r in runs_by_task[t['id']]]
            parent['usage']=usage_for(all_runs)
            parent['execution_retries']=sum(max(0,len(runs_by_task[t['id']])-1) for t in stages)
            parent['fix_stages']=sum(t['stage']['label']=='FIX' for t in parent['stages'])
            parent['timeline']=sorted([e for t in all_tasks for e in events_by_task[t['id']]],key=event_sort)
            recorded=snapshot.published.get(root_id,{})
            parent['delivery']={'url':safe_url(recorded.get('url')),'state':'Recorded URL' if safe_url(recorded.get('url')) else 'Not recorded'}
            verifies=[t for t in parent['stages'] if t['stage']['label'] in ('VERIFY','REVERIFY')]
            parent['latest_verification']=verifies[-1]['verdict'] if verifies else None
            # A URL and stage verdict do not establish repository checks or merging.
            parent['verified_delivery']=False
            parents.append(parent)
        parents.sort(key=lambda t:(t['created_at'] is None,-(t['created_at'] or 0),t['id']))
        unlinked.sort(key=lambda t:t['id'])
        eligible=[t for t in roots.values() if t.get('status')!='archived']
        completed=[t for t in eligible if t.get('status')=='done']
        intervals=[duration(t.get('created_at'),t.get('completed_at'),t['id']) for t in completed]
        intervals=[x for x in intervals if x is not None]
        task_map={t['id']:t for t in snapshot.tasks}
        failed=sum(str(r.get('outcome') or '').lower() in ('fail','failed','error','blocked') or verdict(r.get('summary')) in _FAILED for r in snapshot.runs)
        coverage={'attempts':len(snapshot.runs),'linked_attempts':len(linked),
                  'missing_attempts':len(snapshot.runs)-len(linked),'shared_sessions':len(shared),'unique_sessions':len(sessions)}
        return {'schema_version':1,'board':{'id':snapshot.board_id},'generated_at':snapshot.generated_at,
            'sources':list(snapshot.sources),'warnings':warnings,'coverage':coverage,
            'summary':{'root_count':len(roots),'roots_by_status':dict(Counter(t.get('status') for t in roots.values())),
                'card_completion_rate':len(completed)/len(eligible) if eligible else None,
                'median_cycle_seconds':median(intervals) if intervals else None,
                'execution_retries':sum(p['execution_retries'] for p in parents),
                'active_attempts':sum(r.get('status')=='running' for r in snapshot.runs),
                'blocked_tasks':sum(t.get('status')=='blocked' for t in snapshot.tasks),
                'failed_attempts':failed,
                'failed_stage_verdicts_without_attempt':sum(verdict(t.get('result')) in _FAILED and not runs_by_task[t['id']] for t in task_map.values()),
                'usage':_usage(list(sessions.values()),len(shared))},
            'parents':parents,'unlinked_tasks':unlinked,
            'shared_sessions':[{'profile':sessions[k]['profile'],'profile_aliases':sorted(aliases[k]),'session_id':k[1],'database':sessions[k]['database'],
                'references':[{'task_id':t,'run_id':r} for t,r in sorted(references[k])],
                'usage':_usage([sessions[k]])} for k in sorted(shared)]}
