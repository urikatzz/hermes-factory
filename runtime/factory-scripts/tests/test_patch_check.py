import json
import os
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sandbox import Sandbox, SCRIPTS  # noqa: E402

TOOL = os.path.join(os.path.dirname(SCRIPTS), "hermes-patches", "hermes_patches.py")
BASE = "".join("x%d = %d\n" % (i, i) for i in range(1, 41))


def git(path, *args):
    subprocess.run(["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@example.com", *args], check=True, capture_output=True)


class PatchCheckTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(); self.addCleanup(self.sb.cleanup)
        hermes = os.path.join(self.sb.home, ".hermes")
        self.source = os.path.join(hermes, "hermes-agent")
        self.patches = os.path.join(hermes, "hermes-patches")
        self.upstream_commit = self.make_tree(self.source, patched=False)
        # build the patch set with the real tool from a patched sibling tree
        shutil.copy(TOOL, self.patches if os.path.isdir(self.patches) else self.mkdir(self.patches))
        with open(os.path.join(self.patches, "manifest.json"), "w") as f:
            json.dump(dict(format=1, verified_with=[], patches=[dict(id="0001-core", description="guard", pathspecs=["hermes_cli"], files=[])]), f)
        os.makedirs(os.path.join(self.patches, "patches"))
        reference = self.make_tree(os.path.join(self.sb.root, "reference"), patched=True)
        done = subprocess.run([sys.executable, os.path.join(self.patches, "hermes_patches.py"), "export", "--tree", os.path.join(self.sb.root, "reference")],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def mkdir(self, path):
        os.makedirs(path); return path

    def make_tree(self, path, patched):
        os.makedirs(os.path.join(path, "hermes_cli"))
        git(path, "init", "-q")
        with open(os.path.join(path, "hermes_cli", "a.py"), "w") as f:
            f.write(BASE)
        git(path, "add", "."); git(path, "commit", "-q", "-m", "up")
        if patched:
            with open(os.path.join(path, "hermes_cli", "a.py"), "w") as f:
                f.write(BASE.replace("x3 = 3\n", "x3 = 300\n"))
            with open(os.path.join(path, "hermes_cli", "guard.py"), "w") as f:
                f.write("GUARD_VERSION = 1\n")
        return path

    def apply_by_hand(self):
        subprocess.run([sys.executable, os.path.join(self.patches, "hermes_patches.py"), "apply"], env=dict(os.environ, HOME=self.sb.home), check=True, capture_output=True)

    def state(self):
        return self.sb.state("hermes-patches.json")

    def check(self, *flags):
        done = self.sb.run("factory_patch_check.py", *flags)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def age_problem(self, seconds=1000):
        state = self.state(); state["first_seen"] = int(time.time()) - seconds
        self.sb.set_state("hermes-patches.json", state)

    def test_healthy_tree_is_silent_and_recorded_ok(self):
        self.apply_by_hand()
        self.assertEqual(self.check(), "")
        self.assertTrue(self.state()["ok"])

    def install_probe(self, ok, detail=""):
        with open(os.path.join(self.patches, "probe_owner_model.py"), "w") as f:
            f.write("def probe(source):\n    return dict(ok=%r, detail=%r)\n" % (ok, detail))

    def test_applied_patches_that_do_not_work_are_reported_once_with_the_symptom(self):
        self.apply_by_hand(); self.install_probe(False, "the owner ignored the captured selection")
        out = self.check()
        self.assertIn("APPLIED BUT DO NOT WORK", out); self.assertIn("the owner ignored the captured selection", out)
        self.assertFalse(self.state()["behavior"]["ok"])
        self.assertEqual(self.check(), "")   # not re-announced every run

    def test_a_working_probe_is_silent_and_a_probe_that_cannot_run_is_recorded_but_not_reported_as_broken(self):
        self.apply_by_hand(); self.install_probe(True)
        self.assertEqual(self.check(), ""); self.assertTrue(self.state()["behavior"]["ok"])
        os.remove(os.path.join(self.patches, "probe_owner_model.py"))
        state = self.state(); state["behavior"] = {}; self.sb.set_state("hermes-patches.json", state)
        self.assertEqual(self.check(), "")
        self.assertIsNone(self.state()["behavior"]["ok"]); self.assertIn("could not run", self.state()["behavior"]["detail"])

    def test_missing_patches_alert_once_and_are_recorded(self):
        out = self.check()
        self.assertIn("HERMES PATCHES missing: 0001-core", out); self.assertIn("New factory work is paused", out)
        state = self.state()
        self.assertFalse(state["ok"]); self.assertEqual(state["missing"], ["0001-core"])
        self.assertEqual(self.check(), "")  # the same problem is not re-announced every run

    def test_restoring_by_hand_is_announced_once(self):
        self.check(); self.apply_by_hand()
        self.assertIn("present again", self.check())
        self.assertEqual(self.check(), "")

    def test_repair_waits_for_the_problem_to_settle_and_for_a_running_update(self):
        self.check()
        self.assertFalse(os.path.exists(os.path.join(self.source, "hermes_cli", "guard.py")))  # first sighting: an update may still be writing
        self.age_problem()
        self.sb._write_exe("pgrep", "echo 4242\nexit 0")  # an update is running
        self.assertEqual(self.check(), "")
        self.assertFalse(os.path.exists(os.path.join(self.source, "hermes_cli", "guard.py")))
        self.sb._write_exe("pgrep", "exit 1")
        out = self.check()
        self.assertIn("HERMES PATCHES REAPPLIED (0001-core)", out); self.assertIn("Restart the Hermes gateway", out)
        self.assertTrue(os.path.exists(os.path.join(self.source, "hermes_cli", "guard.py")))
        self.assertTrue(self.state()["ok"])
        self.assertEqual(self.check(), "")

    def test_a_git_lock_also_blocks_repair(self):
        self.check(); self.age_problem()
        open(os.path.join(self.source, ".git", "index.lock"), "w").close()
        self.check()
        self.assertFalse(os.path.exists(os.path.join(self.source, "hermes_cli", "guard.py")))

    def test_check_only_never_applies_even_when_settled(self):
        self.check("--check-only"); self.age_problem()
        self.check("--check-only")
        self.assertFalse(os.path.exists(os.path.join(self.source, "hermes_cli", "guard.py")))
        self.assertFalse(self.state()["ok"])

    def test_a_conflict_is_reported_and_never_repaired(self):
        with open(os.path.join(self.source, "hermes_cli", "a.py"), "w") as f:
            f.write(BASE.replace("x3 = 3\n", "x3 = 33\n"))
        git(self.source, "commit", "-qam", "upstream moved")
        out = self.check()
        self.assertIn("conflict with this Hermes version", out)
        self.age_problem()
        self.check()
        self.assertFalse(os.path.exists(os.path.join(self.source, "hermes_cli", "guard.py")))
        self.assertEqual(self.state()["conflicts"], ["0001-core"])

    def test_intake_pauses_while_patches_are_missing_and_resumes_when_restored(self):
        probe = "import factory_lib; print(factory_lib.hermes_patches_ok())"
        env = dict(os.environ, HOME=self.sb.home)
        ask = lambda: subprocess.run([sys.executable, "-c", probe], cwd=SCRIPTS, env=env, capture_output=True, text=True).stdout.strip()
        self.assertEqual(ask(), "True")  # no guard result yet: not blocked
        self.check(); self.assertEqual(ask(), "False")
        state = self.state(); state["checked_at"] = int(time.time()) - 7200  # a stale result does not block
        self.sb.set_state("hermes-patches.json", state); self.assertEqual(ask(), "True")
        self.apply_by_hand(); self.check(); self.assertEqual(ask(), "True")


if __name__ == "__main__":
    unittest.main()
