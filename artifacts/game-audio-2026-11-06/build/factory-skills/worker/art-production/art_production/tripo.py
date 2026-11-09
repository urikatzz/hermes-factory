"""Small Tripo3D OpenAPI v3 client: upload one image, run image-to-model, download the GLB.

Checked on 2026-10-26 against https://developers.tripo3d.com/en/docs/files.md (upload) and the v2 to v3 migration
guide https://developers.tripo3d.com/assets/developer/tripo-v2-to-v3-migration/SKILL.md (endpoints, statuses, codes).
Every endpoint, field and code is a constant here, so an API change is a one-line edit.
"""
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE_URL = 'https://openapi.tripo3d.com/v3'
UPLOAD_PATH = '/files'
IMAGE_TO_MODEL_PATH = '/generation/image-to-model'
TASK_PATH = '/tasks/{task_id}'
BALANCE_PATH = '/account/balance'
MODEL_VERSION = 'v3.1-20260211'
AUTH_CODES = {2, 1002}
CREDIT_CODES = {2010}
BUSY_CODES = {1007, 2000}
RUNNING = {'queued', 'running'}
POLL_SECONDS = 5
LIMIT_SECONDS = 600
GET_RETRIES = 3
MAX_MODEL_BYTES = 200 * 1024 * 1024
LOCAL_HOSTS = {'localhost', '127.0.0.1'}
UNKNOWN_CREATE = 'unknown-create'


class FallbackError(RuntimeError):
    """No key, no credits, rejected key or API unavailable: the artist builds a Blender blockout (exit 3)."""


class TaskError(RuntimeError):
    """The request or the generation failed for another reason (exit 1)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Requests carrying the API key never follow a redirect; the 3xx comes back as an HTTPError."""

    def redirect_request(self, *args):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _json(raw):
    try:
        value = json.loads(raw or b'{}')
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


class TripoClient:
    def __init__(self, key, base_url=BASE_URL, timeout=60, sleep=time.sleep, clock=time.monotonic):
        if not key:
            raise FallbackError('TRIPO_API_KEY is not set')
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in LOCAL_HOSTS):
            raise TaskError(f'Tripo base URL must use https (http only for localhost): {base_url}')
        self.key, self.base_url, self.timeout = key, base_url.rstrip('/'), timeout
        self.sleep, self.clock = sleep, clock
        self.task_ids = []

    def _call(self, method, path, body=None, content_type=None, bare=False, charged=False):
        """charged: the request may start a paid task, so a lost or failed reply is an error, never a fallback."""
        headers = {'Authorization': f'Bearer {self.key}'}
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with _OPENER.open(request, timeout=self.timeout) as response:
                payload, status = _json(response.read()), response.status
        except urllib.error.HTTPError as error:
            payload, status = _json(error.read()), error.code
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if charged:
                raise TaskError(f'Tripo {method} {path} sent but got no reply (possibly charged): {error}') from error
            raise FallbackError(f'Tripo API unavailable: {error}') from error
        if 300 <= status < 400:
            raise TaskError(f'Tripo {method} {path} redirected (HTTP {status}); redirects are never followed')
        code = payload.get('code', 0 if status < 400 else None)
        message = str(payload.get('message') or '')[:200]
        if status == 401 or code in AUTH_CODES:
            raise FallbackError(f'Tripo rejected the API key (HTTP {status}, code {code})')
        if code in CREDIT_CODES:
            raise FallbackError(f'Tripo credits exhausted (HTTP {status}, code {code})')
        if charged and status >= 500:
            raise TaskError(f'Tripo {method} {path} failed after sending (possibly charged) '
                            f'(HTTP {status}, code {code}) {message}'.strip())
        if status >= 500 or code in BUSY_CODES:
            raise FallbackError(f'Tripo API unavailable (HTTP {status}, code {code}) {message}'.strip())
        if status >= 400 or code != 0:
            raise TaskError(f'Tripo {method} {path} failed (HTTP {status}, code {code}) {message}'.strip())
        data = payload.get('data', payload if bare else None)
        if not isinstance(data, dict):
            raise TaskError(f'Tripo {method} {path} returned no data object')
        return data

    def upload(self, image):
        image = Path(image)
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{image.name}"\r\n'
                'Content-Type: image/png\r\n\r\n').encode() + image.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        token = self._call('POST', UPLOAD_PATH, body, f'multipart/form-data; boundary={boundary}').get('file_token')
        if not isinstance(token, str) or not token:
            raise TaskError('Tripo upload returned no file_token')
        return token

    def create(self, file_token):
        body = json.dumps({'file': {'type': 'png', 'file_token': file_token}, 'model_version': MODEL_VERSION}).encode()
        try:
            task_id = self._call('POST', IMAGE_TO_MODEL_PATH, body, 'application/json', charged=True).get('task_id')
        except TaskError:
            self.task_ids.append(UNKNOWN_CREATE)
            raise
        if not isinstance(task_id, str) or not task_id:
            self.task_ids.append(UNKNOWN_CREATE)
            raise TaskError('Tripo returned no task_id (possibly charged)')
        self.task_ids.append(task_id)
        return task_id

    def wait(self, task_id, interval=POLL_SECONDS, limit=LIMIT_SECONDS):
        """Poll (never faster than every 5 s) until the task ends; return its model URL."""
        interval = max(interval, POLL_SECONDS)
        started, failures = self.clock(), 0
        while True:
            try:
                data = self._call('GET', TASK_PATH.format(task_id=task_id))
                failures = 0
            except FallbackError:
                failures += 1
                if failures >= GET_RETRIES:
                    raise
                data = {'status': 'running'}
            status = data.get('status')
            if status == 'success':
                url = (data.get('output') or {}).get('model_url')
                if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
                    raise TaskError(f'Tripo task {task_id} succeeded without output.model_url')
                return url
            if status not in RUNNING:
                detail = f"{data.get('error_code', '')} {data.get('error_message') or ''}".strip()
                raise TaskError(f'Tripo task {task_id} {status}: {detail}'.strip())
            if self.clock() - started + interval > limit:
                raise TaskError(f'Tripo task {task_id} timed out after {limit}s')
            self.sleep(interval)

    def download(self, url, out):
        """Fetch the signed model URL without the API key and write the GLB atomically."""
        out = Path(out)
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=self.timeout) as response:
                data = response.read(MAX_MODEL_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TaskError(f'model download failed: {error}') from error
        if len(data) > MAX_MODEL_BYTES:
            raise TaskError(f'downloaded model is larger than {MAX_MODEL_BYTES} bytes')
        if data[:4] != b'glTF':
            raise TaskError('downloaded model is not a GLB file')
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name(out.name + '.part')
        partial.write_bytes(data)
        partial.replace(out)
        return out

    def balance(self):
        return self._call('GET', BALANCE_PATH, bare=True)


def image_to_model(client, image, out, interval=POLL_SECONDS, limit=LIMIT_SECONDS):
    """One charged generation. Never retried: a failure after create() is a TaskError (exit 1), never a fallback,
    and is reported with its task ID (or UNKNOWN_CREATE when the create reply was lost)."""
    task_id = client.create(client.upload(image))
    try:
        client.download(client.wait(task_id, interval, limit), out)
    except FallbackError as error:
        raise TaskError(f'Tripo task {task_id} was created (charged) but then: {error}') from error
    return task_id
