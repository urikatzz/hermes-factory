"""Human decisions and structured constraints the controller must honour.

Waivers
    A waiver lets one named acceptance criterion pass for one named path (or narrow glob), optionally for one reviewer. It never
    edits or hides the reviewer's finding: the original text stays in the gate decision and in the waiver's audit trail. There is no
    global waiver; a missing criterion, a missing path or a catch-all pattern is rejected.

Constraints
    Machine-readable requirements that approved plans or a human fixed, of six kinds:
      immutable     paths that must stay unchanged            (preserve: [paths])
      palette       the only colours a scope may use          (colors: ['#RRGGBB'], optional paths scope)
      layout        required geometry or arrangement          (rules: [text], optional paths scope)
      architecture  structural decisions to respect           (rules: [text], optional paths scope)
      behavior      required runtime behaviour                (rules: [text], optional paths scope)
      acceptance    criteria that must stay satisfied         (acs: ['AC8'], optional rules)
    Reviewers and fixers receive them in their cards. Only immutable paths can be checked mechanically; for the rest a reviewer or the
    conflict assessment reports ``spec_conflicts`` (a finding or repair that contradicts a constraint), which the controller treats
    as a specification conflict for a human, not as an implementation defect to spend repair budget on.

Extra repairs
    ``extra_repairs`` grants a bounded number of additional repair cycles to the task in progress, for that decision only.
    ``extra_replans`` (0 or 1 per decision) grants one additional architect replan to the current project. The grant, its reason, its
    consumption and every use are recorded under ``replan_grants``.
    ``plan_correction`` lists the current plan-review finding ids a human classifies as localized corrections (wording, metadata,
    consistency); they go through the bounded plan-correction workflow instead of an architectural replan.
    ``retry_stage: true`` re-runs only the stage the project stopped on (a stop at human_review or blocked) with a new evidence_retry row.
    The earlier row, its result and every accepted stage stay as history; the new row supersedes it. It is bounded by MAX_STAGE_RETRIES per
    stage and cycle, refused while that stage is still running, and recorded as ``human_stage_retry`` in the orchestration log.
    An exhausted repair budget always stops the task for a human (never back to the architect); ``on_exhaustion`` is accepted for old files.
    ``model_overrides`` ({profile: {provider, model, effort}}) makes later stages of that profile use another model for this project; it is
    validated against the model catalog when used and recorded under ``orchestration_log`` as ``human_model_override``.
"""
import fnmatch
import hashlib
import json
import re
import time

from .model_policy import ConfigurationError
from .task_settings import RoleSettings

AC_ID = re.compile(r'AC(?:[0-9]+|-GATE)')
HEX_COLOR = re.compile(r'#[0-9A-Fa-f]{6}')
CATCH_ALL = {'*', '**', '**/*', '*/*', '/', '.', './', '/*'}
KINDS = ('immutable', 'palette', 'layout', 'architecture', 'behavior', 'acceptance')
MAX_EXTRA_REPAIRS = 2
EXHAUSTION = ('human_review',)  # an exhausted repair budget always stops for a human; the key is kept so old decision files still load
MAX_MODEL_OVERRIDES = 4
MAX_EXTRA_REPLANS = 1
MAX_EXTRA_HANDOFF_RETRIES = 3
MAX_STAGE_RETRIES = 2  # human stage retries per stage and cycle, over the whole run
AUDIT_LIMIT = 50


def _pattern(value, what):
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f'A {what} requires a path or pattern')
    text = value.strip()
    if text in CATCH_ALL or not re.search(r'[A-Za-z0-9_]', text):
        raise ConfigurationError(f'A {what} must name specific paths, not a catch-all pattern')
    return text


def validate_preserve(value):
    """Optional ``preserve`` list on a task or constraint: specific paths or narrow globs."""
    if value is None:
        return []
    if not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value):
        raise ConfigurationError('preserve must be a non-empty list of paths')
    return [_pattern(v, 'preserved path') for v in value]


def _text_list(value, what):
    if not isinstance(value, list) or not value or len(value) > 20 or any(not isinstance(v, str) or not 5 <= len(v.strip()) <= 500 for v in value):
        raise ConfigurationError(f'{what} must be a list of 1 to 20 statements of 5 to 500 characters')
    return [v.strip() for v in value]


