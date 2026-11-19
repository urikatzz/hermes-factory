import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
import factory_secrets as fs
from factory_art import similarity

SECRET = 'sk-test-0123456789abcdef'
HERMES = Path.home() / '.hermes/hermes-agent'


class ProfileFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.profile = self.home / 'profiles/art-reviewer'
        self.profile.mkdir(parents=True)

    def configure(self, names, env=''):
        listing = ''.join(f'  - {n}\n' for n in names)
        (self.profile / 'config.yaml').write_text('model:\n  provider: x\nterminal:\n  env_passthrough:\n' + listing + 'hooks: {}\n')
        (self.profile / '.env').write_text(env)

    @staticmethod
    def never(name):
        return False

    @staticmethod
    def provider(name):
        return name == 'OPENROUTER_API_KEY'


class DoctorTests(ProfileFixture):
    def test_a_correctly_scoped_secret_has_no_problems(self):
        self.configure(['FACTORY_SIMILARITY_API_KEY'], f'FACTORY_SIMILARITY_API_KEY={SECRET}\n')
        self.assertEqual(fs.check_profile(self.home, 'art-reviewer', ['FACTORY_SIMILARITY_API_KEY'], self.provider), [])

    def test_each_gap_is_reported_by_name_only(self):
        self.configure([], f'OTHER=1\n')
        problems = fs.check_profile(self.home, 'art-reviewer', ['FACTORY_SIMILARITY_API_KEY'], self.never)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any('env_passthrough' in p for p in problems) and any('no value' in p for p in problems))

    def test_a_provider_credential_name_is_flagged_both_as_required_and_as_declared(self):
        self.configure(['OPENROUTER_API_KEY'], f'OPENROUTER_API_KEY={SECRET}\n')
        problems = fs.check_profile(self.home, 'art-reviewer', ['OPENROUTER_API_KEY'], self.provider)
        self.assertTrue(any('refuses to forward' in p for p in problems))
        self.assertTrue(any('will never forward' in p for p in problems))
        self.assertNotIn(SECRET, ' '.join(problems))

    def test_cli_doctor_never_prints_a_secret_value(self):
        self.configure(['OPENROUTER_API_KEY'], f'OPENROUTER_API_KEY={SECRET}\nFACTORY_SIMILARITY_API_KEY={SECRET}\n')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/factory_secrets.py'), 'doctor'], capture_output=True, text=True,
                                env={'PATH': os.environ['PATH'], 'HERMES_HOME': str(self.home)})
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertIn('art-reviewer', result.stdout)

    def test_passthrough_list_parsing_stops_at_the_next_key(self):
        self.configure(['A_KEY', 'B_KEY'])
        self.assertEqual(fs.passthrough_names(self.profile / 'config.yaml'), ['A_KEY', 'B_KEY'])
        self.assertEqual(fs.passthrough_names(self.profile / 'missing.yaml'), [])


class SetTests(ProfileFixture):
    def test_set_stores_only_a_declared_dedicated_name_with_private_permissions(self):
        self.configure(['FACTORY_SIMILARITY_API_KEY'], 'KEEP=1\nFACTORY_SIMILARITY_API_KEY=old-old-old\n')
        with mock.patch.object(fs, 'provider_blocked', return_value=False), redirect_stdout(io.StringIO()) as out:
            fs.set_secret(self.home, 'art-reviewer', 'FACTORY_SIMILARITY_API_KEY', SECRET)
        text = (self.profile / '.env').read_text()
        self.assertIn(f'FACTORY_SIMILARITY_API_KEY={SECRET}', text)
        self.assertEqual(text.count('FACTORY_SIMILARITY_API_KEY='), 1)
        self.assertIn('KEEP=1', text)
        self.assertEqual(oct((self.profile / '.env').stat().st_mode & 0o777), '0o600')
        self.assertNotIn(SECRET, out.getvalue())

    def test_set_refuses_undeclared_provider_and_malformed_values(self):
        self.configure(['FACTORY_SIMILARITY_API_KEY'])
        with mock.patch.object(fs, 'provider_blocked', return_value=False):
            for name, value in (('OTHER_NAME', SECRET), ('FACTORY_SIMILARITY_API_KEY', ''), ('FACTORY_SIMILARITY_API_KEY', 'short'),
                                ('FACTORY_SIMILARITY_API_KEY', 'a\\nb-0123456789')):
                with self.subTest(name=name, value=value), self.assertRaises(SystemExit):
                    fs.set_secret(self.home, 'art-reviewer', name, value.replace('\\n', '\n'))
        with mock.patch.object(fs, 'provider_blocked', return_value=True), self.assertRaises(SystemExit):
            fs.set_secret(self.home, 'art-reviewer', 'FACTORY_SIMILARITY_API_KEY', SECRET)
        self.assertEqual((self.profile / '.env').read_text(), '')

    def test_set_refuses_a_non_interactive_value_source(self):
        self.configure(['FACTORY_SIMILARITY_API_KEY'])
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/factory_secrets.py'), 'set', 'art-reviewer', 'FACTORY_SIMILARITY_API_KEY'],
                                input=SECRET, capture_output=True, text=True, env={'PATH': os.environ['PATH'], 'HERMES_HOME': str(self.home)})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertEqual((self.profile / '.env').read_text(), '')


