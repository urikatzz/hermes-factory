import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

FW = Path(__file__).resolve().parents[2] / 'runtime/factory-skills/worker/factory-worker/scripts/fw.py'


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.factory').mkdir()
        (self.root / '.factory/PLAN.md').write_text('AC1: x\n')

    def write(self, rel, text='data\n'):
        path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)

    def include(self, *lines):
        (self.root / '.factory/include.txt').write_text('\n'.join(lines) + '\n')

    def manifest(self, *flags):
        run = subprocess.run([sys.executable, str(FW), 'manifest', str(self.root), *flags], capture_output=True, text=True)
        return run.returncode, json.loads(run.stdout)

    def manifest_paths(self):
        return [line.split('  ', 1)[1] for line in (self.root / '.factory/SHA256SUMS').read_text().splitlines()]

    def test_a_path_a_later_task_will_create_does_not_block_an_earlier_task(self):
        self.write('art/style/STYLE.md')
        self.include('art/style/', 'Assets/Art/Room01')
        code, out = self.manifest()
        self.assertEqual(code, 0, out)
        self.assertEqual(out['deferred_missing'], ['Assets/Art/Room01'])
        self.assertNotIn('Assets/Art/Room01', ' '.join(self.manifest_paths()))
        self.write('Assets/Art/Room01/wall.png')  # the later task delivers it: now it is part of the manifest and nothing is deferred
        code, out = self.manifest()
        self.assertEqual((code, out['deferred_missing']), (0, []))
        self.assertIn('Assets/Art/Room01/wall.png', self.manifest_paths())

    def test_a_planned_mark_behaves_the_same_and_a_required_mark_fails_when_missing(self):
        self.write('keep.txt')
        self.include('keep.txt', '?later/output.txt')
        code, out = self.manifest()
        self.assertEqual((code, out['deferred_missing']), (0, ['later/output.txt']))
        self.include('keep.txt', '!inputs/spec.json  # must exist now')
        code, out = self.manifest()
        self.assertEqual(code, 3); self.assertEqual(out['missing'], ['inputs/spec.json'])

    def test_a_genuinely_missing_required_input_still_fails(self):
        self.write('keep.txt')
        self.include('keep.txt', '!baseline/config.yaml')
        code, out = self.manifest()
        self.assertEqual(code, 3)
        self.assertIn('baseline/config.yaml', out['missing'])
        self.assertFalse((self.root / '.factory/SHA256SUMS').exists())  # nothing half-written

    def test_the_final_manifest_requires_every_planned_path(self):
        self.write('keep.txt')
        self.include('keep.txt', '?later/output.txt', 'also/planned')
        code, out = self.manifest('--final')
        self.assertEqual(code, 3); self.assertEqual(sorted(out['missing']), ['also/planned', 'later/output.txt'])
        self.write('later/output.txt'); self.write('also/planned/x')
        self.assertEqual(self.manifest('--final')[0], 0)

    def test_a_path_an_earlier_manifest_delivered_cannot_vanish(self):
        self.write('data/a.txt'); self.write('docs/readme.md')
        self.include('data/a.txt', 'docs/')
        self.assertEqual(self.manifest()[0], 0)
        (self.root / 'data/a.txt').unlink()
        code, out = self.manifest()
        self.assertEqual(code, 3); self.assertEqual(out['vanished'], ['data/a.txt'])
        self.write('data/a.txt')
        self.assertEqual(self.manifest()[0], 0)

    def test_a_delivered_directory_that_disappears_is_a_vanished_input(self):
        self.write('docs/readme.md'); self.include('docs/')
        self.assertEqual(self.manifest()[0], 0)
        (self.root / 'docs/readme.md').unlink(); (self.root / 'docs').rmdir()
        code, out = self.manifest()
        self.assertEqual(code, 3); self.assertEqual(out['vanished'], ['docs'])

    def test_excluded_and_unsafe_paths_are_refused_even_when_planned(self):
        self.write('keep.txt'); self.include('keep.txt', '?.env', '?node_modules/pkg')
        code, out = self.manifest()
        self.assertEqual(code, 3)
        self.assertEqual({r['path'] for r in out['refused']}, {'.env', 'node_modules/pkg'})
        self.include('keep.txt', '?../outside')
        code, out = self.manifest()
        self.assertEqual(code, 3); self.assertFalse(out['ok'])  # an unsafe path is refused, never deferred

    def test_a_plain_complete_include_list_works_as_before(self):
        self.write('a.txt'); self.write('b/c.txt')
        self.include('# comment', '', 'a.txt', 'b/')
        code, out = self.manifest()
        self.assertEqual((code, out['deferred_missing'], out['final']), (0, [], False))
        self.assertEqual(self.manifest_paths(), ['.factory/PLAN.md', '.factory/include.txt', 'a.txt', 'b/c.txt'])


if __name__ == '__main__':
    unittest.main()
