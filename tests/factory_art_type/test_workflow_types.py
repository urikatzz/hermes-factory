import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import factory_copy  # noqa: F401
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_templates import WorkflowTemplates, _preset
from factory_dashboard.workflow_types import CAPABILITIES, TASK_TYPES, WorkflowDefinition


def definition(kind):
    return WorkflowDefinition.from_document(_preset(kind))


class CapabilityTests(unittest.TestCase):
    def test_new_profiles_have_their_capabilities(self):
        self.assertEqual(CAPABILITIES['art-director'], ('prepare',))
        self.assertEqual(CAPABILITIES['artist'], ('implement', 'repair'))
        self.assertEqual(CAPABILITIES['art-reviewer'], ('review',))
        self.assertEqual(TASK_TYPES, ('feature', 'bug', 'chore', 'art'))

    def test_art_reviewer_can_join_any_template(self):
        doc = _preset('feature')
        doc['reviewers'].append(dict(key='art-reviewer', kind='review', profile='art-reviewer', instructions=''))
        self.assertIn('art-reviewer', [s.profile for s in WorkflowDefinition.from_document(doc).reviewers])

    def test_profiles_cannot_take_stages_outside_their_capability(self):
        for field, profile in (('implement', 'art-director'), ('prepare', 'artist'), ('verify', 'art-reviewer')):
            doc = _preset('art')
            doc[field] = dict(doc[field], profile=profile)
            with self.assertRaises(ConfigurationError, msg=field):
                WorkflowDefinition.from_document(doc)
        doc = _preset('art')
        doc['reviewers'].append(dict(key='artist', kind='review', profile='artist', instructions=''))
        with self.assertRaises(ConfigurationError):
            WorkflowDefinition.from_document(doc)


class GameArtPresetTests(unittest.TestCase):
    def test_game_art_preset_shape(self):
        art = definition('art')
        self.assertEqual((art.name, art.task_type, art.max_repairs), ('Game Art', 'art', 2))
        self.assertEqual((art.prepare.profile, art.implement.profile, art.repair.profile, art.verify.profile),
                         ('art-director', 'artist', 'artist', 'verifier'))
        self.assertEqual([s.profile for s in art.reviewers], ['art-reviewer', 'claude-reviewer'])
        self.assertIn('--fail-on-blocking', art.verify.instructions)
        self.assertIn('art_lint.py', art.verify.instructions)
        self.assertIn('--check-bible', art.prepare.instructions)
        self.assertIn('no approved style bible: submit an Art task asking for a style bible', art.prepare.instructions)
        self.assertIn('not judge art taste', art.reviewers[1].instructions)
        self.assertIn('art-review skill', art.reviewers[0].instructions)
        self.assertIn('style_sha256', art.prepare.instructions)
        self.assertIn('--style-hash', art.prepare.instructions)
        for stage in (art.implement, art.repair, art.verify):
            self.assertIn('--expect-style-hash', stage.instructions)

    def test_writers_and_readers_stay_independent(self):
        art = definition('art')
        writers = {art.implement.profile, art.repair.profile}
        readers = {s.profile for s in art.reviewers} | {art.verify.profile}
        self.assertFalse(writers & readers)
        self.assertNotIn(art.prepare.profile, readers)

    def test_a_code_reviewer_is_still_required(self):
        doc = _preset('art')
        doc['reviewers'] = [r for r in doc['reviewers'] if r['profile'] != 'claude-reviewer']
        with self.assertRaisesRegex(ConfigurationError, 'code reviewer'):
            WorkflowDefinition.from_document(doc)

    def test_existing_presets_are_unchanged(self):
        chore = asdict(definition('chore'))
        chore.pop('template_id')
        stage = lambda key, profile, text='', kind=None: dict(key=key, kind=kind or key, profile=profile, instructions=text)
        self.assertEqual(chore, dict(
            revision=1, name='Chore', description='', task_type='chore',
            prepare=stage('prepare', 'developer', 'Define the scope and demonstrate no unintended behavior change.'),
            implement=stage('implement', 'developer'), reviewers=(stage('claude-reviewer', 'claude-reviewer', kind='review'),),
            verify=stage('verify', 'verifier'), repair=stage('repair', 'fixer'), max_repairs=3))
        self.assertEqual([s.profile for s in definition('feature').reviewers],
                         ['claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer'])
        self.assertEqual(definition('bug').repair.profile, 'fixer')

    def test_a_fresh_store_seeds_game_art_as_the_art_default(self):
        with tempfile.TemporaryDirectory() as temp:
            templates = WorkflowTemplates(TaskSettingsStore(Path(temp) / 'settings.db'))
            templates.initialize()
            mapping = templates.defaults()['templates']
            self.assertEqual(sorted(mapping), ['art', 'bug', 'chore', 'feature'])
            self.assertEqual(templates.get(mapping['art']).name, 'Game Art')
