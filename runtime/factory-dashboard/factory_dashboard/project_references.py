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


def hermes_root(environ, default):
    """The Hermes home that holds profiles/<name>. A controller running inside a profile sees HERMES_HOME as <root>/profiles/<profile>; the root is two levels up."""
    home = Path(environ.get('FACTORY_HERMES_HOME') or environ.get('HERMES_HOME') or default)
    return home.parent.parent if home.parent.name == 'profiles' else home


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


MIN_FINDING = 40


def _region(region, label):
    """A normalised [x, y, width, height] box on the image (0..1): where the thing described is."""
    if not isinstance(region, list) or len(region) != 4 or any(type(v) not in (int, float) for v in region):
        raise ConfigurationError(label + ' needs a "region": [x, y, width, height] as fractions of the image (0..1) showing where it is')
    x, y, w, h = region
    if not (0 <= x < 1 and 0 <= y < 1 and 0.03 <= w <= 1 and 0.03 <= h <= 1 and x + w <= 1.001 and y + h <= 1.001):
        raise ConfigurationError(label + ' has an impossible region ' + str(region))
    return tuple(round(v, 3) for v in region)


def _grounded(regions, label, repeats=False):
    """Observations must point at different parts of the image: distinct boxes that fall in several cells of a 3x3 grid.

    Role findings may share a region (palette or composition really do concern the whole image) but at least half of them must be distinct."""
    if repeats:
        if len(set(regions)) * 2 < len(regions):
            raise ConfigurationError(label + ' reuse the same few regions; at least half of the findings must point at their own part of the image')
    elif len(set(regions)) != len(regions):
        raise ConfigurationError(label + ' repeats an identical region; each observation must point at its own part of the image')
    cells = {(min(2, int((x + w / 2) * 3)), min(2, int((y + h / 2) * 3))) for x, y, w, h in regions}
    needed = min(2, len(set(regions))) if repeats else min(3, len(regions))
    if len(cells) < needed:
        raise ConfigurationError(label + ' describes only ' + str(len(cells)) + ' area(s) of the image; they must span at least ' + str(needed) + ' cells of a 3x3 grid')


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
        topics, texts, regions = set(), set(), []
        for observation in observations:
            if not isinstance(observation, dict) or not isinstance(observation.get('topic'), str) or not isinstance(observation.get('observation'), str):
                raise ConfigurationError('Each observation is {"topic":...,"observation":...}')
            text = ' '.join(observation['observation'].split())
            if len(text) < MIN_OBSERVATION or reference['path'] in text and len(text) < 2 * MIN_OBSERVATION or text.lower() in texts:
                raise ConfigurationError('Observation about ' + observation['topic'] + ' is empty, repeated or only names the file; describe what the image shows')
            texts.add(text.lower())
            topics.add(observation['topic'].lower())
            regions.append(_region(observation.get('region'), 'Observation about ' + observation['topic']))
        missing = [t for t in reference['topics'] if t.lower() not in topics]
        if missing:
            raise ConfigurationError('The inspection of ' + reference['id'] + ' does not cover: ' + ', '.join(missing))
        _grounded(regions, 'The inspection of ' + reference['id'])
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
    """Clauses end at sentence punctuation, colons, semicolons, brackets and dashes: a negation never reaches across them."""
    return [c for c in re.split(r'\.(?=\s|$)|[;:()\[\]]|\s[-\u2013\u2014]\s', _strip(line, phrases)) if c.strip()]


# Words that start a new idea: a negation does not govern a keyword beyond one of them ("no image generation, HUD drawn as slanted ...").
_STOP = re.compile(r"\b(is|are|was|were|be|uses?|using|used|drawn|draws?|built|made|with|for|when|while|that|which|as|via|by|but|however|then|so|because|since|if|and then)\b", re.I)
MAX_REACH = 20
_NEW_CLAUSE = re.compile(r',\s*(?:the|a|an|this|that|these|those|it|they|we|you)\b', re.I)  # a comma followed by a subject starts a new clause


def _keyword(keyword):
    return re.compile(r'(?<![\w])' + re.escape(keyword) + r'(?:e?s)?(?![\w-])', re.I)


_ABSENCE = re.compile(r"\b(?:has|have|had|contains?|lacks?|lacking|missing)\s+no\b", re.I)


def _governs(clause, start):
    """True when a prohibition word before position `start` governs it: same clause, a short list of nouns in between, no new idea.

    "X has no steel grey and no ball-joint colour" reports an absence in something that exists; it is not a prohibition."""
    if _ABSENCE.search(clause):
        return False
    for match in _PREFIX.finditer(clause):
        if match.end() > start:
            break
        between = clause[match.end():start]
        if len(between.split()) <= MAX_REACH and not _STOP.search(between) and not _NEW_CLAUSE.search(between):
            return True
    return False


