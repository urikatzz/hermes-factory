"""Human-approved references: authority, inspection, traceability and contradiction checks.

Authority order (highest first): human-approved decisions and references > GDD > style bible and architecture >
implementation plan > implementation and tests. A lower layer can refine a higher one but never contradict or silently drop it.
A reference carries a set of roles; one file can be an immutable visual reference that is also not a shipped production asset.
"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

from .model_policy import ConfigurationError

AUTHORITY_ORDER = ('human-approved decisions and references', 'GDD', 'style bible and architecture', 'implementation plan', 'implementation and tests')
ROLES = ('visual_reference', 'production_asset', 'immutable', 'example')
REFERENCES_SCHEMA = 'factory-references/v1'
INSPECTION_SCHEMA = 'factory-reference-inspection/v1'
REFERENCE_FILES = ('docs/references.json', 'art/references.json')
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp')
DEFAULT_TOPICS = ('composition', 'palette', 'hud', 'subjects', 'materials', 'lighting')
# Stages that decide or judge visuals must look at the images themselves.
INSPECTING_PROFILES = ('architect', 'art-director', 'art-reviewer')
PLAN_REVIEW_KEY = 'project-plan-review'
MIN_OBSERVATION = 25
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}')
# A derived rule that forbids, defers or excludes something approved is a contradiction, whatever the milestone says.
# PREFIX forms govern what follows them ("no animations", "never use gradients"); POSTPONING forms may follow the subject ("the HUD is out of scope").
_PREFIX = re.compile(r"\b(no|never|without|must not|do not|don't|forbid\w*|exclud\w*|omit\w*|avoid|ban(?:ned)?|defer\w*)\b", re.I)
_POSTPONING = re.compile(r"\b(out of scope|later milestone|not yet|defer\w*|postpone\w*|only grey-?box|grey-?box only|until milestone)\b", re.I)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _inside(root, relative):
    if not isinstance(relative, str) or not relative.strip() or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ConfigurationError('Reference path must be relative to the project: ' + str(relative))
    path = (Path(root) / relative).resolve()
    if Path(root).resolve() not in path.parents:
        raise ConfigurationError('Reference path leaves the project: ' + relative)
    return path


def _synthesized(root):
    """Projects without a references file: an image the GDD names as the reference image is still an approved visual reference."""
    gdd = Path(root) / 'docs/GDD.md'
    found = []
    if gdd.is_file():
        for number, line in enumerate(gdd.read_text(errors='replace').splitlines(), 1):
            if not re.search(r'reference|look|direction', line, re.I):
                continue
            for match in re.finditer(r'`?((?:docs|art)/[\w./-]+\.(?:png|jpe?g|webp))`?', line, re.I):
                if match.group(1) not in [f['path'] for f in found]:
                    found.append(dict(path=match.group(1), line=number))
    result = []
    for index, item in enumerate(found, 1):
        result.append(dict(id='ref' + str(index), path=item['path'], roles=['visual_reference', 'immutable'], authority='human_approved',
                           title='Reference image named in docs/GDD.md line ' + str(item['line']), source='gdd',
                           requirements=[dict(id='V' + str(index),
                                              text='The delivered visuals follow ' + item['path'] + ': its composition, palette, HUD, subjects, materials and lighting.',
                                              keywords=[])], deferrals=[]))
    return result


def load_references(project_dir):
    """The approved references of a project with measured hashes. Returns {references, digest, source, problems}."""
    root = Path(project_dir)
    declared, source, milestone = None, None, None
    for name in REFERENCE_FILES:
        path = root / name
        if path.is_file():
            try:
                document = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise ConfigurationError('Invalid ' + name + ': ' + str(exc)) from exc
            if not isinstance(document, dict) or document.get('schema') != REFERENCES_SCHEMA or not isinstance(document.get('references'), list):
                raise ConfigurationError(name + ' must be {"schema":"' + REFERENCES_SCHEMA + '","references":[...]}')
            declared, source, milestone = document['references'], name, document.get('milestone')
            if milestone is not None and (type(milestone) is not int or milestone < 0):
                raise ConfigurationError('"milestone" must be a non-negative integer chosen by a human')
            break
    if declared is None:
        declared = _synthesized(root)
        source = 'docs/GDD.md' if declared else None
    references, problems, seen = [], [], set()
    hasher = hashlib.sha256()
    for item in declared:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not _ID.fullmatch(item['id']) or item['id'] in seen:
            raise ConfigurationError('Each reference needs a unique id of letters, digits, - or _')
        seen.add(item['id'])
        roles = item.get('roles')
        if not isinstance(roles, list) or not roles or any(r not in ROLES for r in roles) or len(set(roles)) != len(roles):
            raise ConfigurationError('Reference ' + item['id'] + ' roles must be a non-empty subset of ' + ', '.join(ROLES))
        path = _inside(root, item.get('path'))
        if not path.is_file():
            raise ConfigurationError('Reference file is missing: ' + str(item.get('path')))
        sha = _digest(path)
        if item.get('sha256') and item['sha256'] != sha:
            problems.append('Reference ' + item['id'] + ' changed since it was approved (' + str(item['path']) + ')')
        authority = item.get('authority', 'derived')
        if authority not in ('human_approved', 'derived'):
            raise ConfigurationError('Reference ' + item['id'] + ' authority must be human_approved or derived')
        requirements = []
        for requirement in item.get('requirements', []):
            if not isinstance(requirement, dict) or not isinstance(requirement.get('id'), str) or not re.fullmatch(r'V[A-Za-z0-9_-]{0,15}', requirement['id']) \
                    or not isinstance(requirement.get('text'), str) or not requirement['text'].strip():
                raise ConfigurationError('Reference ' + item['id'] + ' requirements need an id starting with V and a text')
            keywords = [k.lower() for k in requirement.get('keywords', []) if isinstance(k, str) and k.strip()]
            introduced = requirement.get('introduced_at')
            if introduced is not None and (type(introduced) is not int or introduced < 0 or milestone is None):
                raise ConfigurationError('Requirement ' + requirement['id'] + ': "introduced_at" is a milestone number and needs a human-set top-level "milestone"')
            requirements.append(dict(id=requirement['id'], text=requirement['text'].strip(), keywords=keywords, introduced_at=introduced))
        ids = [r['id'] for r in requirements]
        if len(set(ids)) != len(ids):
            raise ConfigurationError('Duplicate requirement id in reference ' + item['id'])
        deferrals = []
        for deferral in item.get('deferrals', []):
            if not isinstance(deferral, dict) or deferral.get('requirement') not in ids or deferral.get('approved_by') != 'human' \
                    or not str(deferral.get('reason', '')).strip() or not str(deferral.get('until', '')).strip():
                raise ConfigurationError('A deferral needs a requirement of this reference, approved_by "human", a reason and an "until"')
            deferrals.append(dict(requirement=deferral['requirement'], until=str(deferral['until']), reason=str(deferral['reason']).strip(), approved_by='human'))
        reference = dict(id=item['id'], path=item['path'], sha256=sha, roles=list(roles), authority=authority, title=str(item.get('title', item['id'])),
                         requirements=requirements, deferrals=deferrals, milestone=milestone,
                         approved_negations=[n.lower() for n in item.get('approved_negations', []) if isinstance(n, str) and n.strip()], topics=[t for t in item.get('topics', DEFAULT_TOPICS) if isinstance(t, str)] or list(DEFAULT_TOPICS))
        references.append(reference)
        hasher.update(json.dumps(reference, sort_keys=True).encode())
    return dict(references=references, digest=hasher.hexdigest() if references else '', source=source, problems=problems)


def authoritative(references):
    """Visual references a human approved: the source of truth for how the game must look."""
    return [r for r in references if 'visual_reference' in r['roles'] and r['authority'] == 'human_approved']


def deferred_ids(references):
    return {d['requirement'] for r in references for d in r['deferrals']}


def required_requirements(references):
    """Approved visual requirements that downstream work must deliver now.

    Everything implemented follows the approved direction. A requirement is excluded only by a human decision recorded in the references file:
    an explicit deferral, or an `introduced_at` milestone later than the human-set current `milestone` (the feature does not exist yet).
    Agents, plans and milestone names in prose never exclude anything."""
    skipped = deferred_ids(references)
    return [dict(r, reference=ref['id']) for ref in authoritative(references) for r in ref['requirements']
            if r['id'] not in skipped and (r.get('introduced_at') is None or ref.get('milestone') is None or r['introduced_at'] <= ref['milestone'])]


def view(references):
    """What a stage card shows: enough to read the reference itself and to cite its requirement ids."""
    return [dict(id=r['id'], path=r['path'], sha256=r['sha256'], roles=r['roles'], authority=r['authority'], title=r['title'],
                 requirements=[dict(id=q['id'], text=q['text'], introduced_at=q.get('introduced_at')) for q in r['requirements']], deferrals=r['deferrals'],
                 milestone=r.get('milestone'), inspect_topics=r['topics'])
            for r in references]


def must_inspect(profile, key):
    return profile in INSPECTING_PROFILES or key == PLAN_REVIEW_KEY


def vision_problem(profile, home):
    """None when the profile can open images, else why not. Reads the profile's own toolset list."""
    config = Path(home) / 'profiles' / profile / 'config.yaml'
    try:
        lines = config.read_text().splitlines()
    except OSError:
        return profile + ': profile configuration is unreadable (' + str(config) + ')'
    inside = False
    for line in lines:
        if re.match(r'platform_toolsets:\s*$', line):
            inside = True
        elif inside and re.match(r'\S', line):
            inside = False
        if inside and re.match(r'\s+-\s*vision\s*$', line):
            return None
    return profile + ' cannot inspect approved reference images: its toolsets lack "vision"'


