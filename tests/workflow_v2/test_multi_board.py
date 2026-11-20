"""Runs the multi-board scenarios in a subprocess: Hermes keeps process-global board state that must not leak into other suites."""
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'runtime/factory-dashboard'))


class MultiBoardScenarios(unittest.TestCase):
    def test_scenarios(self):
        try:
            import hermes_cli  # noqa: F401  (the real Hermes checkout is required; the harness adds it to sys.path)
        except ImportError:
            hermes = Path.home() / '.hermes/hermes-agent'
            if not hermes.is_dir():
                self.skipTest('Hermes checkout not available')
        done = subprocess.run([sys.executable, str(HERE / 'multi_board_scenarios.py')], cwd=HERE, capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr[-6000:])


if __name__ == '__main__':
    unittest.main()
