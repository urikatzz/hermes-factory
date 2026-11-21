"""Full-scene visual score: the complete rendered scene against the complete human-approved reference.

An isolated sprite is never scored against a composed reference scene (that question has no meaningful answer: a floor strip "has no characters"). The only
similarity gate against an approved reference is this one: a real engine capture of the assembled scene, compared at the reference's framing and resolution.

Nothing here invents a score. A missing, undecodable, mis-framed, copied or unattributed screenshot yields status `blocked` with no score, and a model that is
unavailable or answers unusably does the same. A score is reported only for evidence that passed `validate_render`.
"""
import hashlib
import json
from pathlib import Path

from factory_art.png import Image, PngError, read_png, write_png
from factory_art.similarity import MIME, SimilarityUnavailable, _image

SCHEMA = 'factory-scene-similarity/v1'
RENDER_SCHEMA = 'factory-scene-render/v1'
MODEL = 'typesafe/jev-router'
THRESHOLD = 80
ASPECT_TOLERANCE = 0.01        # the capture must be framed like the reference
COPY_TOLERANCE = 0.004         # mean per-channel difference below this means the "screenshot" is the reference (or a copy of it)
ASPECTS = ('color', 'lighting', 'texture', 'proportion', 'missing_detail', 'composition', 'other')
RENDER_KEYS = {'schema', 'renderer', 'command', 'exit_code', 'scene', 'project_dir', 'screenshot', 'screenshot_sha256', 'width', 'height', 'captured_at'}
RENDER_OPTIONAL = {'engine', 'completeness', 'layout_sha256', 'isolated_clone', 'duration_seconds'}   # written by factory_unity.scene_capture from the engine's own attestation

PROMPT = '''The first image is a screenshot of the assembled game scene, rendered by the game engine. The second image is the human-approved reference for the same scene.
Both are shown at the same framing and resolution. Score how closely the whole scene matches the whole reference in composition, subjects and their proportions,
palette, lighting, materials and texture, and the details that are present (props, HUD, effects). 100 means indistinguishable in look and layout; 0 means unrelated.
The assets that make up the scene are: {assets}.
Reply with JSON only. "differences" lists the real visual differences, largest effect on the score first (at most 8). Each has: "aspect" (one of {aspects}),
"description" (what differs, specifically), "impact" (integer 1-5, how much it lowers the score), "responsible" (the asset file name from the list above that produces it, or "scene settings"
for camera, lighting or placement), and "repair" (an actionable instruction for the artist or scene builder that fixes the cause, not the score).
"diagnosis" is two or three sentences saying why the scene scored as it did.
{"score": <integer 0-100>, "differences": [...], "diagnosis": "..."}'''
RESPONSE = {'type': 'json_schema', 'json_schema': {'name': 'scene_similarity', 'strict': True, 'schema': {
    'type': 'object', 'additionalProperties': False, 'required': ['score', 'differences', 'diagnosis'],
    'properties': {'score': {'type': 'integer'}, 'diagnosis': {'type': 'string'},
                   'differences': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                   'required': ['aspect', 'description', 'impact', 'responsible', 'repair'],
                                   'properties': {'aspect': {'type': 'string'}, 'description': {'type': 'string'}, 'impact': {'type': 'integer'},
                                                  'responsible': {'type': 'string'}, 'repair': {'type': 'string'}}}}}}}}