def normalize_constraint(item, source='human', note='', stamp=0):
    """Validate one constraint document and return it in stored form (with a stable id)."""
    if not isinstance(item, dict) or set(item) - {'kind', 'reason', 'preserve', 'paths', 'colors', 'rules', 'acs'}:
        raise ConfigurationError('Invalid constraint fields')
    kind = item.get('kind', 'immutable' if 'preserve' in item else None)
    if kind not in KINDS:
        raise ConfigurationError('A constraint kind must be one of: ' + ', '.join(KINDS))
    reason = item.get('reason')
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ConfigurationError('A constraint requires a reason of at least 10 characters')
    if item.get('paths') is not None and not isinstance(item['paths'], list):
        raise ConfigurationError('Constraint paths must be a list')
    paths = [_pattern(p, 'constraint scope') for p in item['paths']] if item.get('paths') else []
    stored = dict(kind=kind, reason=reason.strip(), preserve=[], paths=paths, colors=[], rules=[], acs=[])
    if kind == 'immutable':
        stored['preserve'] = validate_preserve(item.get('preserve'))
        if not stored['preserve']:
            raise ConfigurationError('An immutable constraint requires preserve paths')
    elif kind == 'palette':
        colors = item.get('colors')
        if not isinstance(colors, list) or not colors or any(not isinstance(c, str) or not HEX_COLOR.fullmatch(c) for c in colors):
            raise ConfigurationError('A palette constraint requires a list of #RRGGBB colors')
        stored['colors'] = sorted({c.upper() for c in colors})
    elif kind == 'acceptance':
        acs = item.get('acs')
        if not isinstance(acs, list) or not acs or any(not isinstance(a, str) or not AC_ID.fullmatch(a) for a in acs):
            raise ConfigurationError('An acceptance constraint requires acceptance IDs')
        stored['acs'] = sorted(set(acs))
        stored['rules'] = _text_list(item['rules'], 'rules') if item.get('rules') else []
    else:
        stored['rules'] = _text_list(item.get('rules'), 'rules')
    digest = hashlib.sha256(json.dumps(stored, sort_keys=True).encode()).hexdigest()[:8]
    return dict(id='c_' + digest, source=source, note=note.strip()[:500], recorded_at=stamp, **stored)


