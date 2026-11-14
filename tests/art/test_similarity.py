import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from factory_art.similarity import SimilarityUnavailable, run_similarity


def answer(score, differences=()):
    return {'choices': [{'message': {'content': json.dumps({'score': score, 'differences': list(differences)})}}]}


class SimilarityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        for name in ('a.png', 'grey.png', 'dark.png', 'ref.png'):
            (self.dir / name).write_bytes(b'png')
        views = [str(self.dir / n) for n in ('a.png', 'grey.png', 'dark.png')]
        self.lint = {'assets': [
            {'file': 'hero.png', 'images': views, 'references': [str(self.dir / 'ref.png')]},
            {'file': 'orphan.png', 'images': views, 'references': []},
            {'file': 'menu.json', 'images': [], 'references': []}]}

    def run_gate(self, post):
        return run_similarity(self.lint, self.dir / 'out/similarity.json', post)

    def test_scores_grey_view_against_references_and_gates_at_80(self):
        bodies = []
        def post(body):
            bodies.append(body)
            return answer(84, ['outline weight'])
        self.lint['assets'].pop(1)
        result = self.run_gate(post)
        self.assertEqual(result['gate'], 'pass')
        self.assertEqual([(a['file'], a['score'], a['status']) for a in result['assets']], [('hero.png', 84, 'pass')])
        self.assertTrue(result['assets'][0]['candidate'].endswith('grey.png'))
        self.assertEqual(bodies[0]['model'], 'typesafe/jev-router')
        self.assertEqual(len([p for p in bodies[0]['messages'][0]['content'] if p['type'] == 'image_url']), 2)
        self.assertEqual(json.loads((self.dir / 'out/similarity.json').read_text())['threshold'], 80)

    def test_below_threshold_or_missing_reference_fails_the_gate(self):
        result = self.run_gate(lambda body: answer(79, ['palette']))
        self.assertEqual(result['gate'], 'fail')
        self.assertEqual({a['file']: a['status'] for a in result['assets']}, {'hero.png': 'fail', 'orphan.png': 'no_reference'})
        self.assertEqual(result['assets'][0]['differences'], ['palette'])

    def test_unavailable_model_or_bad_answer_blocks_instead_of_passing(self):
        def down(body):
            raise SimilarityUnavailable('offline')
        for post in (None, down, lambda body: answer(140), lambda body: {'choices': []}):
            result = self.run_gate(post)
            self.assertEqual(result['gate'], 'blocked')
            self.assertEqual(result['blocked_tools'], ['jev-similarity'])
            self.assertIsNone(result['assets'][0]['score'])

    def test_cli_without_key_reports_blocked(self):
        lint = self.dir / 'lint.json'
        lint.write_text(json.dumps(self.lint))
        run = subprocess.run([sys.executable, str(ROOT / 'scripts/art_similarity.py'), str(lint), '--out', str(self.dir / 's.json')],
                             capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['gate'], 'blocked')


if __name__ == '__main__':
    unittest.main()
