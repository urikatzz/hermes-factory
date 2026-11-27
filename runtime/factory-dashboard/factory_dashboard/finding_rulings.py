"""Structured human rulings on reviewer findings, enforced by the gate rather than by reviewer compliance.

A ruling is a human's recorded verdict on a finding (``false_positive`` or ``accepted``), scoped to one task, one acceptance
criterion, specific files and optionally one reviewer, with the evidence behind it. It extends the scoped waiver: a waiver covers an
AC and path for the whole project and never expires; a ruling covers one task, must match the finding's claim, and is bound to the
exact content of the files it judged.

Fingerprint
    ``fingerprint(finding, task)`` identifies what a finding is about independently of the reviewer's numbering (F1, F2) and wording:
    task, acceptance criterion and cited file. Reviewers renumber and rephrase between cycles; the fingerprint does not change.

Claim terms
    Several unrelated findings can share a fingerprint (same file, same AC). A ruling therefore also lists ``claim`` terms (for example
    ["pivot", "alignment"]); a finding is covered only when its text contains at least one of them. A genuinely new defect in the
    same file and criterion has none of the terms and blocks as usual.

Material change
    When it is recorded, a ruling stores the SHA-256 of every file it covers (``paths``) and every evidence file it names (``watch``).
    Before each gate, the controller hashes them again. If any digest differs, or a file disappears, the ruling is reopened: it stops
    applying, the finding blocks again and the reopening is recorded. A reopened ruling never comes back by itself; a human records a
    new one.

Audit
    The original finding text is never edited. Each application is kept on the ruling (``applied``, once per task and cycle) and
    emitted as a ``project_ruling_applied`` event; each reopening is kept under ``reopened`` and emitted as ``project_ruling_reopened``.
"""
import hashlib
import json
import re
import time
from pathlib import Path

from .model_policy import ConfigurationError
from .project_decisions import AC_ID, AUDIT_LIMIT, CATCH_ALL, _matches, finding_file

VERDICTS = ('false_positive', 'accepted')
EVIDENCE_KINDS = ('test', 'file', 'log', 'inspection')
MAX_PATHS = 20
MAX_TERMS = 10
APPLIED = re.compile(r'(.*): dismissed by human ruling (r_[0-9a-f]{10}) \((fp_[0-9a-f]{12})\): ', re.S)


def _source(finding):
    match = re.match(r'([a-z]+(?:-[a-z]+)*):F[0-9]+\|', finding)
    return match.group(1) if match else None


def _norm_path(path):
    return path.strip().lstrip('./').replace('\\', '/')


def fingerprint(finding, task):
    """Stable identity of a finding: task, criterion and cited file. Reviewer ids, severity, line numbers and wording are excluded."""
    parts = finding.split('|', 4)
    path = finding_file(finding)
    if len(parts) != 5 or not path:
        return None
    return 'fp_' + hashlib.sha256(f'{task}|{parts[2].strip()}|{_norm_path(path)}'.encode()).hexdigest()[:12]


def digest_file(project_dir, path):
    target = Path(project_dir) / path
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _paths(value, what, required):
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value) or len(value) > MAX_PATHS:
        raise ConfigurationError(f'A ruling {what} must be a list of 1 to {MAX_PATHS} specific file paths')
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item.strip() in CATCH_ALL or any(c in item for c in '*?[') or '..' in item.split('/'):
            raise ConfigurationError(f'A ruling {what} names concrete files inside the project, not patterns')
        result.append(_norm_path(item))
    return sorted(set(result))


