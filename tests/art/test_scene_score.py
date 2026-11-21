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


class EngineAttestationAndAcceptanceTests(SceneFixture):
    def engine(self, **changes):
        digest = hashlib.sha256(self.screenshot.read_bytes()).hexdigest()
        return dict(engine='Unity', engine_version='6000.4.11f1', graphics_device='Apple M1 Max', screenshot_sha256=digest, **changes)

    COMPLETE = dict(required=['V1', 'V2'], present=['V1', 'V2'], missing=[], deferred=[], complete=True)
    PARTIAL = dict(required=['V1', 'V2'], present=['V1'], missing=['V2'], deferred=[], complete=False)

    def gate(self, post, require_engine=True, **record):
        return run_scene_similarity(self.reference, self.screenshot, self.record(**record), self.root / 'out/scene-similarity.json', post, require_engine=require_engine)

    def test_an_attested_complete_scene_at_80_is_final_acceptance(self):
        result = self.gate(self.post(80), engine=self.engine(), completeness=self.COMPLETE)
        self.assertEqual((result['status'], result['attested'], result['preliminary'], result['final_acceptance']), ('pass', True, False, True))

    def test_a_high_score_for_a_scene_that_misses_required_elements_is_only_a_preliminary_test(self):
        result = self.gate(self.post(97), engine=self.engine(), completeness=self.PARTIAL)
        self.assertEqual((result['status'], result['score']), ('pass', 97))       # the score is real and reported
        self.assertTrue(result['preliminary']); self.assertFalse(result['final_acceptance'])
        self.assertEqual(result['completeness']['missing'], ['V2'])

    def test_a_scene_without_a_completeness_account_is_never_final(self):
        result = self.gate(self.post(97), engine=self.engine())
        self.assertFalse(result['final_acceptance']); self.assertTrue(result['preliminary'])

    def test_an_unattested_render_is_blocked_when_the_engine_is_required_and_never_final_otherwise(self):
        blocked = self.gate(self.post(95), completeness=self.COMPLETE)
        self.assertEqual((blocked['status'], blocked['score']), ('blocked', None)); self.assertIn('engine attestation', ' '.join(blocked['problems']))
        self.assertEqual(self.calls, [])
        allowed = self.gate(self.post(95), require_engine=False, completeness=self.COMPLETE)
        self.assertEqual(allowed['status'], 'pass'); self.assertFalse(allowed['final_acceptance']); self.assertFalse(allowed['attested'])

    def test_an_attestation_for_another_screenshot_or_without_a_graphics_device_blocks(self):
        for bad in (self.engine(), ):
            bad = dict(bad, screenshot_sha256='0' * 64)
            result = self.gate(self.post(95), engine=bad, completeness=self.COMPLETE)
            self.assertEqual(result['status'], 'blocked'); self.assertIn('engine attestation does not match', ' '.join(result['problems']))
        result = self.gate(self.post(95), engine=self.engine() | dict(graphics_device=' '), completeness=self.COMPLETE)
        self.assertEqual(result['status'], 'blocked')


class CodexBackendTests(SceneFixture):
    def fake_codex(self, body):
        folder = self.root / 'bin'; folder.mkdir(exist_ok=True)
        exe = folder / 'codex'; exe.write_text('#!/bin/sh\n' + body); exe.chmod(0o755)
        return str(folder)

    def run_post(self, path_dir):
        import os
        from factory_art.scene_score import codex_post, PROMPT, RESPONSE
        from factory_art.similarity import _image
        body = {'messages': [{'content': [{'type': 'text', 'text': PROMPT}, _image(self.screenshot), _image(self.reference)]}]}
        old = os.environ['PATH']
        os.environ['PATH'] = path_dir + os.pathsep + old
        try:
            return codex_post(timeout=30)(body)
        finally:
            os.environ['PATH'] = old

    def test_the_scene_and_reference_go_to_codex_as_attached_images_and_its_json_answer_is_returned(self):
        folder = self.fake_codex('out=""; imgs=0\nwhile [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; -i) imgs=$((imgs+1)); test -s "$2" || exit 9; shift;; esac; shift; done\n'
                                 'echo "$imgs images" > "$out.count"; printf \'sure: {"score": 83, "differences": [], "diagnosis": "close"} done\' > "$out"\n')
        answer = self.run_post(folder)
        self.assertEqual(json.loads(answer['choices'][0]['message']['content'])['score'], 83)

    def test_a_codex_failure_or_a_non_json_answer_is_unavailable_never_a_score(self):
        from factory_art.similarity import SimilarityUnavailable
        for body in ('exit 5\n', 'out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; esac; shift; done; echo "no json here" > "$out"\n'):
            with self.assertRaises(SimilarityUnavailable):
                self.run_post(self.fake_codex(body))

    def test_the_cli_scores_through_codex_when_no_key_is_forwarded(self):
        folder = self.fake_codex('out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; esac; shift; done\n'
                                 'cat > "$out" <<EOF\n{"score": 41, "differences": [{"aspect": "color", "description": "the wall is far too dark", "impact": 5, "responsible": "wall.png", "repair": "lighten the panels"}], "diagnosis": "The wall is nearly black and carries most of the gap."}\nEOF\n')
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/scene_score.py'), '--reference', str(self.reference), '--screenshot', str(self.screenshot), '--render-record', str(self.record()),
                               '--out', str(self.root / 'cli/s.json'), '--allow-unattested'], capture_output=True, text=True, env={'PATH': folder + ':/usr/bin:/bin', 'HOME': '/nonexistent'})
        self.assertEqual(done.returncode, 2, done.stderr)               # a real score below 80
        summary = json.loads(done.stdout)
        self.assertEqual((summary['score'], summary['model'], summary['final_acceptance']), (41, 'codex-cli', False))
        self.assertEqual(json.loads((self.root / 'cli/s.json').read_text())['differences'][0]['responsible'], 'wall.png')


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
