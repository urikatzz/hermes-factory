import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / 'runtime/factory-scripts/unity_gate.sh'


class UnityGateProjectDetectionTests(unittest.TestCase):
    """The gate finds the Unity project itself: it once defaulted to another game's `Client/BouncingGems`, so it could not run for any other project."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        (self.home / '.unity/bin').mkdir(parents=True)
        self.log = Path(self.temp.name) / 'unity-args.txt'
        stub = self.home / '.unity/bin/unity'
        stub.write_text(f'#!/bin/sh\necho "$@" > "{self.log}"\nexit 0\n'); stub.chmod(0o755)
        self.wt = Path(self.temp.name) / 'worktree'; self.wt.mkdir()

    def project(self, relative):
        base = self.wt / relative
        (base / 'Assets').mkdir(parents=True); (base / 'ProjectSettings').mkdir()
        (base / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.11f1\n')
        return base

    def run_gate(self, *args):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(['sh', str(GATE), str(self.wt), *args], capture_output=True, text=True, env=env, timeout=120)

    def unity_ran_on(self):
        words = self.log.read_text().split()
        return Path(words[words.index('test') + 1])

    def test_a_project_at_the_worktree_root_is_found(self):
        self.project('.')
        self.run_gate('EditMode')
        self.assertEqual(self.unity_ran_on().resolve(), (self.wt / '.').resolve())

    def test_a_project_in_a_subdirectory_is_found_wherever_it_is(self):
        self.project('Client/Anything')
        self.run_gate('EditMode')
        self.assertEqual(self.unity_ran_on().resolve(), (self.wt / 'Client/Anything').resolve())

    def test_an_explicit_subdirectory_still_wins(self):
        self.project('One'); self.project('Two')
        self.run_gate('EditMode', 'Two')
        self.assertEqual(self.unity_ran_on().resolve(), (self.wt / 'Two').resolve())

    def test_no_project_or_several_projects_fail_clearly_without_running_unity(self):
        done = self.run_gate('EditMode')
        self.assertEqual(done.returncode, 2); self.assertIn('no Unity project', done.stdout); self.assertFalse(self.log.exists())
        self.project('A'); self.project('B')
        done = self.run_gate('EditMode')
        self.assertEqual(done.returncode, 2); self.assertIn('more than one Unity project', done.stdout); self.assertIn('third argument', done.stdout)
        self.assertFalse(self.log.exists())

    def test_nothing_inside_library_packages_or_other_worktrees_counts_as_a_project(self):
        self.project('.')
        self.project('Library/PackageCache/x'); self.project('.worktrees/other'); self.project('Packages/vendored')
        self.run_gate('EditMode')
        self.assertEqual(self.unity_ran_on().resolve(), (self.wt / '.').resolve())

    def test_unity_exiting_zero_without_a_test_report_is_a_failure_not_a_pass(self):
        self.project('.')
        done = self.run_gate('EditMode')                                       # the stub exits 0 and writes no report
        self.assertEqual(done.returncode, 4); self.assertIn('UNITY_GATE FAIL', done.stdout); self.assertIn('no test ran', done.stdout); self.assertNotIn('PASS', done.stdout)

    def test_a_written_report_with_every_test_passing_is_a_pass(self):
        self.project('.')
        stub = self.home / '.unity/bin/unity'
        stub.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = "--output" ] && out="$2"; shift; done\necho \'<test-run result="Passed" total="3" passed="3" failed="0" skipped="0"></test-run>\' > "$out"\nexit 0\n')
        done = self.run_gate('EditMode')
        self.assertEqual(done.returncode, 0, done.stdout); self.assertIn('UNITY_GATE PASS', done.stdout); self.assertIn('passed="3"', done.stdout)

    def editor_marker(self, pid):
        folder = self.wt / 'Library'; folder.mkdir(exist_ok=True)
        (folder / 'EditorInstance.json').write_text('{\n\t"process_id" : %d,\n\t"version" : "6000.4.11f1"\n}' % pid)
        return folder / 'EditorInstance.json'

    def test_a_marker_copied_from_another_checkouts_library_is_removed_so_unity_does_not_think_the_project_is_open(self):
        self.project('.')
        marker = self.editor_marker(os.getpid())                                   # a live process, but one that does not have this project open
        self.run_gate('EditMode')
        self.assertFalse(marker.exists())

    def test_a_marker_whose_process_really_has_this_project_open_is_kept(self):
        self.project('.')
        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', str((self.wt / '.').resolve())])   # a live process whose command line names this project
        self.addCleanup(holder.kill)
        marker = self.editor_marker(holder.pid)
        self.run_gate('EditMode')
        self.assertTrue(marker.exists())

    def test_a_marker_for_a_dead_process_is_removed(self):
        self.project('.')
        marker = self.editor_marker(2 ** 22 + 12345)
        self.run_gate('EditMode')
        self.assertFalse(marker.exists())

    def test_no_game_specific_default_remains(self):
        self.assertNotIn('BouncingGems', GATE.read_text())


if __name__ == '__main__':
    unittest.main()