def validate_inspection(record, references):
    """The stage proved, per approved reference, that it looked at the exact image and what it saw. Returns the record."""
    needed = authoritative(references)
    if not isinstance(record, dict) or record.get('schema') != INSPECTION_SCHEMA or not isinstance(record.get('references'), list):
        raise ConfigurationError('Invalid reference inspection record (schema ' + INSPECTION_SCHEMA + ')')
    by_id = {}
    for entry in record['references']:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or entry['id'] in by_id:
            raise ConfigurationError('Invalid or duplicate reference in the inspection record')
        by_id[entry['id']] = entry
    for reference in needed:
        entry = by_id.get(reference['id'])
        if entry is None:
            raise ConfigurationError('Approved reference ' + reference['id'] + ' (' + reference['path'] + ') was not inspected')
        if entry.get('sha256') != reference['sha256']:
            raise ConfigurationError('The inspection of ' + reference['id'] + ' is bound to a different image than the approved one')
        if entry.get('tool') != 'vision_analyze':
            raise ConfigurationError('The inspection of ' + reference['id'] + ' must name tool vision_analyze')
        observations = entry.get('observations')
        if not isinstance(observations, list):
            raise ConfigurationError('The inspection of ' + reference['id'] + ' needs observations')
        topics, texts = set(), set()
        for observation in observations:
            if not isinstance(observation, dict) or not isinstance(observation.get('topic'), str) or not isinstance(observation.get('observation'), str):
                raise ConfigurationError('Each observation is {"topic":...,"observation":...}')
            text = ' '.join(observation['observation'].split())
            if len(text) < MIN_OBSERVATION or reference['path'] in text and len(text) < 2 * MIN_OBSERVATION or text.lower() in texts:
                raise ConfigurationError('Observation about ' + observation['topic'] + ' is empty, repeated or only names the file; describe what the image shows')
            texts.add(text.lower())
            topics.add(observation['topic'].lower())
        missing = [t for t in reference['topics'] if t.lower() not in topics]
        if missing:
            raise ConfigurationError('The inspection of ' + reference['id'] + ' does not cover: ' + ', '.join(missing))
        cited = entry.get('requirement_ids')
        wanted = {q['id'] for q in reference['requirements']}
        if not isinstance(cited, list) or not wanted <= set(cited):
            raise ConfigurationError('The inspection of ' + reference['id'] + ' must cite every requirement id: ' + ', '.join(sorted(wanted)))
    return record


