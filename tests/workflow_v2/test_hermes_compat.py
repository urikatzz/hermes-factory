import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'runtime/factory-dashboard'))
from factory_dashboard import hermes_compat as hc  # noqa: E402


def fake_plugins(hooks):
    package, module = types.ModuleType('hermes_cli'), types.ModuleType('hermes_cli.plugins')
    package.plugins = module; module.VALID_HOOKS = set(hooks)
    return {'hermes_cli': package, 'hermes_cli.plugins': module}


class CompatTests(unittest.TestCase):
    def report(self, modules=hc.REQUIRED_MODULES, hooks=hc.REQUIRED_HOOKS):
        with mock.patch.object(hc, '_has_module', lambda name: name in modules), mock.patch.dict(sys.modules, fake_plugins(hooks)):
            return hc.compat_report()

    def test_a_patched_hermes_is_ok(self):
        report = self.report()
        self.assertTrue(report['ok']); self.assertEqual(report['message'], '')

    def test_a_missing_patch_module_is_reported_by_name(self):
        report = self.report(modules=hc.REQUIRED_MODULES[1:])
        self.assertFalse(report['ok'])
        self.assertEqual(report['missing_modules'], [hc.REQUIRED_MODULES[0]])
        self.assertIn('kanban_db_mutation_guard', report['message'])
        self.assertIn('hermes_patches.py apply', report['remedy'])

    def test_a_hook_name_hermes_does_not_know_is_reported(self):
        report = self.report(hooks=[h for h in hc.REQUIRED_HOOKS if h != 'before_kanban_task_mutation'])
        self.assertFalse(report['ok']); self.assertEqual(report['missing_hooks'], ['before_kanban_task_mutation'])

    def test_an_unimportable_plugin_manager_counts_every_hook_as_missing(self):
        with mock.patch.object(hc, '_has_module', lambda name: True), mock.patch.dict(sys.modules, {'hermes_cli': None}):
            report = hc.compat_report()
        self.assertFalse(report['ok']); self.assertEqual(report['missing_hooks'], list(hc.REQUIRED_HOOKS))


if __name__ == '__main__':
    unittest.main()
