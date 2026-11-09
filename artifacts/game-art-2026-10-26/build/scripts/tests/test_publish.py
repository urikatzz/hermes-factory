import json
import os
import subprocess
import sys
import time
import unittest

from sandbox import FW, Sandbox

RID = "t_9b1d0001"


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.env = dict(os.environ, HOME=self.sb.home, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        self.repo = os.path.join(self.sb.root, "repo")
        self.origin = os.path.join(self.sb.root, "origin.git")
        self.wt = os.path.join(self.repo, ".worktrees", "demo-0001")
        self.git("init", "-q", "-b", "main", self.repo)
        self.write(self.repo, "README.md", "demo\n")
        self.git("-C", self.repo, "add", "README.md")
        self.git("-C", self.repo, "commit", "-q", "-m", "init")
        self.git("init", "-q", "--bare", "-b", "main", self.origin)
        self.git("-C", self.repo, "remote", "add", "origin", self.origin)
        self.git("-C", self.repo, "push", "-q", "-u", "origin", "main")
        self.git("-C", self.repo, "worktree", "add", "-q", "-b", "feature/demo", self.wt, "main")
        self.write(self.wt, "src/app.txt", "hello\n")
        self.write(self.wt, ".factory/PLAN.md", "# Plan\nAC1: the app says hello\n")
        self.write(self.wt, ".factory/include.txt", "src\n")
        subprocess.run([sys.executable, FW, "manifest", self.wt], check=True, capture_output=True, env=self.env)
        body = "\n".join(["FACTORY_ROOT v2", "DELIVERY: local", "TYPE: feature", "PROJECT_MODE: existing",
                          "PROJECT_DIR: " + self.wt, "ISOLATION: worktree", "REPO_DIR: " + self.repo,
                          "BRANCH: feature/demo", "REPO: demo", "BASE_BRANCH: main", "AUTO_PR: yes", "UNITY_CI: no",
                          "SLUG: demo", "REQUEST:", "say hello", ""])
        outcome = "OUTCOME=LOCAL_DELIVERED MANIFEST=abc PROJECT_DIR=" + self.wt
        self.sb.add_task(RID, "FACTORY: Say hello", "done", body=body, summary=outcome, result=outcome,
                         completed_at=self.sb.now - 30)

    def tearDown(self):
        self.sb.cleanup()

    def git(self, *args):
        subprocess.run(["git"] + list(args), check=True, capture_output=True, text=True, env=self.env)

    @staticmethod
    def write(root, rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def register_repo(self, gate_cmd):
        self.sb.write_json(self.sb.repos_path, {"repos": {"demo": {
            "path": self.repo, "remote": "example/demo", "base": "main", "auto_pr": True,
            "writer_gates": [{"when": "src", "cmd": gate_cmd}]}}})

    def test_passing_writer_gate_opens_a_draft_pr_with_only_manifest_files(self):
        self.register_repo("true")
        r = self.sb.run("factory_publish.py", env={"GIT_CONFIG_NOSYSTEM": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PR opened (draft)", r.stdout)
        self.assertEqual(self.sb.state("published.json")[RID], {"url": "https://github.com/example/demo/pull/7"})
        files = subprocess.run(["git", "--git-dir", self.origin, "show", "--name-only", "--format=", "feature/demo"],
                               capture_output=True, text=True, env=self.env).stdout.split()
        self.assertEqual(files, ["src/app.txt"])

    def test_hanging_writer_gate_is_stopped_at_the_configured_timeout(self):
        pidfile = os.path.join(self.sb.root, "gate-child.pid")
        self.register_repo("sleep 120 & echo $! > %s; wait" % pidfile)
        self.sb.set_state("config.json", {"writer_gate_timeout": 2})
        started = time.time()
        r = self.sb.run("factory_publish.py", env={"GIT_CONFIG_NOSYSTEM": "1"}, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.time() - started, 60, "the publisher waited for the hanging gate")
        self.assertIn("PUBLISH FAILED %s" % RID, r.stdout)
        self.assertIn("timed out", self.sb.state("published.json")[RID]["error"])
        self.assertEqual(self.sb.calls("gh", "create"), [], "a PR was opened although the gate never passed")
        with open(pidfile) as f:
            child = int(f.read())
        deadline = time.time() + 5
        while alive(child) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(alive(child), "the gate's child process outlived the timeout")

    GOOD_BODY = ("## Summary\n\n```text\non(start)\n  say hello\n```\n\n## Evidence\n\n- **Before:** no greeting\n"
                 "  **After:** AC1 pass\n\n## Merge Danger\n\n**Door:** two-way\n\n**Blast Radius:** tiny\n\n"
                 "## Factory Retro\n\n<details><summary>retro</summary>\n\nclean run\n\n</details>\n")

    def add_verify_stage(self):
        stage = self.sb.add_task("t_9b1d0002", "VERIFY: say hello", "done", assignee="verifier")
        self.sb.show["t_9b1d0002"]["runs"] = [{"profile": "verifier", "outcome": "completed", "summary": "VERDICT=PASS",
                                               "metadata": {"ac_results": {"AC1": "pass"}}, "error": None}]
        self.sb.show[RID]["parents"] = [stage["id"]]

    def publish_with_writer(self, mode, text=""):
        self.register_repo("true")
        self.add_verify_stage()
        body_copy = os.path.join(self.sb.root, "pr-body.md")
        r = self.sb.run("factory_publish.py", env={"GIT_CONFIG_NOSYSTEM": "1", "FAKE_PR_WRITER": mode,
                                                   "FAKE_PR_TEXT": text, "FAKE_GH_BODY": body_copy})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PR opened (draft)", r.stdout)
        with open(body_copy) as f:
            return r, f.read()

    def test_pr_writer_body_leads_the_pr_and_gets_the_dossier(self):
        r, body = self.publish_with_writer("ok", self.GOOD_BODY)
        self.assertTrue(body.startswith("## Summary\n"), body[:200])
        self.assertIn("## Factory Retro", body)
        self.assertIn("Hermes software factory", body)  # provenance footer is kept
        self.assertIn(RID, body)
        writer = [c for c in self.sb.calls("hermes") if "chat" in c]
        self.assertEqual(len(writer), 1)
        self.assertEqual(writer[0][1:3], ["-p", "pr-writer"])
        self.assertIn("factory-pr", writer[0])
        with open(self.sb.calls_path + ".dossier") as f:
            dossier = json.load(f)
        self.assertIn("+hello", dossier["diff.patch"])
        self.assertIn("src/app.txt", dossier["diffstat.txt"])
        self.assertIn("AC1: the app says hello", dossier["PLAN.md"])
        self.assertIn("say hello", dossier["root.md"])
        stages = json.loads(dossier["stages.json"])
        self.assertEqual(stages[0]["title"], "VERIFY: say hello")
        self.assertEqual(stages[0]["runs"][0]["metadata"], {"ac_results": {"AC1": "pass"}})

    def test_failed_pr_writer_falls_back_to_the_plan_body(self):
        r, body = self.publish_with_writer("fail")
        self.assertIn("## Plan", body)
        self.assertIn("AC1: the app says hello", body)
        self.assertIn("pr-writer", r.stdout)  # the fallback is reported, not silent

    def test_pr_writer_body_without_required_sections_is_rejected(self):
        r, body = self.publish_with_writer("ok", "Looks good to me!\n")
        self.assertNotIn("Looks good to me", body)
        self.assertIn("## Plan", body)
        self.assertIn("pr-writer", r.stdout)


if __name__ == "__main__":
    unittest.main()