_REMOVING = re.compile(r"\b(remov\w*|supersed\w*|replac\w*|rewrit\w*|amend\w*|correct\w*|delet\w*|drop\w*|retir\w*|eliminat\w*|no longer|stop\w*|conflict\w*|contradict\w*|obsolete|legacy)\b", re.I)


_INSTEAD = re.compile(r"\b(?:instead of|rather than|in place of|as opposed to)\s+(?:the\s+|any\s+|old\s+|former\s+)*$", re.I)


def _rejects(clause, start, line, word):
    """Simplification wording that is negated, or sits within a few words of a removal, replacement or supersession, is a rejection of the simplification, not a deferral."""
    if _governs(clause, start):
        return True
    offset = line.find(clause)
    position = offset + start if offset >= 0 else line.lower().find(word.lower())
    if position >= 0 and _INSTEAD.search(line[max(0, position - 30):position]):
        return True
    window = line[max(0, position - 90):position + len(word) + 90] if position >= 0 else clause
    return bool(_REMOVING.search(window))


def _forbids(clause, keyword):
    """True when the clause forbids, excludes or postpones the keyword's subject."""
    found = _keyword(keyword).search(clause)
    if not found:
        return False
    return _governs(clause, found.start()) or bool(_POSTPONING.search(clause))


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
_PRESERVING = re.compile(r"\b(byte-identical|unchanged|preserv\w*|remains?|retained|not modified)\b|\b(?:existing|current)\b[^.;]{0,60}\b(?:keeps?|kept|stays?|retains?)\b", re.I)
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
            text = ' '.join(line.split())[:240]
            found.append(dict(id=hashlib.sha256('|'.join((kind, requirement, text)).encode()).hexdigest()[:8], kind=kind, requirement=requirement, reference=reference,
                              keyword=keyword, document=label, line=number, text=text))

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
                    if simple and not _PRESERVING.search(clause) and not _rejects(clause, simple.start(), line, simple.group(0)) and any(re.search(n, clause, re.I) for n in names):
                        add('implicit_deferral', requirement['id'], reference['id'], simple.group(0).lower(), label, number, line)
    if required:
        first = next(iter(required.values()))
        for label, number, line in _documents_lines(documents):
            for clause in _clauses(line, approved_negations):
                whole = _GLOBAL_DEFERRAL.search(clause)
                if whole and not _PRESERVING.search(clause) and (whole.group(0).lower().startswith('no ') or not _rejects(clause, whole.start(), line, whole.group(0))):
                    add('implicit_deferral', first['id'], first['reference'], whole.group(0).lower(), label, number, line)
    for label, ids in (visual_documents or {}).items():
        carried = [i for i in ids if i in required]
        for _, number, line in _documents_lines({label: documents.get(label, '')}):
            for clause in _clauses(line, approved_negations):
                simple = _SIMPLIFY.search(clause)
                if simple and carried and not _PRESERVING.search(clause) and not _rejects(clause, simple.start(), line, simple.group(0)):
                    add('implicit_deferral', carried[0], required[carried[0]]['reference'], simple.group(0).lower(), label, number, line)
    if authority and required:
        first = next(iter(required.values()))
        approved_names = [a['id'] for a in authority] + [Path(a['path']).name for a in authority]
        for derived in (r for r in references if r not in authority):
            name = Path(derived['path']).name
            for label, number, line in _documents_lines(documents):
                for clause in re.split(r'\.(?=\s|$)|;', line):  # a mockup named near a target word, brackets and colons included (JSON lines)
                    if name in clause and _TARGETING.search(clause) and not any(n in clause for n in approved_names):
                        add('derived_source', first['id'], first['reference'], name, label, number, line)
    return found


