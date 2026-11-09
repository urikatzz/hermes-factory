import tempfile
import unittest
from pathlib import Path

import factory_copy  # noqa: F401
from factory_dashboard import workflow_types as wt
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_templates import WorkflowTemplates, _preset
from factory_dashboard.workflow_types import WorkflowDefinition

AUDIO = ('audio-director', 'sound-designer', 'audio-reviewer')


class AudioTypeTest(unittest.TestCase):
    def test_capabilities(self):
        self.assertEqual(wt.CAPABILITIES['audio-director'], ('prepare',))
        self.assertEqual(wt.CAPABILITIES['sound-designer'], ('implement', 'repair'))
        self.assertEqual(wt.CAPABILITIES['audio-reviewer'], ('review',))
        self.assertEqual(wt.TASK_TYPES, ('feature', 'bug', 'chore', 'art', 'audio'))

    def test_preset(self):
        doc = _preset('audio')
        self.assertEqual(doc['name'], 'Game Audio')
        self.assertEqual(doc['prepare']['profile'], 'audio-director')
        self.assertEqual(doc['implement']['profile'], 'sound-designer')
        self.assertEqual(doc['repair']['profile'], 'sound-designer')
        self.assertEqual([r['profile'] for r in doc['reviewers']], ['audio-reviewer', 'claude-reviewer'])
        self.assertEqual(doc['verify']['profile'], 'verifier')
        self.assertEqual(doc['max_repairs'], 2)
        self.assertIn('audio_lint.py', doc['verify']['instructions'])
        self.assertIn('--fail-on-blocking', doc['implement']['instructions'])
        self.assertIn('--check-bible', doc['prepare']['instructions'])

    def test_preset_validates(self):
        for kind in wt.TASK_TYPES:
            WorkflowDefinition.from_document(_preset(kind))
        doc = _preset('audio')
        doc['implement'] = dict(doc['implement'], profile='audio-reviewer')
        with self.assertRaises(ConfigurationError):
            WorkflowDefinition.from_document(doc)
        self.assertTrue(hasattr(WorkflowTemplates, 'save'))

    def test_audio_reviewer_can_join_any_template(self):
        doc = _preset('feature')
        doc['reviewers'].append(dict(key='audio-reviewer', kind='review', profile='audio-reviewer', instructions=''))
        self.assertIn('audio-reviewer', [s.profile for s in WorkflowDefinition.from_document(doc).reviewers])

    def test_art_unchanged(self):
        art = _preset('art')
        self.assertEqual(art['name'], 'Game Art')
        self.assertEqual(art['implement']['profile'], 'artist')
        self.assertEqual(art['max_repairs'], 2)
        self.assertEqual(_preset('feature')['max_repairs'], 3)

    def test_a_fresh_store_seeds_game_audio_as_the_audio_default(self):
        with tempfile.TemporaryDirectory() as temp:
            templates = WorkflowTemplates(TaskSettingsStore(Path(temp) / 'settings.db'))
            templates.initialize()
            mapping = templates.defaults()['templates']
            self.assertEqual(templates.get(mapping['audio']).name, 'Game Audio')
            self.assertEqual(templates.get(mapping['art']).name, 'Game Art')


if __name__ == '__main__':
    unittest.main()
