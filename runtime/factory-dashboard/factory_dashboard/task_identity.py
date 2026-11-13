"""Established Factory task identity; prompt/body text never selects a snapshot."""
import json
import re
from .model_policy import ConfigurationError


def is_root(task):
    if (task.get('title') or '').startswith('FACTORY:'):return True
    skills=task.get('skills') or []
    if isinstance(skills,str):
        try:skills=json.loads(skills)
        except ValueError:return False
    return task.get('assignee')=='factory-orchestrator' and isinstance(skills,list) and 'software-factory' in skills


def root_id(task,lookup):
    if is_root(task):return task['id']
    title=task.get('title') or ''
    prefix=re.match(r'^\[(t_[0-9a-f]+)\]\s',title)
    suffix=re.search(r'\((t_[0-9a-f]+)\)\s*$',title)
    ids={m[1] for m in (prefix,suffix) if m}
    if len(ids)>1:raise ConfigurationError('Conflicting Factory root references')
    if not ids:return None
    rid=ids.pop();root=lookup(rid)
    return rid if root and is_root(root) else None