def traceability_errors(references, tasks, bible_contradictions=()):
    """Every problem of requirement traceability at once (a plan fixed one error per round would exhaust its retries).

    Every undeferred approved requirement is carried by a task whose acceptance cites its id; known ids only; and a style bible that contradicts a
    requirement must be amended by an artist task that carries that requirement."""
    required = {r['id'] for r in required_requirements(references)}
    known = {q['id'] for r in references for q in r['requirements']}
    carried, errors = set(), []
    for task in tasks:
        ids = task.get('visual', [])
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
            errors.append('Task ' + task['id'] + ': "visual" must be a list of requirement ids')
            continue
        unknown = [i for i in ids if i not in known]
        if unknown:
            errors.append('Task ' + task['id'] + ' cites unknown visual requirement(s): ' + ', '.join(unknown))
        text = ' '.join(task['acceptance'].values())
        silent = [i for i in ids if i in known and not re.search(r'\b' + re.escape(i) + r'\b', text)]
        if silent:
            errors.append('Task ' + task['id'] + ' lists ' + ', '.join(silent) + ' in "visual" but no acceptance criterion states it (write each id, for example "' + silent[0] + '", into that task\'s acceptance text)')
        carried.update(i for i in ids if i in known)
    missing = sorted(required - carried)
    if missing:
        errors.append('Approved visual requirement(s) are not traced into any task acceptance: ' + ', '.join(missing)
                      + '. Declare each in a task "visual" list and state it in that task\'s acceptance, or ask a human for an explicit deferral.')
    for item in bible_contradictions:
        amended = any(t.get('owner') == 'artist' and item['requirement'] in t.get('visual', []) and item['document'] in ' '.join(t['acceptance'].values())
                      for t in tasks)
        if not amended:
            errors.append('The existing ' + item['document'] + ' contradicts approved requirement ' + item['requirement']
                          + ' (line ' + str(item['line']) + ': ' + item['text'] + '). Plan an artist task that amends it, lists '
                          + item['requirement'] + ' in "visual" and names ' + item['document'] + ' in its acceptance.')
    return errors


def validate_traceability(references, tasks, bible_contradictions=()):
    errors = traceability_errors(references, tasks, bible_contradictions)
    if errors:
        raise ConfigurationError('; '.join(errors))
    return sorted({i for t in tasks for i in t.get('visual', []) if isinstance(i, str)})


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


def viewed_via_lint_views(name, viewed):
    """True when one of the viewed images is the art lint's own render of the asset `name`.

    The art lint writes every asset on grey and transparent backdrops to <workspace>/lint/views/<Assets__Dir__name>/grey.png. Those are deterministic
    renders of exactly that asset, so looking at one is looking at the asset even though the file name differs."""
    marker = '__' + str(name) + '/'
    return any('/lint/views/' in str(v).replace('\\', '/') and marker in str(v).replace('\\', '/') for v in viewed)


def viewed_images(profile, session_id, home):
    """Paths of every image the stage opened with a successful vision_analyze call (from the worker's own session log)."""
    return _viewed(profile, session_id, home)


def vision_proof(profile, session_id, home, wanted, scratch_ok=()):
    """Which of the wanted images the stage really opened with vision_analyze: {label: path} -> list of labels with no successful call.

    Reads the worker's own session log (the profile's state.db). A correctly shaped JSON file is not evidence; a successful tool call on that
    exact file (same path or same bytes) is. Labels in scratch_ok are files the worker itself made in its scratch workspace, which is gone by the time
    the stage is checked: for those a call on a missing file with the same name counts (the call itself is still required and must have succeeded)."""
    viewed = _viewed(profile, session_id, home)
    digests = {}

    def same(seen, wanted_path, scratch):
        try:
            if scratch and not Path(seen).exists() and Path(seen).name == Path(wanted_path).name:
                return True
            if Path(seen).resolve() == Path(wanted_path).resolve():
                return True
            if Path(seen).is_file():
                digests.setdefault(seen, _digest(seen))
                digests.setdefault(str(wanted_path), _digest(wanted_path))
                return digests[seen] == digests[str(wanted_path)]
        except OSError:
            return False
        return False

    return [label for label, path in wanted.items() if not any(same(seen, path, label in scratch_ok) for seen in viewed)]


def _viewed(profile, session_id, home):
    # Only a sanity check on the shape (the id is a bound query parameter): Hermes ids are 22 characters in older versions and
    # 'local-' plus 64 hex digits (70 characters) in current ones.
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,128}', session_id):
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
    return viewed


# What each visual role must say after looking, beyond describing the image: findings that only someone who looked and did that role's job can write.
ROLE_KINDS = {'art-director': 'achieve', 'architect': 'carry', 'plan-review': 'plan_check', 'art-reviewer': 'render_check'}
ROLE_VERDICTS = {'plan_check': ('faithful', 'weakened', 'missing'), 'render_check': ('matches', 'differs')}
APPROACHES = ('generated', 'procedural', 'hybrid')


def role_kind(profile, key):
    return ROLE_KINDS['plan-review' if key == PLAN_REVIEW_KEY else profile]