def validate_plan_constraints(value):
    """Optional top-level ``constraints`` list in the architect's plan."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 40:
        raise ConfigurationError('Plan constraints must be a list of at most 40 entries')
    return [normalize_constraint(item, source='plan') for item in value]


def normalize_decisions(decisions, note, now=None):
    """Validate a human decision document; return it ready to store."""
    empty = dict(waivers=[], constraints=[], extra_repairs=0, extra_replans=0, extra_handoff_retries=0, on_exhaustion=None, plan_correction=[], retry_stage=False, model_overrides={})
    if decisions in (None, {}):
        return empty
    if not isinstance(decisions, dict) or set(decisions) - {'waivers', 'constraints', 'extra_repairs', 'extra_replans', 'extra_handoff_retries', 'on_exhaustion', 'plan_correction', 'retry_stage', 'model_overrides'}:
        raise ConfigurationError('A decision may only contain waivers, constraints, extra_repairs, extra_replans, extra_handoff_retries, on_exhaustion, plan_correction, retry_stage and model_overrides')
    stamp = int(time.time() if now is None else now)
    waivers = []
    for item in decisions.get('waivers') or []:
        if not isinstance(item, dict) or set(item) - {'ac', 'path', 'source', 'reason'}:
            raise ConfigurationError('Invalid waiver fields')
        ac, reason, source = item.get('ac'), item.get('reason'), item.get('source')
        if not isinstance(ac, str) or not AC_ID.fullmatch(ac):
            raise ConfigurationError('A waiver must name one acceptance criterion')
        if not isinstance(reason, str) or len(reason.strip()) < 10:
            raise ConfigurationError('A waiver requires a reason of at least 10 characters')
        if source is not None and (not isinstance(source, str) or not re.fullmatch(r'[a-z][a-z-]*', source)):
            raise ConfigurationError('A waiver source must be a reviewer profile name')
        path = _pattern(item.get('path'), 'waiver')
        wid = 'w_' + hashlib.sha256(f'{ac}|{path}|{source}|{reason}'.encode()).hexdigest()[:8]
        waivers.append(dict(id=wid, ac=ac, path=path, source=source, reason=reason.strip(), note=note.strip()[:500],
                            recorded_at=stamp, applied=[]))
    constraints = [normalize_constraint(item, 'human', note, stamp) for item in decisions.get('constraints') or []]
    extra = decisions.get('extra_repairs', 0)
    if type(extra) is not int or not 0 <= extra <= MAX_EXTRA_REPAIRS:
        raise ConfigurationError(f'extra_repairs must be an integer from 0 to {MAX_EXTRA_REPAIRS}')
    on_exhaustion = decisions.get('on_exhaustion')
    if on_exhaustion is not None and on_exhaustion not in EXHAUSTION:
        raise ConfigurationError('on_exhaustion must be one of: ' + ', '.join(EXHAUSTION))
    extra_replans = decisions.get('extra_replans', 0)
    if type(extra_replans) is not int or not 0 <= extra_replans <= MAX_EXTRA_REPLANS:
        raise ConfigurationError(f'extra_replans must be an integer from 0 to {MAX_EXTRA_REPLANS} per decision')
    extra_handoff = decisions.get('extra_handoff_retries', 0)
    if type(extra_handoff) is not int or not 0 <= extra_handoff <= MAX_EXTRA_HANDOFF_RETRIES:
        raise ConfigurationError(f'extra_handoff_retries must be an integer from 0 to {MAX_EXTRA_HANDOFF_RETRIES}')
    correction = decisions.get('plan_correction') or []
    if not isinstance(correction, list) or len(correction) > 20 or any(not isinstance(i, str) or not re.fullmatch(r'F[0-9]{1,3}', i) for i in correction):
        raise ConfigurationError('plan_correction must list plan-review finding ids such as F1')
    overrides = decisions.get('model_overrides') or {}
    if not isinstance(overrides, dict) or len(overrides) > MAX_MODEL_OVERRIDES:
        raise ConfigurationError(f'model_overrides maps at most {MAX_MODEL_OVERRIDES} profiles to {{"provider","model","effort"}}')
    model_overrides = {}
    for profile, spec in overrides.items():
        if spec is None and isinstance(profile, str) and re.fullmatch(r'[a-z][a-z-]*', profile):
            model_overrides[profile] = None   # drop this project's override: the profile's own model applies again
            continue
        if not isinstance(profile, str) or not re.fullmatch(r'[a-z][a-z-]*', profile) or not isinstance(spec, dict) \
                or set(spec) - {'provider', 'model', 'effort'} or not {'provider', 'model'} <= set(spec):
            raise ConfigurationError('Each model override is {"provider": ..., "model": ..., "effort": optional} for one profile name')
        chosen = RoleSettings(spec['provider'], spec['model'], spec.get('effort', 'high'))  # shape check; the catalog validates it when it is used
        model_overrides[profile] = dict(provider=chosen.provider, model=chosen.model, effort=chosen.effort)
    retry_stage = decisions.get('retry_stage', False)
    if type(retry_stage) is not bool:
        raise ConfigurationError('retry_stage must be true or false')
    if (extra or extra_replans or extra_handoff or on_exhaustion or correction or retry_stage or model_overrides) and not note.strip():
        raise ConfigurationError('Granting repairs or changing exhaustion handling requires a recorded note')
    return dict(waivers=waivers, constraints=constraints, extra_repairs=extra, extra_replans=extra_replans, extra_handoff_retries=extra_handoff, on_exhaustion=on_exhaustion, plan_correction=sorted(set(correction)), retry_stage=retry_stage, model_overrides=model_overrides)


def finding_file(finding):
    """The file a finding cites: 'profile:F1|HIGH|AC10|path[:line-or-symbol]|text' -> 'path'."""
    parts = finding.split('|', 4)
    if len(parts) != 5:
        return None
    path = parts[3].strip().split(':', 1)[0].strip()
    return path if path and path != '-' else None


def _matches(path, pattern):
    return fnmatch.fnmatchcase(path, pattern) or path == pattern or path.endswith('/' + pattern.lstrip('/'))


def waiver_for(finding, waivers):
    """The waiver that covers this finding (same criterion, matching path, matching reviewer when named), else None."""
    parts = finding.split('|', 4)
    path = finding_file(finding)
    if len(parts) != 5 or not path:
        return None
    source = finding.split(':', 1)[0] if re.match(r'[a-z]+(?:-[a-z]+)*:F[0-9]+\|', finding) else None
    for waiver in waivers or ():
        if parts[2] == waiver['ac'] and _matches(path, waiver['path']) and waiver.get('source') in (None, source):
            return waiver
    return None


def constraint_view(constraint):
    """A stored constraint in the current shape (older decisions stored only preserve + reason)."""
    if 'kind' in constraint and 'id' in constraint:
        return constraint
    legacy = dict(kind='immutable', reason=constraint.get('reason', 'preserved path'), preserve=list(constraint.get('preserve', [])),
                  paths=[], colors=[], rules=[], acs=[])
    digest = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()[:8]
    return {**constraint, **legacy, 'id': 'c_' + digest}


def constraints_of(project):
    """Every constraint in force: task ``preserve`` lists, the plan's structured constraints and recorded human constraints."""
    found = []
    for task in project.get('tasks', []):
        if task.get('preserve'):
            found.append(constraint_view(dict(preserve=task['preserve'], reason=f"task {task['id']} must leave these paths unchanged", source='plan')))
    found += [constraint_view(c) for c in project.get('plan_constraints', [])]
    found += [constraint_view(c) for c in project.get('constraints', [])]
    return list({c['id']: c for c in found}.values())


