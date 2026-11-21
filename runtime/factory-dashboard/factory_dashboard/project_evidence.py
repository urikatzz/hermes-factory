"""Bounded reads of retained planning and perception evidence."""
import hashlib
import json
from pathlib import Path
import re
from .model_policy import ConfigurationError
from . import project_references


def dedupe_artifacts(artifacts):
    """Collapse attachments Kanban stored twice. kanban_complete attaches a file once per mention (the artifacts argument and metadata.artifacts), which
    yields PLAN.md and PLAN_1.md with the same bytes. A numbered copy is dropped only when an earlier file of the base name has identical content;
    differing numbered files stay and stay ambiguous."""
    kept = []
    for artifact in artifacts:
        path = Path(artifact)
        match = re.fullmatch(r'(.+?)_([0-9]+)(\.[^.]+)?', path.name)
        if match and path.is_file():
            base = match.group(1) + (match.group(3) or '')
            original = next((Path(k) for k in kept if Path(k).name == base and Path(k).parent == path.parent and Path(k).is_file()), None)
            if original and not path.is_symlink() and hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(path.read_bytes()).digest():
                continue
        kept.append(artifact)
    return kept


def retained_json(artifacts, name):
    paths = [Path(p) for p in artifacts if re.fullmatch(re.escape(name.removesuffix('.json')) + r'(?:_[0-9]+)?\.json', Path(p).name)]
    if len(paths) != 1:
        raise ConfigurationError('Expected one retained ' + name)
    path = paths[0]
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise ConfigurationError('Invalid or oversized retained ' + name)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigurationError('Duplicate evidence field')
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ConfigurationError('Nonfinite evidence value')))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigurationError('Invalid retained ' + name + ': ' + str(exc)) from exc


def plan_evidence(profile, task_id, metadata):
    plans = [Path(p) for p in metadata['artifacts'] if re.fullmatch(r'PLAN(?:_[0-9]+)?\.md', Path(p).name)]
    if len(plans) != 1 or plans[0].is_symlink() or not plans[0].is_file() or plans[0].stat().st_size > 262144:
        raise ConfigurationError('Preparation requires one retained PLAN.md')
    evidence = dict(profile=profile, task_id=task_id, path=str(plans[0]), sha256=hashlib.sha256(plans[0].read_bytes()).hexdigest())
    mockup = project_references.plan_mockup(metadata['artifacts']) if profile == 'art-director' else None
    if mockup:
        evidence['mockup'] = str(mockup)
    return evidence


SIMILARITY_THRESHOLD = 80


