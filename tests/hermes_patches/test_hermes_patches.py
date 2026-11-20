import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/hermes-patches'))
import hermes_patches as hp  # noqa: E402

BASE_A = ''.join(f'x{i} = {i}\n' for i in range(1, 41))


def git(path, *args):
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args], check=True, capture_output=True)


def upstream(path):
    path.mkdir(parents=True)
    git(path, 'init', '-q')
    (path / 'hermes_cli').mkdir()
    (path / 'hermes_cli/a.py').write_text(BASE_A)
    git(path, 'add', '.'); git(path, 'commit', '-q', '-m', 'upstream')
    return path


def patched(path):
    upstream(path)
    (path / 'hermes_cli/a.py').write_text(BASE_A.replace('x3 = 3\n', 'x3 = 300  # patched\n'))
    (path / 'hermes_cli/guard.py').write_text('GUARD_VERSION = 1\n')
    return path


class PatchSetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch_dir = self.root / 'set'; (self.patch_dir / 'patches').mkdir(parents=True)
        for name, value in (('PATCHES', self.patch_dir / 'patches'), ('MANIFEST', self.patch_dir / 'manifest.json')):
            patcher = mock.patch.object(hp, name, value); patcher.start(); self.addCleanup(patcher.stop)
        (self.patch_dir / 'manifest.json').write_text(json.dumps(dict(format=1, verified_with=[], patches=[
            dict(id='0001-core', description='guard', pathspecs=['hermes_cli'], files=[])])))
        self.tree = patched(self.root / 'tree')
        self.assertEqual(self.run_cli('export', '--tree', str(self.tree))[0], 0)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(Path, 'home', return_value=self.root):
            code = hp.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def test_export_records_files_hashes_and_the_upstream_commit(self):
        manifest = json.loads((self.patch_dir / 'manifest.json').read_text())
        files = {f['path']: f for f in manifest['patches'][0]['files']}
        self.assertEqual(set(files), {'hermes_cli/a.py', 'hermes_cli/guard.py'})
        self.assertTrue(files['hermes_cli/guard.py']['new'] and not files['hermes_cli/a.py']['new'])
        self.assertEqual(len(manifest['verified_with'][0]), 40)

    def test_a_patched_tree_is_applied_and_a_pristine_one_is_missing_but_appliable(self):
        self.assertEqual(self.run_cli('--source', str(self.tree), 'status')[0], 0)
        clean = upstream(self.root / 'clean')
        code, out = self.run_cli('--source', str(clean), 'status')
        self.assertEqual(code, 1); self.assertIn('missing', out)

    def test_apply_restores_the_patch_and_backs_up_replaced_files(self):
        clean = upstream(self.root / 'clean')
        self.assertEqual(self.run_cli('--source', str(clean), 'apply', '--dry-run')[0], 0)
        self.assertFalse((clean / 'hermes_cli/guard.py').exists())  # a dry run changes nothing
        code, out = self.run_cli('--source', str(clean), 'apply')
        self.assertEqual(code, 0, out)
        self.assertEqual((clean / 'hermes_cli/guard.py').read_text(), 'GUARD_VERSION = 1\n')
        self.assertIn('x3 = 300  # patched', (clean / 'hermes_cli/a.py').read_text())
        self.assertEqual(self.run_cli('--source', str(clean), 'status')[0], 0)
        self.assertTrue(list((self.root / '.hermes/backups').glob('hermes-patches-*/hermes_cli/a.py')))
        self.assertEqual(self.run_cli('--source', str(clean), 'apply')[1].strip(), 'Nothing to apply: every patch is present.')  # idempotent

    def test_a_conflicting_upstream_change_is_reported_and_nothing_is_applied(self):
        clean = upstream(self.root / 'clean')
        (clean / 'hermes_cli/a.py').write_text(BASE_A.replace('x3 = 3\n', 'x3 = 33  # rewritten upstream\n'))
        git(clean, 'commit', '-qam', 'upstream moved')
        code, out = self.run_cli('--source', str(clean), 'status')
        self.assertEqual(code, 2); self.assertIn('conflict', out)
        before = (clean / 'hermes_cli/a.py').read_text()
        code, out = self.run_cli('--source', str(clean), 'apply')
        self.assertEqual(code, 2); self.assertIn('Refusing to apply', out)
        self.assertEqual((clean / 'hermes_cli/a.py').read_text(), before)
        self.assertFalse((clean / 'hermes_cli/guard.py').exists())

    def test_unrelated_upstream_drift_around_an_applied_patch_still_counts_as_applied(self):
        (self.tree / 'hermes_cli/a.py').write_text((self.tree / 'hermes_cli/a.py').read_text().replace('x38 = 38\n', 'x38 = 380\n'))
        code, out = self.run_cli('--source', str(self.tree), 'status')
        self.assertEqual(code, 0, out)
        self.assertIn('around it', out)

    def test_a_patch_that_leaves_a_file_that_does_not_compile_is_rolled_back(self):
        clean = upstream(self.root / 'clean')
        text = (self.patch_dir / 'patches/0001-core.patch').read_text().replace('GUARD_VERSION = 1', 'GUARD_VERSION = = 1')
        (self.patch_dir / 'patches/0001-core.patch').write_text(text)
        before = (clean / 'hermes_cli/a.py').read_text()
        code, out = self.run_cli('--source', str(clean), 'apply')
        self.assertEqual(code, 2); self.assertIn('does not compile', out)
        self.assertEqual((clean / 'hermes_cli/a.py').read_text(), before)
        self.assertFalse((clean / 'hermes_cli/guard.py').exists())

    def test_a_removed_file_is_missing_again(self):
        (self.tree / 'hermes_cli/guard.py').unlink()
        git(self.tree, 'checkout', 'hermes_cli/a.py')  # an update resets tracked files too
        self.assertEqual(self.run_cli('--source', str(self.tree), 'status')[0], 1)

    def test_export_refuses_an_unmodified_tree(self):
        code, out = self.run_cli('export', '--tree', str(upstream(self.root / 'plain')))
        self.assertEqual(code, 2); self.assertIn('No changes under', out)


if __name__ == '__main__':
    unittest.main()