def downscale(image, width, height):
    """Nearest-neighbour resample to exactly width x height (up or down), sampling the centre of each target pixel."""
    return Image(width, height, [image.pixels[min(image.height - 1, (2 * y + 1) * image.height // (2 * height)) * image.width
                                              + min(image.width - 1, (2 * x + 1) * image.width // (2 * width))]
                                 for y in range(height) for x in range(width)])


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _mean_difference(a, b):
    """Mean per-channel absolute difference (0..1) of two same-size images."""
    total = 0
    for p, q in zip(a.pixels, b.pixels):
        total += abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2])
    return total / (3 * 255 * len(a.pixels)) if a.pixels else 1.0


def validate_render(record, screenshot, reference, asset_files=(), require_engine=False):
    """Everything that makes a screenshot admissible. Returns (problems, screenshot image, reference image); problems is empty when admissible."""
    problems = []
    if not isinstance(record, dict) or not RENDER_KEYS <= set(record) or set(record) - RENDER_KEYS - RENDER_OPTIONAL or record.get('schema') != RENDER_SCHEMA:
        return ['render record is missing or does not match ' + RENDER_SCHEMA], None, None
    engine = record.get('engine')
    if engine is not None:
        if not isinstance(engine, dict) or engine.get('screenshot_sha256') != record['screenshot_sha256'] or not str(engine.get('graphics_device', '')).strip() or not str(engine.get('engine_version', '')).strip():
            problems.append('the engine attestation does not match the screenshot')
    elif require_engine:
        problems.append('the render record carries no engine attestation: only a capture made by the game engine is accepted')
    command = record['command']
    if not (isinstance(command, str) and command.strip()) and not (isinstance(command, list) and command and all(isinstance(c, str) and c for c in command)):
        problems.append('render record has no capture command')
    if record['exit_code'] != 0 or type(record['exit_code']) is not int:
        problems.append('the capture command did not succeed')
    for key in ('renderer', 'scene', 'project_dir'):
        if not isinstance(record[key], str) or not record[key].strip():
            problems.append(f'render record has no {key}')
    shot, ref = Path(screenshot), Path(reference)
    if not shot.is_file() or shot.is_symlink():
        return problems + ['scene screenshot is missing'], None, None
    if not ref.is_file():
        return problems + ['reference image is missing'], None, None
    if sha256_file(shot) != record['screenshot_sha256']:
        problems.append('screenshot does not match the sha256 in the render record')
    try:
        image, expected = read_png(shot), read_png(ref)
    except (PngError, OSError, ValueError) as error:
        return problems + [f'image does not decode: {error}'], None, None
    if (image.width, image.height) != (record['width'], record['height']):
        problems.append('screenshot size differs from the render record')
    if abs(image.width / image.height - expected.width / expected.height) > ASPECT_TOLERANCE * expected.width / expected.height:
        problems.append(f'screenshot framing {image.width}x{image.height} does not match the reference {expected.width}x{expected.height}')
    if sha256_file(shot) == sha256_file(ref):
        problems.append('the screenshot is byte-identical to the reference')
    for asset in asset_files:
        if Path(asset).is_file() and sha256_file(asset) == sha256_file(shot):
            problems.append('the screenshot is a single asset file, not an assembled scene')
    if not problems:
        scaled = image if (image.width, image.height) == (expected.width, expected.height) else downscale(image, expected.width, expected.height)
        if _mean_difference(scaled, expected) < COPY_TOLERANCE:
            problems.append('the screenshot is a copy of the reference, not a render of the scene')
    return problems, image, expected


def compared_image(image, reference, out):
    """The screenshot at the reference's resolution (the view the model compares); written next to the report so it can be retained."""
    scaled = image if (image.width, image.height) == (reference.width, reference.height) else downscale(image, reference.width, reference.height)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    write_png(Path(out), scaled)
    return Path(out)


def score_scene(candidate, reference, assets, post, model=MODEL):
    body = {'model': model, 'temperature': 0, 'seed': 0, 'response_format': RESPONSE,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': PROMPT.replace('{assets}', ', '.join(assets) or 'none listed').replace('{aspects}', ', '.join(ASPECTS))},
                                                      _image(candidate), _image(reference)]}]}
    try:
        answer = json.loads(post(body)['choices'][0]['message']['content'])
        score, diagnosis, differences = answer['score'], answer['diagnosis'], answer['differences']
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise SimilarityUnavailable(f'unusable model answer: {error}') from error
    if type(score) is not int or not 0 <= score <= 100 or not isinstance(diagnosis, str) or not isinstance(differences, list):
        raise SimilarityUnavailable('unusable model answer: score out of range')
    clean = []
    for item in differences[:8]:
        if (not isinstance(item, dict) or type(item.get('impact')) is not int or not 1 <= item['impact'] <= 5
                or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('aspect', 'description', 'responsible', 'repair'))):
            raise SimilarityUnavailable('unusable model answer: malformed difference')
        clean.append({k: item[k] for k in ('aspect', 'description', 'impact', 'responsible', 'repair')})
    clean.sort(key=lambda d: -d['impact'])    # ranked by effect on the score, stable for equal impacts
    return score, clean, diagnosis.strip()


