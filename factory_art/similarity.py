"""Cheap similarity pre-check: score each rendered asset against its reference images before the detailed review."""
import base64
import json
from pathlib import Path
import urllib.error
import urllib.request

SCHEMA = 'factory-similarity/v1'
MODEL = 'typesafe/jev-router'
THRESHOLD = 80
TOOL = 'jev-similarity'
URL = 'https://openrouter.ai/api/v1/chat/completions'
# Hermes refuses to forward provider credential names (OPENROUTER_API_KEY, ...) into a worker's terminal, by design.
# The gate therefore reads a dedicated variable that a profile can list in terminal.env_passthrough, then falls back.
KEY_VARS = ('FACTORY_SIMILARITY_API_KEY', 'OPENROUTER_API_KEY')


def api_key(environ):
    """The first non-empty similarity credential in environ, or None."""
    for name in KEY_VARS:
        value = (environ.get(name) or '').strip()
        if value:
            return value
    return None
MAX_REFERENCES = 4
MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
PROMPT = '''The first image is a rendered game asset. The remaining images are the approved references for it.
Score how closely the rendered asset matches the references in subject, silhouette, proportions, palette and rendering style.
100 means it could be shipped as the same asset family; 0 means unrelated. Ignore background colour and image size.
Reply with JSON only: {"score": <integer 0-100>, "differences": [<up to 5 short phrases naming the largest mismatches>]}'''
RESPONSE = {'type': 'json_schema', 'json_schema': {'name': 'similarity', 'strict': True, 'schema': {
    'type': 'object', 'additionalProperties': False, 'required': ['score', 'differences'],
    'properties': {'score': {'type': 'integer'}, 'differences': {'type': 'array', 'items': {'type': 'string'}}}}}}


class SimilarityUnavailable(Exception):
    """The model could not be reached or returned an unusable answer. Never a pass."""


def _image(path):
    path = Path(path)
    mime = MIME.get(path.suffix.lower())
    if not mime or not path.is_file():
        raise SimilarityUnavailable(f'unreadable image: {path}')
    return {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()}}


def openrouter_post(api_key, timeout=120):
    def post(body):
        request = urllib.request.Request(URL, json.dumps(body).encode(),
                                         {'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise SimilarityUnavailable(str(error)) from error
    return post


def score_pair(candidate, references, post, model=MODEL):
    body = {'model': model, 'temperature': 0, 'seed': 0, 'response_format': RESPONSE,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': PROMPT}, _image(candidate),
                                                      *[_image(ref) for ref in references]]}]}
    try:
        answer = json.loads(post(body)['choices'][0]['message']['content'])
        score, differences = answer['score'], answer['differences']
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise SimilarityUnavailable(f'unusable model answer: {error}') from error
    if type(score) is not int or not 0 <= score <= 100 or not isinstance(differences, list):
        raise SimilarityUnavailable('unusable model answer: score out of range')
    return score, [str(item) for item in differences[:5]]


def candidate_image(asset):
    # Sprites come as transparent, grey and dark views; the grey one is the neutral comparison.
    images = asset['images']
    return images[1] if len(images) >= 3 else images[0]


def run_similarity(lint, out, post=None, threshold=THRESHOLD, model=MODEL):
    """post=None means no credentials: every asset is unverified and the tool is reported blocked."""
    result = {'schema': SCHEMA, 'model': model, 'threshold': threshold, 'assets': [], 'blocked_tools': []}
    for asset in lint.get('assets', []):
        if not asset.get('images'):
            continue
        references = asset.get('references', [])[:MAX_REFERENCES]
        row = {'file': asset['file'], 'candidate': candidate_image(asset), 'references': references,
               'score': None, 'differences': []}
        if not references:
            row['status'] = 'no_reference'
        elif post is None:
            row['status'] = 'unverified'
        else:
            try:
                row['score'], row['differences'] = score_pair(row['candidate'], references, post, model)
                row['status'] = 'pass' if row['score'] >= threshold else 'fail'
            except SimilarityUnavailable as error:
                row.update(status='unverified', error=str(error))
        result['assets'].append(row)
    statuses = [row['status'] for row in result['assets']]
    if 'unverified' in statuses:
        result['blocked_tools'].append(TOOL)
    result['gate'] = ('blocked' if 'unverified' in statuses else
                      'fail' if {'fail', 'no_reference'} & set(statuses) else 'pass')
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    return result
