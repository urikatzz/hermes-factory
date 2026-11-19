"""Human decisions the controller must honour: scoped finding waivers and preserved-path constraints.

A waiver lets one named acceptance criterion pass for one named path (or narrow glob), optionally for one reviewer. It never
edits or hides the reviewer's finding: the original text stays in the gate decision and in the waiver's audit trail. There is
no global waiver; a missing criterion, a missing path or a catch-all pattern is rejected.

A constraint names paths that approved plans or the human require to stay unchanged. A repair that would have to change one is
a conflict the controller hands back to a human instead of dispatching an impossible task. Tasks may declare the same thing
with an optional ``preserve`` list in the architect's plan.
"""
import fnmatch
import hashlib
import re
import time

from .model_policy import ConfigurationError

AC_ID = re.compile(r'AC(?:[0-9]+|-GATE)')
CATCH_ALL = {'*', '**', '**/*', '*/*', '/', '.', './', '/*'}
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


def normalize_decisions(decisions, note, now=None):
    """Validate a human decision document; return {'waivers': [...], 'constraints': [...]} ready to store."""
    if decisions in (None, {}):
        return {'waivers': [], 'constraints': []}
    if not isinstance(decisions, dict) or set(decisions) - {'waivers', 'constraints'}:
        raise ConfigurationError('A decision may only contain waivers and constraints')
    stamp = int(time.time() if now is None else now)
    waivers, constraints = [], []
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
    for item in decisions.get('constraints') or []:
        if not isinstance(item, dict) or set(item) - {'preserve', 'reason'}:
            raise ConfigurationError('Invalid constraint fields')
        reason = item.get('reason')
        if not isinstance(reason, str) or len(reason.strip()) < 10:
            raise ConfigurationError('A constraint requires a reason of at least 10 characters')
        constraints.append(dict(preserve=validate_preserve(item.get('preserve')), reason=reason.strip(), source='human',
                                note=note.strip()[:500], recorded_at=stamp))
    return dict(waivers=waivers, constraints=constraints)


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


def constraints_of(project):
    """Preserved-path constraints from the approved task plan plus recorded human constraints."""
    found = [dict(preserve=t['preserve'], reason=f"task {t['id']} must leave these paths unchanged", source='plan')
             for t in project.get('tasks', []) if t.get('preserve')]
    return found + list(project.get('constraints', []))


def preserved_conflict(finding, constraints):
    """The constraint a repair of this finding would violate (the finding cites a preserved path), else None."""
    path = finding_file(finding)
    if not path:
        return None
    for constraint in constraints:
        if any(_matches(path, pattern) for pattern in constraint['preserve']):
            return constraint
    return None


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