def preserved_conflict(finding, constraints):
    """The immutable constraint a repair of this finding would violate (the finding cites a preserved path), else None."""
    path = finding_file(finding)
    if not path:
        return None
    for constraint in constraints:
        if constraint.get('kind', 'immutable') == 'immutable' and any(_matches(path, p) for p in constraint.get('preserve', [])):
            return constraint
    return None


def relevant_constraints(finding, constraints):
    """Non-mechanical constraints a repair of this finding could plausibly contradict: same scope path, same criterion or unscoped."""
    path, parts = finding_file(finding), finding.split('|', 4)
    ac = parts[2] if len(parts) == 5 else None
    result = []
    for constraint in constraints:
        kind = constraint.get('kind', 'immutable')
        if kind == 'immutable':
            continue
        scoped = constraint.get('paths') or []
        if kind == 'acceptance' and ac in constraint.get('acs', []):
            result.append(constraint)
        elif scoped and path and any(_matches(path, p) for p in scoped):
            result.append(constraint)
        elif not scoped and kind != 'acceptance':
            result.append(constraint)
    return result


def validate_spec_conflicts(metadata):
    """Shape of the optional ``spec_conflicts`` a worker reports: [{constraint, reason, finding?}]. Returns the normalized list."""
    value = metadata.get('spec_conflicts')
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ConfigurationError('Invalid spec_conflicts')
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {'constraint', 'reason', 'finding'}:
            raise ConfigurationError('Invalid spec_conflicts entry')
        constraint, reason, finding = item.get('constraint'), item.get('reason'), item.get('finding')
        if not isinstance(constraint, str) or not re.fullmatch(r'c_[0-9a-f]{8}', constraint):
            raise ConfigurationError('spec_conflicts must name a constraint ID')
        if not isinstance(reason, str) or len(reason.strip()) < 10:
            raise ConfigurationError('spec_conflicts needs a reason')
        if finding is not None and not isinstance(finding, str):
            raise ConfigurationError('Invalid spec_conflicts finding')
        result.append(dict(constraint=constraint, reason=reason.strip(), finding=finding))
    return result


def record_applied(project, entries, task_id, cycle):
    """Keep the original finding on each waiver that was applied, once per task and cycle; return the audit entries added."""
    added = []
    for entry in entries:
        match = re.match(r'(.*): waived by human decision (w_[0-9a-f]{8}): ', entry, re.S)
        if not match:
            continue
        for waiver in project.get('waivers', []):
            if waiver['id'] == match.group(2):
                audit = dict(task=task_id, cycle=cycle, finding=match.group(1))
                if audit not in waiver['applied'] and len(waiver['applied']) < AUDIT_LIMIT:
                    waiver['applied'].append(audit)
                    added.append(dict(waiver=waiver['id'], **audit))
    return added
