import unittest
from pathlib import Path

from factory_copy import COPY, DASHBOARD, LIVE
import factory_dashboard
import factory_lib


class CopyTests(unittest.TestCase):
    def test_imports_come_from_the_copy(self):
        self.assertTrue(Path(factory_dashboard.__file__).resolve().is_relative_to(DASHBOARD.resolve()))
        self.assertTrue(Path(factory_lib.__file__).resolve().is_relative_to(COPY))
        self.assertFalse(COPY.is_relative_to(LIVE.resolve()))

    def test_copy_has_the_plugin_sources_for_bundling(self):
        plugin = DASHBOARD / 'integrations/hermes_factory_models'
        self.assertTrue((plugin / 'plugin.yaml').is_file())
        self.assertTrue((plugin / '__init__.py').is_file())
        self.assertTrue((COPY / 'factory-skills/worker/factory-worker/scripts/fw.py').is_file())