def _strip(line, phrases):
    """Remove the phrases a human approved as characteristics that are themselves negations (for example "no cast shadows")."""
    for phrase in phrases:
        line = re.sub(r'(?<![\w])' + re.escape(phrase) + r'(?![\w])', ' ', line, flags=re.I)
    return line


def _clauses(line, phrases=()):
    return [c for c in re.split(r'[.;]\s+|[.;]$', _strip(line, phrases)) if c.strip()]


def _forbids(clause, keyword):
    """True when the clause forbids, excludes or postpones the keyword's subject."""
    lowered = clause.lower()
    found = re.search(r'(?<![\w])' + re.escape(keyword) + r'(?:e?s)?(?![\w])', lowered)
    if not found:
        return False
    before = _PREFIX.search(clause)
    return bool((before and before.end() <= found.start()) or _POSTPONING.search(clause))


def _documents_lines(documents):
    for label, text in documents.items():
        for number, line in enumerate(str(text).splitlines(), 1):
            yield label, number, line


# Simplification vocabulary. Next to an approved requirement it is an implicit deferral: milestone scoping and "grey-box" never postpone a visual.
_SIMPLIFY = re.compile(r"\b(grey-?box\w*|gray-?box\w*|placeholder\w*|blockout\w*|block-out|stand-?ins?|flat (?:squares?|rectangles?|boxes)|solid[- ]colou?r\w*|generic|programmer art|for now|"
                       r"later milestone|until milestone \d+|polish(?:ed)? later|simplified|temporary)\b", re.I)
