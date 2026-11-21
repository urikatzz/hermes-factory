import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from factory_art.png import Image, write_png
from factory_art.scene_score import RENDER_SCHEMA, THRESHOLD, run_scene_similarity, validate_render


def scene_image(width, height, seed):
    """A varied image (not flat), different per seed, standing in for an engine capture in these tests."""
    return Image(width, height, [((x * 7 + seed * 31) % 256, (y * 5 + seed * 17) % 256, ((x + y) * 3 + seed * 11) % 256, 255) for y in range(height) for x in range(width)])


def answer(score, differences=None, diagnosis='The set lacks the dummies and the floor is too light.'):
    differences = differences if differences is not None else [
        dict(aspect='color', description='floor far lighter than the near-black reference floor', impact=4, responsible='room01-floor-band.png', repair='repaint the floor near-black charcoal'),
        dict(aspect='texture', description='wall nearly featureless', impact=5, responsible='room01-wall-backdrop.png', repair='add visible lighter charcoal panels with seams and rivets')]
    return {'choices': [{'message': {'content': json.dumps({'score': score, 'differences': differences, 'diagnosis': diagnosis})}}]}


class SceneFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / 'look-D.png'; write_png(self.reference, scene_image(160, 90, 1))
        self.screenshot = self.root / 'scene.png'; write_png(self.screenshot, scene_image(160, 90, 2))
        self.calls = []

    def record(self, **changes):
        record = dict(schema=RENDER_SCHEMA, renderer='engine-game-view', command=['engine', '--capture', 'scene'], exit_code=0, scene='Scenes/Room01.unity',
                      project_dir=str(self.root), screenshot='scene.png', screenshot_sha256=hashlib.sha256(self.screenshot.read_bytes()).hexdigest() if self.screenshot.exists() else '0' * 64, width=160, height=90, captured_at=1)
        record.update(changes)
        path = self.root / 'scene-render.json'; path.write_text(json.dumps(record)); return path

    def post(self, score, **kw):
        def post(body):
            self.calls.append(body); return answer(score, **kw)
        return post

    def run_gate(self, post, record=None, **kw):
        return run_scene_similarity(self.reference, self.screenshot, record or self.record(), self.root / 'out/scene-similarity.json', post, assets=kw.get('assets', ['room01-wall-backdrop.png', 'room01-floor-band.png']))


class FullSceneComparisonTests(SceneFixture):
    def test_the_model_is_given_the_whole_scene_and_the_whole_reference_and_nothing_else(self):
        result = self.run_gate(self.post(85))
        content = self.calls[0]['messages'][0]['content']
        images = [c for c in content if c['type'] == 'image_url']
        self.assertEqual(len(images), 2)    # the scene, then the reference: never an isolated sprite, never several candidates
        self.assertIn('assembled game scene', content[0]['text']); self.assertIn('whole reference', content[0]['text'])
        self.assertEqual(result['reference']['sha256'], hashlib.sha256(self.reference.read_bytes()).hexdigest())
        self.assertEqual(result['screenshot']['sha256'], hashlib.sha256(self.screenshot.read_bytes()).hexdigest())

    def test_the_screenshot_is_compared_at_the_references_resolution(self):
        write_png(self.screenshot, scene_image(320, 180, 2))   # same 16:9 framing, twice the resolution
        result = self.run_gate(self.post(90), record=self.record(width=320, height=180, screenshot_sha256=hashlib.sha256(self.screenshot.read_bytes()).hexdigest()))
        from factory_art.png import read_png
        compared = read_png(result['compared'])
        self.assertEqual((compared.width, compared.height), (160, 90))
        self.assertEqual(result['status'], 'pass')

    def test_a_score_at_the_threshold_passes_and_one_below_it_fails_with_a_ranked_diagnosis(self):
        self.assertEqual(self.run_gate(self.post(THRESHOLD))['status'], 'pass')
        failed = self.run_gate(self.post(THRESHOLD - 1))
        self.assertEqual((failed['status'], failed['score']), ('fail', 79))
        self.assertEqual([d['impact'] for d in failed['differences']], [5, 4])      # ranked by effect on the score
        self.assertEqual(failed['differences'][0]['responsible'], 'room01-wall-backdrop.png')
        self.assertIn('floor', failed['diagnosis']); self.assertTrue(all(d['repair'] for d in failed['differences']))

    def test_the_threshold_is_80(self):
        self.assertEqual(THRESHOLD, 80)


