"""Bounded reads of retained planning and perception evidence."""
import hashlib
import json
from pathlib import Path
import re
from .model_policy import ConfigurationError


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
    return dict(profile=profile, task_id=task_id, path=str(plans[0]), sha256=hashlib.sha256(plans[0].read_bytes()).hexdigest())


SIMILARITY_THRESHOLD = 80


def validate_similarity(result):
    """The cheap model score gates the detailed art review. Returns True when every asset reached the threshold."""
    record = retained_json(result.metadata['artifacts'], 'similarity.json')
    if not isinstance(record, dict) or record.get('schema') != 'factory-similarity/v1' or not isinstance(record.get('assets'), list):
        raise ConfigurationError('Invalid similarity record')
    threshold = record.get('threshold')
    if type(threshold) is not int or not SIMILARITY_THRESHOLD <= threshold <= 100:
        raise ConfigurationError('Similarity threshold is below the required 80%')
    passed = True
    for asset in record['assets']:
        if not isinstance(asset, dict) or not isinstance(asset.get('file'), str):
            raise ConfigurationError('Invalid similarity record')
        score, status = asset.get('score'), asset.get('status')
        if status == 'no_reference' and score is None:
            passed = False
        elif status in ('pass', 'fail') and type(score) is int and 0 <= score <= 100 and (status == 'pass') == (score >= threshold):
            passed = passed and status == 'pass'
        elif status == 'unverified':
            raise ConfigurationError('Similarity pre-check did not run for every asset')
        else:
            raise ConfigurationError('Contradictory similarity score')
    if not passed:
        blocking = [f for f in result.metadata.get('findings', []) if f.split('|', 4)[1] in ('BLOCKER', 'HIGH')]
        if not blocking or result.metadata['verdict'] != 'CHANGES_REQUIRED':
            raise ConfigurationError('A similarity score below 80% requires a blocking finding and CHANGES_REQUIRED')
    return passed


def validate_comparison(profile, result, plans, integration):
    """A linter success is never perceptual approval. Missing evidence stops the run."""
    if profile != 'art-reviewer':
        raise ConfigurationError('No perceptual comparison is defined for ' + profile)
    plan = next((p for p in plans if p['profile'] == 'art-director'), None)
    if plan is None:
        raise ConfigurationError('Specialist review has no captured director plan')
    record = retained_json(result.metadata['artifacts'], 'comparison.json')
    if not isinstance(record, dict) or set(record) != {'schema', 'plan_sha256', 'manifest_sha12', 'mode', 'source', 'outcome', 'criteria', 'evidence'}:
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