# Deferrals of the entire visual style need no requirement keyword: a bible or plan that declares the style itself postponed contradicts any approved visual reference.
_GLOBAL_DEFERRAL = re.compile(r"\b(grey-?box only|only grey-?box|gray-?box only|deferred look|look is deferred|no (?:new )?textures|no painted art|"
                              r"placeholder (?:art|look|visuals?|assets?)|flat (?:untextured )?(?:squares|rectangles) only)\b", re.I)
_PRESERVING = re.compile(r"\b(byte-identical|unchanged|preserv\w*|remains?|retained|not modified)\b", re.I)
_TARGETING = re.compile(r"\b(similar\w*|compar\w*|match\w*|target\w*|baseline|against|reference\w*|expected|scor\w*|threshold)\b", re.I)


def find_contradictions(references, documents, visual_documents=None):
    """Derived text that contradicts, implicitly defers or replaces an approved, currently required visual requirement.

    documents maps a label to text. kinds: `forbids` (a rule forbids, defers or excludes an approved characteristic), `implicit_deferral`
    (simplification wording such as grey-box or placeholder next to a requirement id or keyword), `derived_source` (a factory mockup used as
    the comparison target instead of the approved reference). visual_documents maps a label to the requirement ids that document carries: any
    simplification wording there is an implicit deferral. This is deliberately a floor: the plan reviewer must still audit meaning."""
    required = {r['id']: r for r in required_requirements(references)}
    authority = authoritative(references)
    approved_negations = [p for a in authority for p in a.get('approved_negations', [])]
    found = []
    seen = set()

    def add(kind, requirement, reference, keyword, label, number, line):
        key = (kind, requirement, label, number, keyword)
        if key not in seen:
            seen.add(key)
            found.append(dict(kind=kind, requirement=requirement, reference=reference, keyword=keyword, document=label, line=number,
                              text=' '.join(line.split())[:240]))

    for reference in authority:
        for requirement in reference['requirements']:
            if requirement['id'] not in required:
                continue
            for label, number, line in _documents_lines(documents):
                clauses = _clauses(line, approved_negations)
                hit = next(((k, c) for c in clauses for k in requirement['keywords'] if _forbids(c, k)), None)
                if hit:
                    add('forbids', requirement['id'], reference['id'], hit[0], label, number, line)
                names = [r'(?<![\w])' + re.escape(requirement['id']) + r'(?![\w])'] + [r'(?<![\w])' + re.escape(k) + r'(?:e?s)?(?![\w])' for k in requirement['keywords']]
                for clause in clauses:
                    simple = _SIMPLIFY.search(clause)
                    if simple and not _PRESERVING.search(clause) and any(re.search(n, clause, re.I) for n in names):
                        add('implicit_deferral', requirement['id'], reference['id'], simple.group(0).lower(), label, number, line)
    if required:
        first = next(iter(required.values()))
        for label, number, line in _documents_lines(documents):
            for clause in _clauses(line, approved_negations):
                whole = _GLOBAL_DEFERRAL.search(clause)
                if whole and not _PRESERVING.search(clause):
                    add('implicit_deferral', first['id'], first['reference'], whole.group(0).lower(), label, number, line)
    for label, ids in (visual_documents or {}).items():
        carried = [i for i in ids if i in required]
        for _, number, line in _documents_lines({label: documents.get(label, '')}):
            for clause in _clauses(line, approved_negations):
                simple = _SIMPLIFY.search(clause)
                if simple and carried and not _PRESERVING.search(clause):
                    add('implicit_deferral', carried[0], required[carried[0]]['reference'], simple.group(0).lower(), label, number, line)
    if authority and required:
        first = next(iter(required.values()))
        approved_names = [a['id'] for a in authority] + [Path(a['path']).name for a in authority]
        for derived in (r for r in references if r not in authority):
            name = Path(derived['path']).name
            for label, number, line in _documents_lines(documents):
                for clause in _clauses(line, approved_negations):
                    if name in clause and _TARGETING.search(clause) and not any(n in clause for n in approved_names):
                        add('derived_source', first['id'], first['reference'], name, label, number, line)
    return found


