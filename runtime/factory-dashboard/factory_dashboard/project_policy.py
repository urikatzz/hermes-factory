"""Pure project planning, reviewer selection and specialist repair policy."""
import re
from .model_policy import ConfigurationError

V2_PROFILES = (
    'factory-orchestrator', 'architect', 'developer', 'fixer',
    'art-director', 'artist', 'art-reviewer',
    'audio-director', 'sound-designer', 'audio-reviewer',
    'claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer',
    'verifier', 'factory-retro',
)
DOMAINS = ('art', 'audio', 'ui', 'ux')


def validate_scope(scope):
    if not isinstance(scope, dict) or set(scope) != set(DOMAINS) or any(type(v) is not bool for v in scope.values()):
        raise ConfigurationError('Scope requires art, audio, ui and ux booleans')
    return dict(scope)


def planning_profiles(scope):
    scope = validate_scope(scope)
    return [*(['art-director'] if scope['art'] else []),
            *(['audio-director'] if scope['audio'] else []), 'architect']


def review_profiles(needs, selected=()):
    validate_scope(needs)
    code = [p for p in selected if p in ('claude-reviewer', 'codex-reviewer')]
    profiles = [*(code or ['claude-reviewer']), 'security-reviewer']
    profiles += [p for domain, p in [('ux', 'ux-reviewer'), ('ui', 'ui-reviewer'),
                                  ('art', 'art-reviewer'), ('audio', 'audio-reviewer')] if needs[domain]]
    return list(dict.fromkeys(profiles))


def validate_plan(document, scope, project_ac_ids):
    validate_scope(scope)
    if not isinstance(document, dict) or set(document) != {'tasks'}:
        raise ConfigurationError('Project plan must contain tasks only')
    tasks = document['tasks']
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 40:
        raise ConfigurationError('Project plan requires 1 to 40 small tasks')
    by_id = {}
    covered = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {'id', 'title', 'owner', 'dependencies', 'acceptance', 'needs'}:
            raise ConfigurationError('Invalid task fields')
        key = task['id']
        if not isinstance(key, str) or not re.fullmatch('[a-z][a-z0-9-]{0,23}', key) or key == 'integration' or key in by_id:
            raise ConfigurationError('Invalid or duplicate task ID')
        if not isinstance(task['title'], str) or not task['title'].strip() or len(task['title']) > 200:
            raise ConfigurationError('Invalid task title')
        if task['owner'] not in ('developer', 'artist', 'sound-designer'):
            raise ConfigurationError('Invalid task owner')
        needs = validate_scope(task['needs'])
        if any(needs[d] and not scope[d] for d in DOMAINS):
            raise ConfigurationError('Task expands the captured project scope')
        for owner, domain in [('artist', 'art'), ('sound-designer', 'audio')]:
            if task['owner'] == owner and not needs[domain]:
                raise ConfigurationError('Asset task must declare its specialist domain')
        ac = task['acceptance']
        if not isinstance(ac, dict) or not ac or any(not isinstance(k, str) or not re.fullmatch(r'AC(?:[0-9]+|-GATE)', k)
                or not isinstance(v, str) or not v.strip() or len(v) > 1000 for k, v in ac.items()):
            raise ConfigurationError('Task requires numbered acceptance criteria')
        if not set(ac) <= set(project_ac_ids):
            raise ConfigurationError('Task acceptance is outside the architecture plan')
        covered.update(ac)
        deps = task['dependencies']
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(deps) != len(set(deps)):
            raise ConfigurationError('Invalid task dependencies')
        by_id[key] = task
    if covered != set(project_ac_ids):
        raise ConfigurationError('Task graph does not cover every project acceptance criterion')
    ordered, visiting, ancestors = [], set(), {}

    def visit(key):
        if key in visiting:
            raise ConfigurationError('Task dependency cycle')
        if key in ancestors:
            return ancestors[key]
        if key not in by_id:
            raise ConfigurationError('Unknown task dependency')
        visiting.add(key)
        inherited = set()
        for dep in by_id[key]['dependencies']:
            inherited.update(visit(dep))
            inherited.add(dep)
        visiting.remove(key)
        ancestors[key] = inherited
        ordered.append(by_id[key])
        return inherited

    for key in by_id:
        visit(key)
    for task in ordered:
        if task['owner'] == 'developer':
            for domain, owner in [('art', 'artist'), ('audio', 'sound-designer')]:
                if task['needs'][domain] and not any(by_id[d]['owner'] == owner for d in ancestors[task['id']]):
                    raise ConfigurationError('Code integration must depend on the required asset producer')
    for domain, owner in [('art', 'artist'), ('audio', 'sound-designer')]:
        if scope[domain] and not any(t['owner'] == owner for t in ordered):
            raise ConfigurationError('Project scope requires an asset production task')
    return ordered


def repair_profiles(findings, owner, repair_domains=()):
    profiles = []
    for domain in repair_domains:
        if domain not in ('code', 'art', 'audio'):
            raise ConfigurationError('Unsupported repair domain')
        profiles.append({'code': 'fixer', 'art': 'artist', 'audio': 'sound-designer'}[domain])
    for finding in findings:
        source = finding.split(':', 1)[0]
        if source in ('art-reviewer', 'audio-reviewer'):
            profiles.append({'art-reviewer': 'artist', 'audio-reviewer': 'sound-designer'}[source])
        elif re.match(r'[a-z]+-reviewer:F[0-9]+\|', finding):
            profiles.append('fixer')
        elif not repair_domains:
            profiles.append({'artist': 'artist', 'sound-designer': 'sound-designer'}.get(owner, 'fixer'))
    if not profiles:
        profiles.append({'artist': 'artist', 'sound-designer': 'sound-designer'}.get(owner, 'fixer'))
    ordered = [p for p in ('artist', 'sound-designer', 'fixer') if p in profiles]
    if len(ordered) > 1 and 'fixer' not in ordered:
        ordered.append('fixer')
    return ordered
