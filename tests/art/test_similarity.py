import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from factory_art.similarity import KEY_VARS, SimilarityUnavailable, api_key, run_similarity


def answer(score, differences=()):
    return {'choices': [{'message': {'content': json.dumps({'score': score, 'differences': list(differences)})}}]}


class CredentialPropagationTests(unittest.TestCase):
    def test_dedicated_variable_wins_and_provider_variable_is_the_fallback(self):
        self.assertEqual(api_key({'FACTORY_SIMILARITY_API_KEY': ' dedicated ', 'OPENROUTER_API_KEY': 'provider'}), 'dedicated')
        self.assertEqual(api_key({'OPENROUTER_API_KEY': 'provider'}), 'provider')
        self.assertEqual(api_key({'FACTORY_SIMILARITY_API_KEY': '  ', 'OPENROUTER_API_KEY': 'provider'}), 'provider')
        self.assertIsNone(api_key({}))
        self.assertIsNone(api_key({'FACTORY_SIMILARITY_API_KEY': '', 'OPENROUTER_API_KEY': None}))

    def test_cli_with_only_the_dedicated_variable_reaches_the_model_path(self):
        # Without a key the gate is blocked; with only the dedicated name the process must at least try the network path.
        env = {'PATH': '/usr/bin:/bin', 'FACTORY_SIMILARITY_API_KEY': 'k', 'HOME': '/nonexistent'}
        with tempfile.TemporaryDirectory() as d:
            lint = Path(d) / 'lint.json'
            lint.write_text(json.dumps({'assets': []}))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/art_similarity.py'), str(lint), '--out', str(Path(d) / 's.json')],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('no credential', result.stderr)
            bare = subprocess.run([sys.executable, str(ROOT / 'scripts/art_similarity.py'), str(lint), '--out', str(Path(d) / 's2.json')],
                                  capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'})
            self.assertIn('no credential', bare.stderr)

    def test_dedicated_name_is_not_a_hermes_provider_credential(self):
        # The point of the dedicated name: Hermes' own guard must accept it for env_passthrough.
        hermes = Path.home() / '.hermes/hermes-agent'
        if not (hermes / 'tools/env_passthrough.py').exists():
            self.skipTest('Hermes source not available')
        sys.path.insert(0, str(hermes))
        try:
            from tools.env_passthrough import _is_hermes_provider_credential
        except Exception as error:  # pragma: no cover - environment dependent
            self.skipTest(str(error))
        self.assertFalse(_is_hermes_provider_credential(KEY_VARS[0]))
        self.assertTrue(_is_hermes_provider_credential('OPENROUTER_API_KEY'))


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