class RedactionTests(unittest.TestCase):
    def test_the_key_never_reaches_an_error_the_worker_could_log_or_attach(self):
        import urllib.error
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError(f'rejected credential {SECRET}')):
            with self.assertRaises(similarity.SimilarityUnavailable) as raised:
                similarity.openrouter_post(SECRET)({'model': 'm'})
        self.assertNotIn(SECRET, str(raised.exception))
        self.assertIn('[redacted]', str(raised.exception))
        self.assertEqual(similarity.redact('short', 'sh'), 'short')  # too short to be a secret: left alone

    def test_the_gate_script_prints_no_credential_even_when_the_model_is_unreachable(self):
        with tempfile.TemporaryDirectory() as directory:
            lint = Path(directory) / 'lint.json'
            lint.write_text(json.dumps({'assets': []}))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/art_similarity.py'), str(lint), '--out', str(Path(directory) / 's.json')],
                                    capture_output=True, text=True, env={'PATH': os.environ['PATH'], 'FACTORY_SIMILARITY_API_KEY': SECRET})
            self.assertNotIn(SECRET, result.stdout + result.stderr + (Path(directory) / 's.json').read_text())


@unittest.skipUnless((HERMES / 'tools/environments/local.py').exists() and (HERMES / 'venv/bin/python').exists(), 'Hermes source not available')
class HermesPropagationTests(unittest.TestCase):
    """Real Hermes, dummy values: a declared dedicated name reaches the worker's commands; a provider credential name never does."""
    PROBE = ('from tools.environments.local import _sanitize_subprocess_env as s\n'
             "import json;base={'PATH':'/usr/bin:/bin','FACTORY_SIMILARITY_API_KEY':'dummy-dedicated','OPENROUTER_API_KEY':'dummy-provider','UNDECLARED_THING':'x'}\n"
             "print(json.dumps(sorted(k for k in s(base) if k in base)))\n")

    def probe(self, passthrough):
        with tempfile.TemporaryDirectory() as home:
            Path(home, 'config.yaml').write_text('terminal:\n  env_passthrough:\n' + ''.join(f'  - {n}\n' for n in passthrough))
            result = subprocess.run([str(HERMES / 'venv/bin/python'), '-c', self.PROBE], capture_output=True, text=True, cwd=HERMES,
                                    env={'PATH': os.environ['PATH'], 'HERMES_HOME': home})
        return json.loads(result.stdout.strip().splitlines()[-1]), result.stderr

    def test_dedicated_name_propagates_and_provider_credential_name_does_not(self):
        names, warning = self.probe(['FACTORY_SIMILARITY_API_KEY', 'OPENROUTER_API_KEY'])
        self.assertIn('FACTORY_SIMILARITY_API_KEY', names)
        self.assertNotIn('OPENROUTER_API_KEY', names)
        self.assertIn('GHSA-rhgp-j443-p4rf', warning)

    def test_the_doctor_agrees_with_hermes_about_which_names_are_blocked(self):
        with mock.patch.dict(os.environ, {'HERMES_HOME': str(Path.home() / '.hermes')}):
            result = subprocess.run([str(HERMES / 'venv/bin/python'), '-c',
                                     'import sys;sys.path.insert(0,%r);import factory_secrets as f;print(f.provider_blocked("OPENROUTER_API_KEY"),f.provider_blocked("FACTORY_SIMILARITY_API_KEY"))' % str(ROOT / 'scripts')],
                                    capture_output=True, text=True)
        self.assertEqual(result.stdout.strip().splitlines()[-1], 'True False')


if __name__ == '__main__':
    unittest.main()
