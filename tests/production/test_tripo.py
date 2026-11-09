import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import cube, sprite
from art_production import tripo
from art_production.tripo import MODEL_VERSION, FallbackError, TaskError, TripoClient, image_to_model
from factory_art.png import write_png


class FakeTripo:
    """Scripted local stand-in for the Tripo v3 API; task statuses are served in order, the last one repeats."""

    def __init__(self, statuses=('success',), create_error=None, glb=b'', create_delay=0, redirect=None):
        self.requests, self.statuses, self.create_error, self.glb = [], list(statuses), create_error, glb
        self.create_delay, self.redirect = create_delay, redirect
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, payload=None, raw=None):
                body = raw if raw is not None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.requests.append(('GET', self.path, dict(self.headers), b''))
                if self.path == '/model.glb':
                    return self.reply(200, raw=fake.glb)
                if fake.redirect and self.path == '/v3/account/balance':
                    self.send_response(302)
                    self.send_header('Location', fake.redirect)
                    self.send_header('Content-Length', '0')
                    return self.end_headers()
                if self.path == '/v3/account/balance':
                    return self.reply(200, {'code': 0, 'data': {'balance': 12.5, 'frozen': 0.0}})
                if self.path == '/v3/tasks/task-1':
                    status = fake.statuses.pop(0) if len(fake.statuses) > 1 else fake.statuses[0]
                    data = {'task_id': 'task-1', 'status': status}
                    if status == 'success':
                        data['output'] = {'model_url': fake.url + '/model.glb'}
                    if status == 'failed':
                        data.update(error_code=2008, error_message='moderation rejected')
                    return self.reply(200, {'code': 0, 'data': data})
                self.reply(404, {'code': 404, 'message': 'not found'})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                fake.requests.append(('POST', self.path, dict(self.headers), body))
                if self.path == '/v3/files':
                    return self.reply(200, {'code': 0, 'data': {'file_token': 'file_1'}})
                if self.path == '/v3/generation/image-to-model':
                    time.sleep(fake.create_delay)
                    if fake.create_error:
                        return self.reply(*fake.create_error)
                    return self.reply(200, {'code': 0, 'data': {'task_id': 'task-1', 'status': 'queued'}})
                self.reply(404, {'code': 404, 'message': 'not found'})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def paths(self, method=None):
        return [path for verb, path, _, _ in self.requests if method in (None, verb)]


class TripoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.image = self.root / 'concept.png'
        write_png(self.image, sprite())
        cube(self.root / 'cube.glb')
        self.glb = (self.root / 'cube.glb').read_bytes()
        self.sleeps, self.now = [], 0.0

    def fake(self, **kwargs):
        kwargs.setdefault('glb', self.glb)
        fake = FakeTripo(**kwargs)
        self.addCleanup(fake.close)
        return fake

    def client(self, fake, key='secret-key'):
        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds
        return TripoClient(key, fake.url + '/v3', timeout=5, sleep=sleep, clock=lambda: self.now)

    def test_success_uploads_creates_polls_and_downloads_without_leaking_the_key(self):
        fake = self.fake(statuses=('queued', 'running', 'success'))
        client = self.client(fake)
        self.assertEqual(image_to_model(client, self.image, self.root / 'out/model.glb'), 'task-1')
        self.assertEqual((self.root / 'out/model.glb').read_bytes(), self.glb)
        self.assertEqual(fake.paths(), ['/v3/files', '/v3/generation/image-to-model', '/v3/tasks/task-1',
                                        '/v3/tasks/task-1', '/v3/tasks/task-1', '/model.glb'])
        self.assertEqual(self.sleeps, [5, 5])
        upload, create = fake.requests[0], fake.requests[1]
        self.assertIn(b'name="file"; filename="concept.png"', upload[3])
        self.assertIn(self.image.read_bytes(), upload[3])
        self.assertEqual(json.loads(create[3]), {'file': {'type': 'png', 'file_token': 'file_1'},
                                                 'model_version': MODEL_VERSION})
        self.assertTrue(all(r[2].get('Authorization') == 'Bearer secret-key' for r in fake.requests[:-1]))
        self.assertNotIn('Authorization', fake.requests[-1][2])
        self.assertEqual(client.task_ids, ['task-1'])

    def test_missing_key_is_a_fallback_before_any_request(self):
        fake = self.fake()
        with self.assertRaisesRegex(FallbackError, 'TRIPO_API_KEY'):
            self.client(fake, key='')
        self.assertEqual(fake.requests, [])

    def test_exhausted_credits_is_a_fallback_and_is_never_retried(self):
        fake = self.fake(create_error=(403, {'code': 2010, 'message': 'insufficient balance'}))
        with self.assertRaisesRegex(FallbackError, 'credits exhausted'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')
        self.assertEqual(fake.paths('POST').count('/v3/generation/image-to-model'), 1)

    def test_rejected_key_is_a_fallback(self):
        fake = self.fake(create_error=(401, {'code': 2, 'message': 'invalid key'}))
        with self.assertRaisesRegex(FallbackError, 'rejected the API key'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')

    def test_failed_task_is_an_error_and_is_not_created_again(self):
        fake = self.fake(statuses=('running', 'failed'))
        with self.assertRaisesRegex(TaskError, 'task-1 failed: 2008 moderation rejected'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')
        self.assertEqual(fake.paths('POST').count('/v3/generation/image-to-model'), 1)
        self.assertFalse((self.root / 'model.glb').exists())

    def test_task_times_out_after_ten_minutes_of_five_second_polls(self):
        fake = self.fake(statuses=('running',))
        with self.assertRaisesRegex(TaskError, 'timed out after 600s'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')
        self.assertEqual(len(self.sleeps), 120)
        self.assertEqual(set(self.sleeps), {5})

    def test_polling_is_never_faster_than_five_seconds(self):
        fake = self.fake(statuses=('running', 'success'))
        client = self.client(fake)
        client.wait('task-1', interval=1)
        self.assertEqual(self.sleeps, [5])

    def test_unreachable_api_is_a_fallback(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        client = TripoClient('secret-key', f'http://127.0.0.1:{port}/v3', timeout=5)
        with self.assertRaisesRegex(FallbackError, 'unavailable'):
            client.upload(self.image)

    def test_a_download_that_is_not_glb_is_an_error(self):
        fake = self.fake(glb=b'<html>expired</html>')
        with self.assertRaisesRegex(TaskError, 'not a GLB'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')

    def test_create_timeout_after_sending_is_a_possibly_charged_error(self):
        fake = self.fake(create_delay=2)
        client = TripoClient('secret-key', fake.url + '/v3', timeout=1)
        with self.assertRaisesRegex(TaskError, 'possibly charged'):
            image_to_model(client, self.image, self.root / 'model.glb')
        self.assertEqual(client.task_ids, ['unknown-create'])

    def test_create_server_error_is_a_possibly_charged_error(self):
        fake = self.fake(create_error=(502, {'code': 2000, 'message': 'bad gateway'}))
        client = self.client(fake)
        with self.assertRaisesRegex(TaskError, 'possibly charged'):
            image_to_model(client, self.image, self.root / 'model.glb')
        self.assertEqual(client.task_ids, ['unknown-create'])
        self.assertEqual(fake.paths('POST').count('/v3/generation/image-to-model'), 1)

    def test_poll_outage_after_create_is_an_error_not_a_fallback(self):
        fake = self.fake()
        client = self.client(fake)
        client.wait = lambda *args: (_ for _ in ()).throw(FallbackError('Tripo API unavailable'))
        with self.assertRaises(TaskError):
            image_to_model(client, self.image, self.root / 'model.glb')
        self.assertEqual(client.task_ids, ['task-1'])

    def test_authorized_requests_never_follow_redirects(self):
        target = self.fake()
        fake = self.fake(redirect=target.url + '/v3/account/balance')
        with self.assertRaises(TaskError):
            self.client(fake).balance()
        self.assertEqual(target.requests, [])

    def test_base_url_must_be_https_unless_local(self):
        for url in ('http://example.com/v3', 'ftp://localhost/v3'):
            with self.assertRaisesRegex(TaskError, 'https'):
                TripoClient('secret-key', url)
        TripoClient('secret-key', 'http://localhost:1/v3')
        TripoClient('secret-key', 'http://127.0.0.1:1/v3')
        TripoClient('secret-key', 'https://openapi.tripo3d.com/v3')

    def test_model_download_is_size_capped(self):
        fake = self.fake(glb=b'glTF' + b'0' * 100)
        client = self.client(fake)
        old = tripo.MAX_MODEL_BYTES
        tripo.MAX_MODEL_BYTES = 50
        self.addCleanup(setattr, tripo, 'MAX_MODEL_BYTES', old)
        with self.assertRaisesRegex(TaskError, 'larger than'):
            client.download(fake.url + '/model.glb', self.root / 'big.glb')
        self.assertFalse((self.root / 'big.glb').exists())

    def run_cli(self, fake, *args, key='secret-key'):
        env = {k: v for k, v in os.environ.items() if k != 'TRIPO_API_KEY'}
        env['TRIPO_BASE_URL'] = fake.url + '/v3'
        if key:
            env['TRIPO_API_KEY'] = key
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/tripo_model.py'), *map(str, args)],
                                capture_output=True, text=True, env=env, timeout=60)
        return result.returncode, json.loads(result.stdout or '{}')

    def test_cli_exit_codes(self):
        out = self.root / 'cli.glb'
        self.assertEqual(self.run_cli(self.fake(), self.image, out, key='')[0], 3)
        code, data = self.run_cli(self.fake(create_error=(403, {'code': 2010})), self.image, out)
        self.assertEqual((code, data['tripo_tasks']), (3, []))
        (self.root / 'bad.png').write_bytes(b'not a png')
        fake = self.fake()
        self.assertEqual(self.run_cli(fake, self.root / 'bad.png', out)[0], 1)
        self.assertEqual(fake.requests, [])
        code, data = self.run_cli(self.fake(), self.image, out)
        self.assertEqual((code, data['task_id'], data['tripo_tasks']), (0, 'task-1', ['task-1']))
        self.assertEqual(out.read_bytes(), self.glb)
        code, data = self.run_cli(self.fake(create_error=(503, {})), self.image, out)
        self.assertEqual((code, data['tripo_tasks']), (1, ['unknown-create']))
        self.assertIn('possibly charged', data['error'])
        self.assertEqual(self.run_cli(self.fake(), '--balance'), (0, {'balance': {'balance': 12.5, 'frozen': 0.0}}))