def normalize_rulings(items, note, project_dir, now=None):
    """Validate the ``rulings`` of a human decision and bind each to the current content of its files."""
    if not items:
        return []
    if not isinstance(items, list) or len(items) > 20:
        raise ConfigurationError('rulings must be a list of at most 20 entries')
    stamp = int(time.time() if now is None else now)
    rulings = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {'task', 'ac', 'paths', 'source', 'claim', 'verdict', 'reason', 'evidence', 'watch'}:
            raise ConfigurationError('Invalid ruling fields')
        task, ac, source, verdict, reason = item.get('task'), item.get('ac'), item.get('source'), item.get('verdict'), item.get('reason')
        if not isinstance(task, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', task):
            raise ConfigurationError('A ruling must name the task it applies to')
        if not isinstance(ac, str) or not AC_ID.fullmatch(ac):
            raise ConfigurationError('A ruling must name one acceptance criterion')
        if source is not None and (not isinstance(source, str) or not re.fullmatch(r'[a-z][a-z-]*', source)):
            raise ConfigurationError('A ruling source must be a reviewer profile name')
        if verdict not in VERDICTS:
            raise ConfigurationError('A ruling verdict must be one of: ' + ', '.join(VERDICTS))
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            raise ConfigurationError('A ruling requires a reason of at least 20 characters')
        claim = item.get('claim')
        if not isinstance(claim, list) or not claim or len(claim) > MAX_TERMS or any(not isinstance(t, str) or not re.fullmatch(r'[A-Za-z0-9_ .-]{3,40}', t.strip()) for t in claim):
            raise ConfigurationError(f'A ruling claim is a list of 1 to {MAX_TERMS} terms (3-40 characters) that the finding text must contain')
        evidence = item.get('evidence')
        if not isinstance(evidence, list) or not evidence or len(evidence) > 10:
            raise ConfigurationError('A ruling requires 1 to 10 evidence entries')
        stored_evidence = []
        for entry in evidence:
            if not isinstance(entry, dict) or set(entry) - {'kind', 'ref', 'summary'} or entry.get('kind') not in EVIDENCE_KINDS \
                    or not isinstance(entry.get('ref'), str) or not entry['ref'].strip() \
                    or not isinstance(entry.get('summary'), str) or len(entry['summary'].strip()) < 10:
                raise ConfigurationError('Each ruling evidence entry is {"kind": ' + '|'.join(EVIDENCE_KINDS) + ', "ref", "summary" (10+ characters)}')
            stored_evidence.append(dict(kind=entry['kind'], ref=entry['ref'].strip()[:500], summary=entry['summary'].strip()[:1000]))
        paths = _paths(item.get('paths'), 'paths', True)
        watch = [p for p in _paths(item.get('watch'), 'watch list', False) if p not in paths]
        digests = {}
        for path in paths + watch:
            value = digest_file(project_dir, path)
            if value is None:
                raise ConfigurationError(f'A ruling covers {path}, which does not exist in the project; it can only judge files that exist')
            digests[path] = value
        body = dict(task=task, ac=ac, paths=paths, watch=watch, source=source, claim=sorted({t.strip().lower() for t in claim}),
                    verdict=verdict, reason=reason.strip(), digests=digests)
        rid = 'r_' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:10]
        fps = sorted({fingerprint(f'x:F1|HIGH|{ac}|{p}|-', task) for p in paths})
        rulings.append(dict(id=rid, fingerprints=fps, evidence=stored_evidence, note=note.strip()[:500], recorded_at=stamp,
                            state='active', applied=[], reopened=[], **body))
    return rulings


def merge(project, new):
    """Add new rulings to the project. A new ruling with the same task, criterion and files replaces (supersedes) an older active one."""
    kept = project.setdefault('rulings', [])
    known = {r['id'] for r in kept}
    for ruling in new:
        if ruling['id'] in known:
            continue
        for old in kept:
            if old['state'] == 'active' and old['task'] == ruling['task'] and old['ac'] == ruling['ac'] and set(old['paths']) & set(ruling['paths']) \
                    and old.get('source') == ruling.get('source'):
                old['state'] = 'superseded'
                old['superseded_by'] = ruling['id']
        kept.append(ruling)
    return kept


def refresh(project, project_dir, now=None):
    """Reopen every active ruling whose covered or watched files changed since it was recorded. Returns the reopen records."""
    events = []
    for ruling in project.get('rulings', []):
        if ruling['state'] != 'active':
            continue
        changed = sorted(p for p, value in ruling['digests'].items() if digest_file(project_dir, p) != value)
        if changed:
            record = dict(ruling=ruling['id'], task=ruling['task'], ac=ruling['ac'], changed=changed, at=int(time.time() if now is None else now))
            ruling['state'] = 'reopened'
            ruling['reopened'].append(record)
            events.append(record)
    return events


def ruling_for(finding, task, rulings):
    """The active ruling that covers this finding for this task, else None."""
    fp = fingerprint(finding, task)
    if not fp:
        return None
    path = _norm_path(finding_file(finding))
    text = finding.lower()
    source = _source(finding)
    for ruling in rulings or ():
        if ruling.get('state') != 'active' or ruling['task'] != task or fp not in ruling['fingerprints']:
            continue
        if ruling.get('source') not in (None, source):
            continue
        if not any(_matches(path, p) for p in ruling['paths']):
            continue
        if any(term in text for term in ruling['claim']):
            return ruling
    return None


def dismissed_entry(finding, ruling, fp):
    return f"{finding}: dismissed by human ruling {ruling['id']} ({fp}): {ruling['verdict']}: {ruling['reason']}"


def record_applied(project, entries, task_id, cycle):
    """Keep the original finding on each ruling that was applied, once per task and cycle; return the audit entries added."""
    added = []
    by_id = {r['id']: r for r in project.get('rulings', [])}
    for entry in entries:
        match = APPLIED.match(entry)
        if not match or match.group(2) not in by_id:
            continue
        ruling = by_id[match.group(2)]
        audit = dict(task=task_id, cycle=cycle, fingerprint=match.group(3), finding=match.group(1))
        if audit not in ruling['applied'] and len(ruling['applied']) < AUDIT_LIMIT:
            ruling['applied'].append(audit)
            added.append(dict(ruling=ruling['id'], **audit))
    return added


def card_view(project, task):
    """What a reviewer or fixer of this task is shown: the rulings that bind it, with their evidence."""
    return [{k: r[k] for k in ('id', 'fingerprints', 'ac', 'paths', 'source', 'claim', 'verdict', 'reason', 'evidence', 'state')}
            for r in project.get('rulings', []) if r['task'] == task and r['state'] in ('active', 'reopened')]