def validate_role_findings(record, references, kind, tasks=(), screenshots=(), findings=(), verdict=None):
    """Role-specific, image-grounded findings: one per demanded requirement, each tied to a region of the reference image.

    achieve (art director): how the requirement is achieved and whether by `generated`, `procedural` or `hybrid` production.
    carry (architect): the task (an id in project-plan.json whose `visual` list has the requirement) that delivers it.
    plan_check (plan reviewer): faithful | weakened | missing against the image; weakened or missing needs a blocking finding naming the id.
    render_check (art reviewer): matches | differs for a retained rendered screenshot; differs needs a blocking finding and CHANGES_REQUIRED."""
    entries = record.get('role_findings')
    if not isinstance(entries, list):
        raise ConfigurationError('reference-inspection.json needs "role_findings": one entry of kind "' + kind + '" per approved requirement')
    required = {r['id']: r for r in required_requirements(references)}
    seen, regions, texts = {}, [], set()
    task_ids = {t['id']: t for t in tasks}
    known = {q['id'] for ref in references for q in ref['requirements']}
    form = ('{"kind":"' + kind + '","requirement_id":"V..","finding":"...","region":[x,y,w,h]' + (',"subject":"..."' if kind != 'plan_check' else '')
            + (',"verdict":"' + '|'.join(ROLE_VERDICTS[kind]) + '"' if kind in ROLE_VERDICTS else '') + '}')
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigurationError('role_findings entry #%d is not an object; each is %s' % (position + 1, form))
        if entry.get('kind') != kind:
            raise ConfigurationError('role_findings entry #%d has kind %r; your role writes kind "%s": %s' % (position + 1, entry.get('kind'), kind, form))
        if entry.get('requirement_id') not in known:
            raise ConfigurationError('role_findings entry #%d names requirement_id %r, which is not one of: %s' % (position + 1, entry.get('requirement_id'), ', '.join(sorted(known))))
        if entry['requirement_id'] in seen:
            raise ConfigurationError('role_findings has two entries for %s; write exactly one per requirement' % entry['requirement_id'])
        if entry['requirement_id'] not in required:
            seen[entry['requirement_id']] = entry  # a known requirement a human scheduled for a later milestone: allowed, not demanded
            continue
        identifier = entry['requirement_id']
        text = ' '.join(str(entry.get('finding', '')).split())
        if len(text) < MIN_FINDING or text.lower() in texts or required[identifier]['text'].lower() in text.lower() or text.lower() in required[identifier]['text'].lower():
            raise ConfigurationError('The ' + kind + ' finding for ' + identifier + ' is empty, repeated or just restates the requirement; say what you saw and what follows from it')
        texts.add(text.lower())
        regions.append(_region(entry.get('region'), 'The ' + kind + ' finding for ' + identifier))
        subject = entry.get('subject')
        if kind == 'achieve' and subject not in APPROACHES:
            raise ConfigurationError('The achieve finding for ' + identifier + ' needs "subject": one of ' + ', '.join(APPROACHES) + ' (how its assets are produced)')
        if kind == 'carry' and (subject not in task_ids or identifier not in task_ids[subject].get('visual', [])):
            raise ConfigurationError('The carry finding for ' + identifier + ' must name in "subject" a task of project-plan.json whose "visual" list has ' + identifier)
        if kind == 'render_check' and subject not in set(screenshots):
            raise ConfigurationError('The render_check finding for ' + identifier + ' must name a retained rendered screenshot in "subject" (' + ', '.join(sorted(screenshots)) + ')')
        if kind in ROLE_VERDICTS:
            if entry.get('verdict') not in ROLE_VERDICTS[kind]:
                raise ConfigurationError('The ' + kind + ' finding for ' + identifier + ' needs "verdict": ' + '|'.join(ROLE_VERDICTS[kind]))
            if entry['verdict'] in ('weakened', 'missing', 'differs'):
                blocking = [f for f in findings if identifier in f and f.split('|', 4)[1] in ('BLOCKER', 'HIGH')]
                if not blocking or (kind == 'render_check' and verdict != 'CHANGES_REQUIRED'):
                    raise ConfigurationError('A ' + entry['verdict'] + ' ' + identifier + ' needs a BLOCKER/HIGH finding whose text contains the id "' + identifier + '" (write it in the finding itself, e.g. "AC3|scene|' + identifier + ': ...")' + (' and the verdict CHANGES_REQUIRED' if kind == 'render_check' else ''))
        seen[identifier] = entry
    missing = sorted(set(required) - set(seen))
    if missing:
        raise ConfigurationError('Missing ' + kind + ' findings for approved requirement(s): ' + ', '.join(missing))
    _grounded(regions, 'The ' + kind + ' findings', repeats=True)
    return entries


