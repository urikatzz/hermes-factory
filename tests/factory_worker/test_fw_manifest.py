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


class OwnedStartCheckTests(unittest.TestCase):
    """A repair task may start when the files it is assigned to repair already differ from the baseline manifest; nothing else may."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.factory').mkdir()
        (self.root / '.factory/PLAN.md').write_text('AC1: x\n')
        for rel in ('Assets/wall.png', 'Assets/floor.png', 'Assets/door.png', 'code/main.py'):
            path = self.root / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('original ' + rel)
        (self.root / '.factory/include.txt').write_text('Assets\ncode\n')
        self.run_fw('manifest')
        self.baseline = json.loads(self.run_fw('check')[1])['sha12']

    def run_fw(self, *args):
        run = subprocess.run([sys.executable, str(FW), *args[:1], str(self.root), *args[1:]], capture_output=True, text=True)
        return run.returncode, run.stdout, run.stderr

    def check(self, *flags):
        code, out, err = self.run_fw('check', '--expect', self.baseline, *flags)
        return code, (json.loads(out) if out.strip() else {}), err

    def change(self, *rels):
        for rel in rels:
            (self.root / rel).write_text('changed by an earlier attempt: ' + rel)

    def test_a_normal_check_still_fails_on_any_difference(self):
        self.change('Assets/wall.png')
        code, out, _ = self.check()
        self.assertEqual((code, out['mismatched']), (4, ['Assets/wall.png']))
        self.assertNotIn('start_check', out)

    def test_a_non_repair_check_with_no_differences_passes_and_records_nothing_extra(self):
        code, out, _ = self.check()
        self.assertEqual((code, out['ok']), (0, True))

    def test_differences_confined_to_the_owned_files_are_accepted_and_recorded(self):
        self.change('Assets/wall.png', 'Assets/floor.png')
        code, out, _ = self.check('--owned', 'Assets/wall.png,Assets/floor.png')
        self.assertEqual((code, out['ok']), (0, True))
        record = out['start_check']
        self.assertEqual(record['baseline_sha12'], self.baseline)
        self.assertEqual(record['differed'], ['Assets/floor.png', 'Assets/wall.png'])
        self.assertEqual(record['accepted_owned'], ['Assets/floor.png', 'Assets/wall.png'])
        self.assertEqual(record['rejected_outside_scope'], [])

    def test_a_difference_outside_the_owned_files_still_blocks(self):
        self.change('code/main.py')
        code, out, _ = self.check('--owned', 'Assets/wall.png,Assets/floor.png')
        self.assertEqual((code, out['ok'], out['mismatched']), (4, False, ['code/main.py']))
        self.assertEqual(out['start_check']['accepted_owned'], [])

    def test_mixed_differences_block_and_name_only_the_outside_file(self):
        self.change('Assets/wall.png', 'Assets/door.png')
        code, out, _ = self.check('--owned', 'Assets/wall.png,Assets/floor.png')
        self.assertEqual((code, out['mismatched']), (4, ['Assets/door.png']))
        self.assertEqual(out['start_check']['accepted_owned'], ['Assets/wall.png'])
        self.assertEqual(out['start_check']['rejected_outside_scope'], ['Assets/door.png'])

    def test_a_missing_owned_file_is_never_accepted(self):
        (self.root / 'Assets/wall.png').unlink()
        code, out, _ = self.check('--owned', 'Assets/wall.png')
        self.assertEqual((code, out['ok'], out['missing']), (4, False, ['Assets/wall.png']))

    def test_ownership_that_is_missing_empty_ambiguous_or_unsafe_fails_closed(self):
        self.change('Assets/wall.png')
        for owned in ('', ',', 'Assets/*.png', 'Assets', 'not/in/the/manifest.png', '../etc/passwd', '/abs/wall.png'):
            with self.subTest(owned=owned):
                code, out, err = self.check('--owned', owned)
                self.assertIn(code, (2, 3), (owned, out, err))   # refused: never exit 0 and never ok
                self.assertFalse(out.get('ok', False))

    def test_the_baseline_is_never_rewritten_and_a_wrong_expected_baseline_still_fails(self):
        before = (self.root / '.factory/SHA256SUMS').read_text()
        self.change('Assets/wall.png')
        self.check('--owned', 'Assets/wall.png')
        self.assertEqual((self.root / '.factory/SHA256SUMS').read_text(), before)
        code, out, _ = self.run_fw('check', '--expect', 'deadbeef0000', '--owned', 'Assets/wall.png')
        self.assertEqual(code, 5)


class OwnedStartCheckAgainstTheBaselineSnapshotTests(OwnedStartCheckTests):
    """The on-disk manifest was rebuilt (by a blocked worker's `fw.py manifest`) after the baseline: the check compares against the baseline snapshot instead."""

    def setUp(self):
        super().setUp()
        import tarfile
        self.tgz = self.root.parent / (self.root.name + '-baseline.tgz')
        self.addCleanup(lambda: self.tgz.unlink(missing_ok=True))
        with tarfile.open(self.tgz, 'w:gz') as tar:
            tar.add(self.root / '.factory/SHA256SUMS', arcname='.factory/SHA256SUMS')

    def rebuild_manifest(self):
        self.run_fw('manifest')   # what a worker that finishes BLOCKED used to do: the on-disk manifest now describes the changed files

    def snapshot_check(self, *flags, expect=None):
        code, out, err = self.run_fw('check', '--expect', expect or self.baseline, *flags, '--baseline-tgz', str(self.tgz))
        return code, (json.loads(out) if out.strip() else {}), err

    def test_a_rebuilt_manifest_no_longer_blocks_a_repair_whose_only_differences_are_its_own_files(self):
        self.change('Assets/wall.png', 'Assets/floor.png'); self.rebuild_manifest()
        self.assertEqual(self.check()[0], 5)   # the plain check cannot pass any more: the manifest on disk is not the baseline
        code, out, _ = self.snapshot_check('--owned', 'Assets/wall.png,Assets/floor.png')
        self.assertEqual((code, out['ok']), (0, True))
        record = out['start_check']
        self.assertEqual((record['baseline_sha12'], record['manifest_rebuilt_since_baseline']), (self.baseline, True))
        self.assertNotEqual(record['current_manifest_sha12'], self.baseline)
        self.assertEqual(record['accepted_owned'], ['Assets/floor.png', 'Assets/wall.png'])
        self.assertEqual(record['rejected_outside_scope'], [])

    def test_the_on_disk_manifest_is_not_rewritten_by_the_check(self):
        self.change('Assets/wall.png'); self.rebuild_manifest()
        before = (self.root / '.factory/SHA256SUMS').read_bytes()
        self.snapshot_check('--owned', 'Assets/wall.png')
        self.assertEqual((self.root / '.factory/SHA256SUMS').read_bytes(), before)

    def test_an_unrelated_change_still_blocks_even_though_the_rebuilt_manifest_describes_it(self):
        self.change('Assets/wall.png', 'code/main.py'); self.rebuild_manifest()
        code, out, _ = self.snapshot_check('--owned', 'Assets/wall.png')
        self.assertEqual((code, out['ok'], out['mismatched']), (4, False, ['code/main.py']))

    def test_a_file_added_to_the_rebuilt_manifest_outside_the_owned_files_blocks(self):
        self.change('Assets/wall.png'); self.write_new('Assets/extra.png'); self.rebuild_manifest()
        code, out, _ = self.snapshot_check('--owned', 'Assets/wall.png')
        self.assertEqual((code, out['ok']), (4, False))
        self.assertEqual(out['start_check']['added_outside_scope'], ['Assets/extra.png'])

    def write_new(self, rel):
        (self.root / rel).write_text('new file')

    def test_a_snapshot_that_is_not_the_expected_baseline_or_unreadable_fails_closed(self):
        self.change('Assets/wall.png')
        for kwargs in (dict(expect='deadbeef0000'),):
            code, out, err = self.snapshot_check('--owned', 'Assets/wall.png', **kwargs)
            self.assertEqual(code, 5, (out, err))
        bad = self.root.parent / (self.root.name + '-bad.tgz'); bad.write_text('not a tarball'); self.addCleanup(lambda: bad.unlink(missing_ok=True))
        code, out, _ = self.run_fw('check', '--expect', self.baseline, '--owned', 'Assets/wall.png', '--baseline-tgz', str(bad))
        self.assertEqual(code, 4)
        code, out, _ = self.run_fw('check', '--expect', self.baseline, '--owned', 'Assets/wall.png', '--baseline-tgz', '/no/such.tgz')
        self.assertEqual(code, 2)

    def test_a_baseline_snapshot_without_owned_files_is_refused(self):
        code, out, _ = self.run_fw('check', '--expect', self.baseline, '--baseline-tgz', str(self.tgz))
        self.assertEqual(code, 2)


class DeltaWithoutABaselineTests(unittest.TestCase):
    """BASELINE_TGZ none on a card means no earlier snapshot: delta answers with the whole manifest instead of failing and tricking a reviewer into a tool incident."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'src'; (self.root / '.factory').mkdir(parents=True)
        (self.root / '.factory/PLAN.md').write_text('AC1: x\n'); (self.root / 'a.txt').write_text('a'); (self.root / '.factory/include.txt').write_text('a.txt\n')
        subprocess.run([sys.executable, str(FW), 'manifest', str(self.root)], check=True, capture_output=True)
        self.out = Path(self.temp.name) / 'delta.diff'

    def delta(self, base):
        run = subprocess.run([sys.executable, str(FW), 'delta', base, str(self.root), str(self.out)], capture_output=True, text=True)
        return run.returncode, (json.loads(run.stdout) if run.stdout.strip() else {})

    def test_none_is_a_normal_answer_with_an_explanatory_diff_file(self):
        code, out = self.delta('none')
        self.assertEqual((code, out['baseline'], out['changed_files']), (0, 'none', []))
        self.assertIn('review the whole manifest', out['note'])
        self.assertIn('no baseline snapshot', self.out.read_text())

    def test_none_still_refuses_a_broken_manifest_and_a_relative_output_path(self):
        (self.root / 'a.txt').write_text('tampered')
        code, out = self.delta('none')
        self.assertEqual(code, 4); self.assertIn('fails its manifest', out['error'])
        run = subprocess.run([sys.executable, str(FW), 'delta', 'none', str(self.root), 'relative.diff'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)

    def test_a_missing_baseline_file_that_is_not_none_still_fails(self):
        self.assertEqual(self.delta(str(Path(self.temp.name) / 'absent.tgz'))[0], 2)