def validate_traceability(references, tasks, bible_contradictions=()):
    """Every undeferred approved requirement is carried by a task whose acceptance cites its id; known ids only.

    A style bible that contradicts a requirement must be amended by an artist task that carries that requirement."""
    required = {r['id'] for r in required_requirements(references)}
    known = {q['id'] for r in references for q in r['requirements']}
    carried = set()
    for task in tasks:
        ids = task.get('visual', [])
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
            raise ConfigurationError('Task ' + task['id'] + ': "visual" must be a list of requirement ids')
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise ConfigurationError('Task ' + task['id'] + ' cites unknown visual requirement(s): ' + ', '.join(unknown))
        text = ' '.join(task['acceptance'].values())
        silent = [i for i in ids if not re.search(r'\b' + re.escape(i) + r'\b', text)]
        if silent:
            raise ConfigurationError('Task ' + task['id'] + ' lists ' + ', '.join(silent) + ' in "visual" but no acceptance criterion states it')
        carried.update(ids)
    missing = sorted(required - carried)
    if missing:
        raise ConfigurationError('Approved visual requirement(s) are not traced into any task acceptance: ' + ', '.join(missing)
                                 + '. Declare each in a task "visual" list and state it in that task\'s acceptance, or ask a human for an explicit deferral.')
    for item in bible_contradictions:
        amended = any(t['owner'] == 'artist' and item['requirement'] in t.get('visual', []) and item['document'] in ' '.join(t['acceptance'].values())
                      for t in tasks)
        if not amended:
            raise ConfigurationError('The existing ' + item['document'] + ' contradicts approved requirement ' + item['requirement']
                                     + ' (line ' + str(item['line']) + ': ' + item['text'] + '). Plan an artist task that amends it, lists '
                                     + item['requirement'] + ' in "visual" and names ' + item['document'] + ' in its acceptance.')
    return sorted(carried)


HOLISTIC_VERDICTS = ('accept', 'reject')
HOLISTIC_DIMENSIONS = ('matches', 'close', 'differs')
MIN_SUMMARY = 120


