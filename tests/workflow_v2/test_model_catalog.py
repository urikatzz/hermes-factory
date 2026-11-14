import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/factory-dashboard'))

from factory_dashboard.catalog_export import export_catalog
from factory_dashboard.model_catalog import ModelCatalog
from factory_dashboard.model_policy import ModelSelection


def document(*models):
    entries = [dict(provider=p, model=m) for p, m in models]
    return dict(profiles=dict(developer=dict(default=entries[0], models=entries)))


class ModelCatalogTests(unittest.TestCase):
    def write(self, path, data, stamp):
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        os.utime(path, ns=(stamp, stamp))

    def test_reexported_catalog_is_served_without_restart_and_bad_file_keeps_last_good(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model-catalog.json'
            self.write(path, document(('openai-codex', 'gpt-6-sol')), 1_000_000_000)
            catalog = ModelCatalog.from_file(path)
            self.assertEqual([c.model for c in catalog.choices(('developer',))], ['gpt-6-sol'])
            self.write(path, document(('openai-codex', 'gpt-6-sol'), ('openai-codex', 'gpt-6.1-sol'), ('openrouter', 'typesafe/jev-router')), 2_000_000_000)
            self.assertEqual([(c.provider, c.model) for c in catalog.choices(('developer',))],
                             [('openai-codex', 'gpt-6-sol'), ('openai-codex', 'gpt-6.1-sol'), ('openrouter', 'typesafe/jev-router')])
            catalog.validate(ModelSelection('openrouter', 'typesafe/jev-router'), ('developer',))
            self.write(path, '{broken', 3_000_000_000)
            self.assertEqual(len(catalog.choices(('developer',))), 3)

    def test_export_lists_every_model_the_connected_providers_report(self):
        config = dict(model=dict(provider='openai-codex', default='gpt-6-sol'),
                      factory_models=[dict(provider='openai-codex', model='gpt-6.1-sol'), dict(provider='openrouter', model='typesafe/jev-router')])
        models = export_catalog(['developer'], lambda role: config)['profiles']['developer']['models']
        self.assertEqual([(m['provider'], m['model']) for m in models],
                         [('openai-codex', 'gpt-6-sol'), ('openai-codex', 'gpt-6.1-sol'), ('openrouter', 'typesafe/jev-router')])


if __name__ == '__main__':
    unittest.main()