def validate_comparison(profile, result, plans, integration, approved=False):
    """A linter success is never perceptual approval. Missing evidence stops the run."""
    if profile != 'art-reviewer':
        raise ConfigurationError('No perceptual comparison is defined for ' + profile)
    plan = next((p for p in plans if p['profile'] == 'art-director'), None)
    if plan is None:
        raise ConfigurationError('Specialist review has no captured director plan')
    record = retained_json(result.metadata['artifacts'], 'comparison.json')
    keys = {'schema', 'plan_sha256', 'manifest_sha12', 'mode', 'source', 'outcome', 'criteria', 'evidence'} | ({'references', 'holistic'} if approved else set())
    if not isinstance(record, dict) or set(record) != keys:
        raise ConfigurationError('Invalid perceptual comparison record')
    mode = 'rendered_in_engine' if integration else 'rendered_asset'
    if record['schema'] != 'factory-comparison/v1' or record['plan_sha256'] != plan['sha256'] or record['manifest_sha12'] != result.metadata['manifest_sha12']:
        raise ConfigurationError('Comparison does not match the retained director plan and manifest')
    if record['mode'] != mode or record['source'] not in ('tool', 'human'):
        raise ConfigurationError('Required rendered evidence is unavailable')
    evidence = record['evidence']
    if not isinstance(evidence, list) or not evidence or any(not isinstance(p, str) or not p.strip() for p in evidence):
        raise ConfigurationError('Comparison evidence must be retained attachments')
    retained = []
    for reference in evidence:
        # Scratch completion moves artifacts, but cannot rewrite paths inside JSON.
        name = Path(reference).name
        pattern = re.escape(Path(name).stem) + r'(?:_[0-9]+)?' + re.escape(Path(name).suffix)
        matches = [p for p in result.metadata['artifacts'] if p == reference or re.fullmatch(pattern, Path(p).name)]
        if len(matches) != 1 or re.fullmatch(r'comparison(?:_[0-9]+)?\.json', Path(matches[0]).name):
            raise ConfigurationError('Comparison evidence must identify an unambiguous retained attachment')
        retained.append(matches[0])
    evidence = retained
    record['evidence'] = retained
    if not any(Path(p).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') for p in evidence):
        raise ConfigurationError('Rendered visual comparison requires a retained image')
    if any(not Path(p).is_file() or Path(p).is_symlink() for p in evidence):
        raise ConfigurationError('Comparison evidence is unavailable')
    criteria = record['criteria']
    if not isinstance(criteria, list) or not criteria:
        raise ConfigurationError('Comparison requires expected and observed director criteria')
    for criterion in criteria:
        if not isinstance(criterion, dict) or set(criterion) != {'rule', 'expected', 'observed', 'outcome'} or any(
                not isinstance(criterion[k], str) or not criterion[k].strip() for k in ('rule', 'expected', 'observed')) or criterion['outcome'] not in ('pass', 'fail'):
            raise ConfigurationError('Invalid director criterion comparison')
    if record['outcome'] not in ('pass', 'fail') or (record['outcome'] == 'pass') != all(c['outcome'] == 'pass' for c in criteria):
        raise ConfigurationError('Contradictory perceptual outcome')
    if record['outcome'] == 'fail' and not result.metadata.get('findings'):
        raise ConfigurationError('Failed comparison requires actionable findings')
    if record['outcome'] == 'fail':
        blocking = [f for f in result.metadata['findings'] if f.split('|', 4)[1] in ('BLOCKER', 'HIGH')
                    or (f.split('|', 4)[1] == 'MEDIUM' and f.split('|', 4)[2] != '-')]
        if not blocking or result.metadata['verdict'] != 'CHANGES_REQUIRED':
            raise ConfigurationError('A director mismatch requires a blocking finding and CHANGES_REQUIRED')
    if record['outcome'] == 'pass' and result.metadata['verdict'] != 'NO_BLOCKING_FINDINGS':
        raise ConfigurationError('Comparison and reviewer verdict disagree')
    return record


def validate_scene_similarity(result, references, required=()):
    """The full-scene gate: a real engine capture of the assembled scene scored against the human-approved reference. Never a sprite, never an invented score.
    Returns (record, render record). status `blocked` (no admissible evidence, no score) stops the project; `fail` needs CHANGES_REQUIRED and a ranked diagnosis."""
    record = retained_json(result.metadata['artifacts'], 'scene-similarity.json')
    render = retained_json(result.metadata['artifacts'], 'scene-render.json')
    keys = {'schema', 'model', 'threshold', 'reference', 'screenshot', 'score', 'differences', 'diagnosis', 'status', 'problems'}
    if not isinstance(record, dict) or not keys <= set(record) or record['schema'] != 'factory-scene-similarity/v1':
        raise ConfigurationError('Invalid scene similarity record')
    threshold = record['threshold']
    if type(threshold) is not int or not SIMILARITY_THRESHOLD <= threshold <= 100:
        raise ConfigurationError('Scene similarity threshold is below the required 80')
    if record['status'] == 'blocked' or record['score'] is None:
        raise ConfigurationError('Scene similarity could not be evaluated, so no score exists: ' + '; '.join(str(p) for p in record.get('problems', []))[:300])
    score, status = record['score'], record['status']
    if status not in ('pass', 'fail') or type(score) is not int or not 0 <= score <= 100 or (status == 'pass') != (score >= threshold):
        raise ConfigurationError('Contradictory scene similarity score')
    authoritative = {r.get('sha256') for r in references if 'visual_reference' in r['roles'] and r['authority'] == 'human_approved'}
    if not isinstance(record['reference'], dict) or record['reference'].get('sha256') not in authoritative:
        raise ConfigurationError('Scene similarity was not scored against a human-approved reference')
    shot = record['screenshot'] if isinstance(record['screenshot'], dict) else {}
    named = [p for p in result.metadata['artifacts'] if isinstance(render, dict) and Path(p).name == Path(str(render.get('screenshot', ''))).name]
    if (not isinstance(render, dict) or render.get('schema') != 'factory-scene-render/v1' or render.get('exit_code') != 0 or not render.get('command')
            or len(named) != 1 or Path(named[0]).is_symlink() or not Path(named[0]).is_file()):
        raise ConfigurationError('Scene similarity has no retained engine render record and screenshot')
    data = Path(named[0]).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or digest != render.get('screenshot_sha256') or digest != shot.get('sha256'):
        raise ConfigurationError('The scored screenshot is not the retained render')
    # Acceptance needs an engine-attested capture of a COMPLETE scene. The required elements come from the approved reference (computed by the controller, never taken from the
    # capture), so a render that understates what is required, or that still misses required elements, can be scored but never accepted.
    engine = render.get('engine')
    if not isinstance(engine, dict) or engine.get('screenshot_sha256') != digest or not str(engine.get('graphics_device', '')).strip() or not str(engine.get('engine_version', '')).strip():
        raise ConfigurationError('The scene render carries no engine attestation: only a capture made by the game engine is accepted')
    done = render.get('completeness')
    if required:
        if not isinstance(done, dict) or not set(required) <= set(done.get('required', [])) or not isinstance(done.get('missing'), list):
            raise ConfigurationError('The scene render does not account for every required reference element')
    incomplete = list(done.get('missing', [])) if isinstance(done, dict) else []
    if status == 'pass' and incomplete:
        status = 'incomplete'
    if status in ('fail', 'incomplete'):
        diffs = record['differences'] or ([dict(aspect='missing_detail', description='required elements are not in the scene: ' + ', '.join(incomplete), impact=5, responsible='scene settings',
                                                repair='build the missing required elements into the scene: ' + ', '.join(incomplete))] if incomplete else [])
        ok = (isinstance(diffs, list) and diffs and all(isinstance(d, dict) and type(d.get('impact')) is int and 1 <= d['impact'] <= 5
                                                          and all(isinstance(d.get(k), str) and d[k].strip() for k in ('aspect', 'description', 'responsible', 'repair')) for d in diffs)
              and all(diffs[i]['impact'] >= diffs[i + 1]['impact'] for i in range(len(diffs) - 1)))
        if not ok or (status == 'fail' and (not isinstance(record['diagnosis'], str) or len(record['diagnosis'].strip()) < 20)):
            raise ConfigurationError('A failing scene score needs a ranked list of differences and a diagnosis')
        blocking = [f for f in result.metadata.get('findings', []) if f.split('|', 4)[1] in ('BLOCKER', 'HIGH')]
        if not blocking or result.metadata['verdict'] != 'CHANGES_REQUIRED':
            raise ConfigurationError('A scene score below 80, or a scene that still misses required elements (' + ', '.join(incomplete) + '), requires a blocking finding and CHANGES_REQUIRED')
    return record, render, incomplete

