"""The tracked copies of the factory cron scripts keep their own unit tests (fake hermes, temporary HOME); run them as part of this suite."""
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / 'runtime/factory-scripts'


class FactoryScriptTests(unittest.TestCase):
    def test_script_suite(self):
        done = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=SCRIPTS, capture_output=True, text=True, timeout=900)
        self.assertEqual(done.returncode, 0, done.stderr[-4000:])


if __name__ == '__main__':
    unittest.main()