def run_scene_similarity(reference, screenshot, render_record, out, post=None, threshold=THRESHOLD, model=MODEL, assets=(), require_engine=False):
    """Write `out` (factory-scene-similarity/v1). status: pass / fail (a real score below the threshold) / blocked (no score was obtained, for any reason)."""
    out = Path(out)
    result = {'schema': SCHEMA, 'model': model, 'threshold': threshold, 'reference': {'path': str(reference)},
              'screenshot': {'path': str(screenshot)}, 'score': None, 'differences': [], 'diagnosis': '', 'status': 'blocked', 'problems': []}
    try:
        record = json.loads(Path(render_record).read_text()) if Path(render_record).is_file() else None
    except (OSError, ValueError):
        record = None
    problems, image, expected = validate_render(record, screenshot, reference, assets, require_engine)
    if Path(reference).is_file():
        result['reference']['sha256'] = sha256_file(reference)
    if Path(screenshot).is_file():
        result['screenshot']['sha256'] = sha256_file(screenshot)
    if record is not None and Path(render_record).is_file():
        result['render_record_sha256'] = sha256_file(render_record)
    if problems:
        result['problems'] = problems
    elif post is None:
        result['problems'] = ['no model credentials: the scene could not be scored']
    else:
        try:
            compared = compared_image(image, expected, out.parent / 'scene-compared.png')
            result['compared'] = str(compared)
            result['score'], result['differences'], result['diagnosis'] = score_scene(compared, reference, [Path(a).name for a in assets], post, model)
            result['status'] = 'pass' if result['score'] >= threshold else 'fail'
        except SimilarityUnavailable as error:
            result['problems'] = [str(error)]
    # Acceptance needs more than a score: an engine-attested capture of a COMPLETE scene. A scene that still misses required elements is a preliminary composition test.
    done = (record or {}).get('completeness') if isinstance(record, dict) else None
    complete = isinstance(done, dict) and done.get('missing') == [] and done.get('complete') is True
    result['completeness'] = done if isinstance(done, dict) else None
    result['attested'] = bool(isinstance(record, dict) and record.get('engine'))
    result['preliminary'] = not complete
    result['final_acceptance'] = result['status'] == 'pass' and complete and result['attested']
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    return result


def codex_post(timeout=300, binary='codex'):
    """A `post` for score_scene that uses the machine's Codex login instead of an API key: the two images go to `codex exec -i` and its JSON answer is returned in the
    chat-completions shape score_scene reads. Nothing about a credential is read or forwarded here."""
    import base64
    import shutil
    import subprocess
    import tempfile

    def post(body):
        exe = shutil.which(binary)
        if not exe:
            raise SimilarityUnavailable('the codex CLI is not installed')
        parts = body['messages'][0]['content']
        text = next(p['text'] for p in parts if p['type'] == 'text')
        images = [p['image_url']['url'] for p in parts if p['type'] == 'image_url']
        with tempfile.TemporaryDirectory(prefix='scene-codex-') as work:
            files = []
            for index, url in enumerate(images):
                header, _, data = url.partition(',')
                path = Path(work) / f'image-{index}.png'
                path.write_bytes(base64.b64decode(data))
                files.append(str(path))
            answer = Path(work) / 'answer.txt'
            prompt = text + '\nThe first attached image is the engine screenshot of the scene, the second is the approved reference. Answer with the JSON object only.'
            command = [exe, 'exec', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only', '-C', work, '--color', 'never', '-o', str(answer)]
            for f in files:
                command += ['-i', f]
            command += ['--', prompt]
            try:
                done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise SimilarityUnavailable(f'codex exec failed: {error}') from error
            if done.returncode != 0 or not answer.is_file():
                raise SimilarityUnavailable('codex exec returned no answer: ' + (done.stderr or '')[-200:])
            content = answer.read_text().strip()
            start, end = content.find('{'), content.rfind('}')
            if start < 0 or end < start:
                raise SimilarityUnavailable('codex answered without a JSON object')
            return {'choices': [{'message': {'content': content[start:end + 1]}}]}
    return post

