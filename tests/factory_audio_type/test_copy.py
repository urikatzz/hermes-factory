import unittest
from pathlib import Path

import factory_copy as fc


class CopyTest(unittest.TestCase):
    def test_copy_is_separate_and_has_art(self):
        self.assertNotIn(fc.LIVE.resolve(), [fc.COPY, *fc.COPY.parents])
        types = (fc.DASHBOARD / 'factory_dashboard/workflow_types.py').read_text()
        self.assertIn("'art'", types)
        self.assertTrue((fc.DASHBOARD / 'integrations/hermes_factory_models/plugin.yaml').is_file())


if __name__ == '__main__':
    unittest.main()