ART_PLAN_SECTIONS = (
    ('how the approved direction is achieved', r'achiev'),
    ('production assets to create', r'production assets?|assets? (?:to|that must)'),
    ('image generation versus procedural implementation', r'procedural'),
    ('articulation and animation of characters or subjects', r'articulat|animat'),
    ('environment composition, lighting and HUD implementation', r'environment|lighting|\bhud\b|interface'),
    ('comparison of the final rendered result with the approved reference', r'compar'),
    ('requirements active at each milestone', r'milestone'),
    ('representative mockup', r'mockup'),
)
MOCKUP_NAME = re.compile(r'plan-mockup(?:_[0-9]+)?\.png')


def validate_art_plan(text):
    """An art plan for a project with approved references must say how the look will be built and checked; the mockup is a separate artifact."""
    headings = [line.lstrip('#').strip().lower() for line in str(text).splitlines() if line.startswith('#')]
    missing = [name for name, pattern in ART_PLAN_SECTIONS if not any(re.search(pattern, h) for h in headings)]
    if missing:
        raise ConfigurationError('The art plan has no section (a markdown heading) for: ' + '; '.join(missing))


def plan_mockup(artifacts):
    """The representative mockup artifact (plan-mockup.png) if it is a real PNG of useful size, else None."""
    for artifact in artifacts:
        path = Path(artifact)
        if MOCKUP_NAME.fullmatch(path.name) and path.is_file() and not path.is_symlink():
            data = path.read_bytes()[:32]
            if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
                width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
                if width >= 640 and height >= 360 and path.stat().st_size >= 20000:
                    return path
    return None


ADJUDICATION_SCHEMA = 'factory-scan-adjudication/v1'
MIN_EXPLANATION = 40
SCAN_VERDICTS = ('contradiction', 'benign', 'ambiguous')


def _norm(text):
    return ' '.join(str(text).lower().split())


def split_explained(findings, explanations):
    """Findings in plan prose (never in operative rules) the author explained: (unresolved, explained with the explanation attached).

    An explanation quotes the flagged text (at least 15 characters of it) and says why it is not a contradiction (at least 40 characters).
    It does not dismiss the finding: it is shown to the human at the gate and ruled on by the plan reviewer."""
    unresolved, explained = [], []
    for finding in findings:
        match = next((e for e in (explanations or []) if isinstance(e, dict) and isinstance(e.get('quote'), str) and len(_norm(e['quote'])) >= 15
                      and _norm(e['quote']) in _norm(finding['text']) and len(' '.join(str(e.get('explanation', '')).split())) >= MIN_EXPLANATION
                      and e.get('requirement_id', finding['requirement']) == finding['requirement']), None)
        (explained if match else unresolved).append(dict(finding, explanation=' '.join(str(match['explanation']).split())) if match else finding)
    return unresolved, explained


def validate_adjudication(record, candidates):
    """The plan reviewer ruled on every explained candidate, quoting it: contradiction | benign | ambiguous, each with a rationale. Returns the entries."""
    if not isinstance(record, dict) or record.get('schema') != ADJUDICATION_SCHEMA or not isinstance(record.get('adjudications'), list):
        raise ConfigurationError('scan-adjudication.json must be {"schema":"' + ADJUDICATION_SCHEMA + '","adjudications":[{"id","verdict","quote","rationale"}]}')
    by_id = {}
    for entry in record['adjudications']:
        if not isinstance(entry, dict) or entry.get('id') in by_id:
            raise ConfigurationError('Invalid or duplicate entry in scan-adjudication.json')
        by_id[entry.get('id')] = entry
    for candidate in candidates:
        entry = by_id.get(candidate['id'])
        if entry is None:
            raise ConfigurationError('scan-adjudication.json has no ruling on candidate ' + candidate['id'] + ': ' + candidate['text'][:120])
        if entry.get('verdict') not in SCAN_VERDICTS:
            raise ConfigurationError('Candidate ' + candidate['id'] + ' needs verdict ' + '|'.join(SCAN_VERDICTS))
        if not isinstance(entry.get('quote'), str) or len(_norm(entry['quote'])) < 15 or _norm(entry['quote']) not in _norm(candidate['text']):
            raise ConfigurationError('The ruling on ' + candidate['id'] + ' must quote at least 15 characters of the flagged text')
        if len(' '.join(str(entry.get('rationale', '')).split())) < MIN_EXPLANATION:
            raise ConfigurationError('The ruling on ' + candidate['id'] + ' needs a rationale of at least ' + str(MIN_EXPLANATION) + ' characters')
    return [by_id[c['id']] for c in candidates]
