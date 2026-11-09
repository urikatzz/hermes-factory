import filecmp
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, LIVE

LIVE_PLUGIN = LIVE / 'plugins/factory-models'


class BundleTests(unittest.TestCase):
    def test_bundle_from_the_copy_carries_the_art_type(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'factory-models'
            result = subprocess.run([sys.executable, str(DASHBOARD / 'scripts/bundle_factory_plugin.py'), str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('workflow_types.py', 'workflow_templates.py', 'workflow_cards.py', 'workflow_controller.py'):
                self.assertTrue(filecmp.cmp(out / 'factory_dashboard' / name, DASHBOARD / 'factory_dashboard' / name,
                                            shallow=False), name)
            probe = subprocess.run([sys.executable, '-c', 'from factory_dashboard.workflow_types import TASK_TYPES, '
                                    'CAPABILITIES; print(TASK_TYPES[-1], CAPABILITIES["artist"])'],
                                   capture_output=True, text=True, cwd=out)
            self.assertEqual(probe.stdout.strip(), "art ('implement', 'repair')", probe.stderr)
            if LIVE_PLUGIN.is_dir():
                for name in ('plugin.yaml', '__init__.py'):
                    self.assertTrue(filecmp.cmp(out / name, LIVE_PLUGIN / name, shallow=False), name)