def validate_reference_comparison(record, references):
    """Rendered results are judged against the original reference per requirement AND as a whole; never against a derived mockup or a score."""
    needed = authoritative(references)
    cited = record.get('references')
    if not isinstance(cited, list) or {(c.get('id'), c.get('sha256')) if isinstance(c, dict) else None for c in cited} != {(r['id'], r['sha256']) for r in needed}:
        raise ConfigurationError('comparison.json must cite every approved reference with its sha256, and only those')
    rules = ' '.join(c['rule'] for c in record['criteria'])
    missing = [r['id'] for r in required_requirements(references) if not re.search(r'\b' + re.escape(r['id']) + r'\b', rules)]
    if missing:
        raise ConfigurationError('comparison.json has no criterion for approved visual requirement(s): ' + ', '.join(missing))
    derived = [Path(r['path']).name for r in references if r not in needed]
    texts = ' '.join(c['expected'] + ' ' + c['observed'] for c in record['criteria'])
    if any(name in texts for name in derived) or any(Path(p).name in derived for p in record['evidence']):
        raise ConfigurationError('comparison.json uses a factory-made mockup as evidence or target; only the approved reference is the source of truth')
    holistic = record.get('holistic')
    if not isinstance(holistic, dict) or set(holistic) != {'verdict', 'summary', 'dimensions', 'screenshots'} or holistic['verdict'] not in HOLISTIC_VERDICTS:
        raise ConfigurationError('comparison.json needs a "holistic" judgement {verdict: accept|reject, summary, dimensions, screenshots}: requirements passing one by one does not make the whole acceptable')
    if not isinstance(holistic['summary'], str) or len(' '.join(holistic['summary'].split())) < MIN_SUMMARY:
        raise ConfigurationError('The holistic summary must describe, in at least %d characters, how the whole screenshot compares with the whole reference' % MIN_SUMMARY)
    topics = {t.lower() for r in needed for t in r['topics']}
    dimensions = holistic['dimensions']
    if not isinstance(dimensions, dict) or {k.lower() for k in dimensions} != topics or any(v not in HOLISTIC_DIMENSIONS for v in dimensions.values()):
        raise ConfigurationError('holistic.dimensions must rate each of ' + ', '.join(sorted(topics)) + ' as ' + '|'.join(HOLISTIC_DIMENSIONS))
    names = {Path(p).name for p in record['evidence']}
    shots = holistic['screenshots']
    if not isinstance(shots, list) or not shots or any(Path(str(x)).name not in names for x in shots):
        raise ConfigurationError('holistic.screenshots must name retained evidence screenshots')
    if holistic['verdict'] == 'accept' and 'differs' in dimensions.values():
        raise ConfigurationError('A holistic accept cannot rate a dimension as differs')
    overall = [c for c in record['criteria'] if c['rule'].strip().upper().startswith('HOLISTIC')]
    if len(overall) != 1 or (overall[0]['outcome'] == 'pass') != (holistic['verdict'] == 'accept'):
        raise ConfigurationError('comparison.json needs exactly one criterion whose rule starts with HOLISTIC and whose outcome equals the holistic verdict')
    return record


def vision_proof(profile, session_id, home, wanted):
    """Which of the wanted images the stage really opened with vision_analyze: {label: path} -> list of labels with no successful call.

    Reads the worker's own session log (the profile's state.db). A correctly shaped JSON file is not evidence; a successful tool call on that
    exact file (same path or same bytes) is."""
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,64}', session_id):
        raise ConfigurationError('The stage reported no worker session, so its image inspection cannot be verified')
    database = Path(home) / 'profiles' / profile / 'state.db'
    try:
        connection = sqlite3.connect('file:' + quote(str(database)) + '?mode=ro', uri=True)
        try:
            rows = connection.execute('SELECT role,tool_calls,tool_call_id,tool_name,content FROM messages WHERE session_id=? ORDER BY id', (session_id,)).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ConfigurationError('The worker session log is unreadable (' + str(database) + '): ' + str(exc)) from exc
    requested, viewed = {}, []
    for role, calls, call_id, tool_name, content in rows:
        if role == 'assistant' and calls:
            try:
                for call in json.loads(calls):
                    if call.get('function', {}).get('name') == 'vision_analyze':
                        arguments = json.loads(call['function'].get('arguments') or '{}')
                        requested[call.get('id') or call.get('call_id')] = arguments.get('image_url') or arguments.get('image') or arguments.get('path')
            except (ValueError, AttributeError, TypeError):
                continue
        elif role == 'tool' and tool_name == 'vision_analyze' and call_id in requested and requested[call_id]:
            if '"success": false' not in (content or '')[:400] and '"error"' not in (content or '')[:60]:
                viewed.append(str(requested[call_id]))
    digests = {}

    def same(seen, wanted_path):
        try:
            if Path(seen).resolve() == Path(wanted_path).resolve():
                return True
            if Path(seen).is_file():
                digests.setdefault(seen, _digest(seen))
                digests.setdefault(str(wanted_path), _digest(wanted_path))
                return digests[seen] == digests[str(wanted_path)]
        except OSError:
            return False
        return False

    return [label for label, path in wanted.items() if not any(same(seen, path) for seen in viewed)]