class AdmissibleEvidenceTests(SceneFixture):
    def assert_blocked_without_a_score(self, result, fragment):
        self.assertEqual((result['status'], result['score']), ('blocked', None))
        self.assertTrue(any(fragment in p for p in result['problems']), result['problems'])
        self.assertEqual(self.calls, [])      # the model is never asked about inadmissible evidence

    def test_a_missing_screenshot_blocks_instead_of_receiving_a_score(self):
        self.screenshot.unlink()
        self.assert_blocked_without_a_score(self.run_gate(self.post(95), record=self.record(screenshot_sha256='0' * 64)), 'missing')

    def test_an_undecodable_screenshot_blocks(self):
        self.screenshot.write_bytes(b'this is not a png')
        self.assert_blocked_without_a_score(self.run_gate(self.post(95), record=self.record(screenshot_sha256=hashlib.sha256(b'this is not a png').hexdigest())), 'decode')

    def test_a_missing_or_malformed_render_record_blocks(self):
        self.assert_blocked_without_a_score(run_scene_similarity(self.reference, self.screenshot, self.root / 'nope.json', self.root / 'o.json', self.post(95)), 'render record')
        bad = self.root / 'bad.json'; bad.write_text(json.dumps({'schema': RENDER_SCHEMA}))
        self.assert_blocked_without_a_score(run_scene_similarity(self.reference, self.screenshot, bad, self.root / 'o.json', self.post(95)), 'render record')

    def test_a_failed_capture_or_one_with_no_command_blocks(self):
        self.assert_blocked_without_a_score(self.run_gate(self.post(95), record=self.record(exit_code=1)), 'did not succeed')
        self.assert_blocked_without_a_score(self.run_gate(self.post(95), record=self.record(command='')), 'no capture command')

    def test_a_screenshot_that_differs_from_its_record_blocks(self):
        self.assert_blocked_without_a_score(self.run_gate(self.post(95), record=self.record(screenshot_sha256='1' * 64)), 'sha256')
        self.assert_blocked_without_a_score(self.run_gate(self.post(95), record=self.record(width=999)), 'size differs')

    def test_the_wrong_framing_blocks(self):
        write_png(self.screenshot, scene_image(100, 100, 2))     # square capture against a 16:9 reference
        self.assert_blocked_without_a_score(self.run_gate(self.post(95), record=self.record(width=100, height=100, screenshot_sha256=hashlib.sha256(self.screenshot.read_bytes()).hexdigest())), 'framing')

    def test_the_reference_itself_or_a_copy_of_it_is_not_a_scene_render(self):
        self.screenshot.write_bytes(self.reference.read_bytes())
        self.assert_blocked_without_a_score(self.run_gate(self.post(100), record=self.record(screenshot_sha256=hashlib.sha256(self.screenshot.read_bytes()).hexdigest())), 'identical')
        copy = scene_image(160, 90, 1)          # re-encoded pixels of the reference: different file, same picture
        write_png(self.screenshot, Image(160, 90, [(min(255, p[0] + 1), p[1], p[2], 255) for p in copy.pixels]))
        self.assert_blocked_without_a_score(self.run_gate(self.post(100), record=self.record(screenshot_sha256=hashlib.sha256(self.screenshot.read_bytes()).hexdigest())), 'copy of the reference')

    def test_a_single_asset_is_not_an_assembled_scene(self):
        asset = self.root / 'room01-floor-band.png'; asset.write_bytes(self.screenshot.read_bytes())
        result = run_scene_similarity(self.reference, self.screenshot, self.record(), self.root / 'o.json', self.post(95), assets=[str(asset)])
        self.assertEqual(result['status'], 'blocked'); self.assertIn('single asset', ' '.join(result['problems']))

    def test_no_credentials_or_an_unusable_model_answer_never_produces_a_score(self):
        no_key = self.run_gate(None)
        self.assertEqual((no_key['status'], no_key['score']), ('blocked', None))
        for bad in ({'choices': [{'message': {'content': 'not json'}}]}, answer(150), answer(70, differences=[dict(aspect='color')])):
            def post(body, bad=bad): return bad
            result = self.run_gate(post)
            self.assertEqual((result['status'], result['score']), ('blocked', None), bad)

    def test_validate_render_returns_no_problems_for_a_good_capture(self):
        problems, image, expected = validate_render(json.loads(self.record().read_text()), self.screenshot, self.reference)
        self.assertEqual(problems, []); self.assertEqual((image.width, expected.width), (160, 160))


class SceneCommandLineTests(SceneFixture):
    def run_cli(self, *extra, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/scene_score.py'), '--reference', str(self.reference), '--screenshot', str(self.screenshot),
                               '--render-record', str(self.record()), '--out', str(self.root / 'cli/scene-similarity.json'), *extra],
                              capture_output=True, text=True, env=env or {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'})

    def test_without_a_credential_the_cli_exits_3_and_invents_no_score(self):
        done = self.run_cli()
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIsNone(json.loads(done.stdout)['score']); self.assertIn('no score is invented', done.stderr)
        self.assertEqual(json.loads((self.root / 'cli/scene-similarity.json').read_text())['status'], 'blocked')

    def test_the_cli_refuses_a_threshold_below_80(self):
        done = self.run_cli('--threshold', '60')
        self.assertEqual(done.returncode, 2); self.assertIn('cannot be below 80', done.stderr)


if __name__ == '__main__':
    unittest.main()
