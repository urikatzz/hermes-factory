"""Cron scripts across dedicated run boards: fan-out isolation, registry-only scope, and the intake pump's board lifecycle."""
import json
import os
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sandbox import Sandbox

FAKE_BOARDS_CLI = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(["boards-cli"] + argv) + "\n")
mode = os.environ.get("FAKE_PROVISION", "ok")
if argv[0] == "provision":
    if mode == "ok":
        print(json.dumps({"board": "run-" + argv[1], "status": "active"}))
    else:
        print(json.dumps({"error": "disk is read-only", "status": mode}))
        sys.exit(2)
elif argv[0] == "bind-root":
    print(json.dumps({"board": argv[1], "root": argv[2]}))
'''


def ticket_body(request="Add a login page with a remember-me checkbox and tests for both", project="/nonexistent-new"):
    return "PROJECT: new\nTYPE: feature\nREQUEST:\n" + request + "\n"


class BoardScripts(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.set_state("config.json", {"max_roots": 2, "max_roots_per_repo": 2, "root_assignee": "factory-orchestrator", "ticket_prefix": "TICKET:",
                                          "root_prefix": "FACTORY:", "reviewers": "claude", "dedicated_boards": True})
        cli_dir = os.path.join(self.sb.home, ".hermes", "factory-dashboard", "scripts")
        os.makedirs(cli_dir)
        with open(os.path.join(cli_dir, "factory_boards.py"), "w") as f:
            f.write(FAKE_BOARDS_CLI)
        self.gateway(supports=True)
        python_dir = os.path.join(self.sb.home, ".hermes", "hermes-agent", "venv", "bin")
        os.makedirs(python_dir)
        # A wrapper, not a symlink: a venv interpreter only finds its libraries from its own location.
        wrapper = os.path.join(python_dir, "python")
        with open(wrapper, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
        os.chmod(wrapper, 0o755)

    def gateway(self, supports):
        """A live 'gateway' (this very process) that has, or has not, announced the run-board plugin."""
        pid = os.getpid()
        with open(os.path.join(self.sb.home, ".hermes", "gateway.pid"), "w") as f:
            json.dump({"pid": pid, "kind": "hermes-gateway"}, f)
        marker = os.path.join(self.sb.state_dir, "board-support", str(pid))
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        if supports:
            from factory_lib import process_start
            with open(marker, "w") as f:
                json.dump({"contract": 1, "pid": pid, "started": process_start(pid)}, f)
        elif os.path.exists(marker):
            os.unlink(marker)

    def test_a_stale_or_foreign_marker_does_not_count_as_support(self):
        self.gateway(supports=True)
        marker = os.path.join(self.sb.state_dir, "board-support", str(os.getpid()))
        for bad in ({"contract": 1, "pid": os.getpid(), "started": "Mon Jan  1 00:00:00 2001"},  # same pid, different process (pid reuse)
                    {"contract": 0, "pid": os.getpid(), "started": ""}, "not json", "[1]", "2"):
            with open(marker, "w") as f:
                f.write(bad if isinstance(bad, str) else json.dumps(bad))
            self.sb.add_task("t_aaaa9999", "TICKET: Guarded", "triage", body=ticket_body())
            self.sb.run("factory_intake.py")
            self.assertEqual(self.sb.calls("boards-cli"), [])
        self.assertEqual(self.sb.state("board-activation.json")["state"], "waiting-for-gateway-restart")

    def test_a_first_version_marker_counts_only_if_written_after_the_process_started(self):
        self.gateway(supports=True)
        marker = os.path.join(self.sb.state_dir, "board-support", str(os.getpid()))
        with open(marker, "w") as f:
            f.write("1")
        self.sb.add_task("t_dddd1010", "TICKET: Fresh", "triage", body=ticket_body())
        self.sb.run("factory_intake.py")
        self.assertTrue(self.sb.calls("boards-cli"))  # written just now, after this process started
        os.utime(marker, (1000000000, 1000000000))  # a stale file from before the process existed (pid reuse)
        self.sb.run("factory_intake.py")
        self.assertEqual(self.sb.state("board-activation.json")["state"], "waiting-for-gateway-restart")

    def test_an_unreadable_registry_pauses_admission_instead_of_assuming_no_runs(self):
        with open(os.path.join(self.sb.state_dir, "board-registry.db"), "w") as f:
            f.write("this is not a sqlite database")
        self.sb.add_task("t_bbbb8888", "TICKET: Blind", "triage", body=ticket_body())
        r = self.sb.run("factory_intake.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("intake paused", r.stdout)
        self.assertEqual([c for c in self.sb.calls("hermes") if "create" in c[:6]], [])
        alerts = self.sb.run("factory_alerts.py", "--no-seed")
        self.assertIn("run boards skipped", alerts.stdout)

    def test_a_retry_reuses_the_reserved_branch_and_worktree(self):
        import subprocess
        repo = os.path.join(self.sb.root, "repo")
        os.makedirs(repo)
        for cmd in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", "-C", repo] + cmd, check=True, capture_output=True,
                           env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.c", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.c"))
        repo = os.path.realpath(repo)
        body = "PROJECT: %s\nTYPE: feature\nREQUEST:\nAdd a login page with a remember-me checkbox and tests for both\n" % repo
        self.sb.add_task("t_cccc7777", "TICKET: Login", "triage", body=body)
        self.sb.run("factory_intake.py", env={"FAKE_PROVISION": "provisioning"})  # first attempt: worktree and branch created, board not ready
        worktrees = os.listdir(os.path.join(repo, ".worktrees"))
        self.assertEqual(len(worktrees), 1)
        reserved = os.path.join(repo, ".worktrees", worktrees[0])
        self.sb.add_run_board("run-t_cccc7777", "t_cccc7777", "", status="provisioning")
        import sqlite3
        with sqlite3.connect(os.path.join(self.sb.state_dir, "board-registry.db")) as c:
            c.execute("ALTER TABLE factory_boards ADD COLUMN project_dir TEXT")
            c.execute("ALTER TABLE factory_boards ADD COLUMN branch TEXT")
            c.execute("UPDATE factory_boards SET project_dir=?, branch='feature/login' WHERE ticket_id='t_cccc7777'", (reserved,))
        self.sb.run("factory_intake.py")
        self.assertEqual(os.listdir(os.path.join(repo, ".worktrees")), worktrees)  # no second worktree
        provision = [c for c in self.sb.calls("boards-cli") if c[1] == "provision"][-1]
        self.assertEqual(provision[provision.index("--branch") + 1], "feature/login")
        self.assertEqual(provision[provision.index("--project-dir") + 1], reserved)

    def test_intake_waits_for_the_gateway_before_using_dedicated_boards(self):
        self.gateway(supports=False)
        self.sb.add_task("t_eeee5555", "TICKET: Early", "triage", body=ticket_body())
        r = self.sb.run("factory_intake.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        creates = [c for c in self.sb.calls("hermes") if "create" in c[:6]]
        self.assertEqual(len(creates), 1)
        self.assertNotIn("--board", creates[0])  # legacy root on the default board; no board was provisioned
        self.assertEqual(self.sb.calls("boards-cli"), [])
        self.assertEqual(self.sb.state("board-activation.json")["state"], "waiting-for-gateway-restart")
        self.gateway(supports=True)
        self.sb.add_task("t_ffff6666", "TICKET: Later", "triage", body=ticket_body())
        r = self.sb.run("factory_intake.py")
        self.assertEqual(self.sb.state("board-activation.json")["state"], "active")
        self.assertTrue(self.sb.calls("boards-cli"))

    def test_intake_gives_each_ticket_its_own_board_and_binds_the_root(self):
        self.sb.add_task("t_aaaa1111", "TICKET: Login page", "triage", body=ticket_body())
        r = self.sb.run("factory_intake.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        creates = [c for c in self.sb.calls("hermes") if "create" in c[:6]]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0][1:3], ["kanban", "--board"])
        self.assertEqual(creates[0][3], "run-t_aaaa1111")
        cli = [c[1:] for c in self.sb.calls("boards-cli")]
        self.assertEqual(cli[0][:2], ["provision", "t_aaaa1111"])
        self.assertEqual(cli[1][0], "bind-root")
        # The ticket itself is closed on the intake board (no --board flag).
        done = [c for c in self.sb.calls("hermes") if "complete" in c[:6]]
        self.assertTrue(done and "--board" not in done[0])

    def test_intake_counts_run_board_roots_toward_capacity(self):
        self.sb.set_state("config.json", {"max_roots": 1, "max_roots_per_repo": 2, "root_assignee": "factory-orchestrator", "ticket_prefix": "TICKET:",
                                          "root_prefix": "FACTORY:", "reviewers": "claude", "dedicated_boards": True})
        busy = dict(id="t_root0001", title="FACTORY: busy", status="running", body="", created_at=1)
        self.sb.add_run_board("run-t_old00001", "t_old00001", "t_root0001", tasks=[busy])
        self.sb.add_task("t_bbbb2222", "TICKET: Another", "triage", body=ticket_body())
        r = self.sb.run("factory_intake.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.sb.calls("hermes") if "create" in c[:6]], [])
        self.assertEqual(self.sb.calls("boards-cli"), [])

    def test_a_transient_provisioning_failure_retries_but_an_exhausted_one_blocks_the_ticket(self):
        self.sb.add_task("t_cccc3333", "TICKET: Flaky", "triage", body=ticket_body())
        r = self.sb.run("factory_intake.py", env={"FAKE_PROVISION": "provisioning"})
        self.assertIn("will retry", r.stdout)
        self.assertEqual([c for c in self.sb.calls("hermes") if "block" in c[:6]], [])
        self.assertEqual([c for c in self.sb.calls("hermes") if "create" in c[:6]], [])
        r = self.sb.run("factory_intake.py", env={"FAKE_PROVISION": "failed"})
        self.assertIn("run board could not be created", r.stdout)
        self.assertTrue([c for c in self.sb.calls("hermes") if "block" in c[:6]])
        self.assertEqual([c for c in self.sb.calls("hermes") if "create" in c[:6]], [])

    def test_dedicated_boards_off_keeps_legacy_intake(self):
        self.sb.set_state("config.json", {"max_roots": 2, "max_roots_per_repo": 2, "root_assignee": "factory-orchestrator", "ticket_prefix": "TICKET:",
                                          "root_prefix": "FACTORY:", "reviewers": "claude"})
        self.sb.add_task("t_dddd4444", "TICKET: Legacy", "triage", body=ticket_body())
        r = self.sb.run("factory_intake.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        creates = [c for c in self.sb.calls("hermes") if "create" in c[:6]]
        self.assertEqual(len(creates), 1)
        self.assertNotIn("--board", creates[0])
        self.assertEqual(self.sb.calls("boards-cli"), [])

    def test_alerts_fan_out_isolated_per_registered_board_and_ignore_unregistered_ones(self):
        blocked = dict(id="t_root0002", title="FACTORY: needs you", status="blocked", body="", created_at=self.sb.now - 7200, completed_at=None)
        show = {"t_root0002": {"task": blocked, "events": [dict(created_at=self.sb.now - 60, kind="blocked", payload={"reason": "Pick a database", "kind": "needs_input"}, run_id=None)],
                               "comments": [], "runs": [], "parents": [], "children": [], "latest_summary": ""}}
        self.sb.add_run_board("run-t_new00002", "t_new00002", "t_root0002", tasks=[blocked], show=show)
        self.sb.add_run_board("run-t_gone0003", "t_gone0003", "t_root0003", status="archived")
        r = self.sb.run("factory_alerts.py", "--no-seed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Pick a database", r.stdout)
        boards_seen = {c[c.index("--board") + 1] for c in self.sb.calls("hermes") if "--board" in c}
        self.assertEqual(boards_seen, {"run-t_new00002"})  # the archived board is never queried
        # The run board's first run is not a seeding run: its alert is delivered, not swallowed.
        again = self.sb.run("factory_alerts.py")
        self.assertNotIn("Pick a database", again.stdout)  # already reported once

    def test_one_broken_board_does_not_stop_the_others(self):
        self.sb.add_run_board("run-t_bad00004", "t_bad00004", "t_root0004", tasks=[])  # no show fixture: its scripts fail
        good = dict(id="t_root0005", title="FACTORY: good", status="blocked", body="", created_at=self.sb.now - 7200, completed_at=None)
        show = {"t_root0005": {"task": good, "events": [dict(created_at=self.sb.now - 60, kind="blocked", payload={"reason": "Choose a colour", "kind": "needs_input"}, run_id=None)],
                               "comments": [], "runs": [], "parents": [], "children": [], "latest_summary": ""}}
        self.sb.add_run_board("run-t_good0005", "t_good0005", "t_root0005", tasks=[good], show=show)
        r = self.sb.run("factory_alerts.py", "--no-seed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Choose a colour", r.stdout)


if __name__ == "__main__":
    unittest.main()
