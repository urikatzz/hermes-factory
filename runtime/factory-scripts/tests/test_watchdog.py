import unittest

from sandbox import Sandbox

# Real escalations from the board (Oct 5). Both were blocked with kind=capability only because the orchestrator
# alternates block kinds after a human resume (software-factory SKILL "Outcomes"); both are human decisions.
REAL_T_5AEB01CB = """NEEDS YOUR DECISION: Choose whether to retry the unfinished implementation with an approved route for restricted checks, or stop.
WHAT HAPPENED: The resumed build added server LiveOps progress loading, and the implementer reported passing focused Go tests and structural checks, but reward completion, boot/menu integration, wallet and event displays, Rescue presentation and integration QA remain missing. The overall check stopped on a script permission restriction, and Unity reported compiler errors rather than a busy Editor. The independent checker and Claude reviewer stopped without testing or reviewing because no complete build was available.
WHY IT STOPPED: The implementer again reported incomplete work, required integration checks need restricted Docker access, and the existing allowance for a busy Unity Editor does not cover actual compiler errors or missing features.
OPTIONS:
A) Retry the full implementation, requiring compiler diagnostics and an approved human-run route for checks the workers cannot execute, without bypassing restrictions (recommended).
B) Stop and preserve the partial work in its isolated project folder without marking it delivered.
REPLY WITH:
hermes kanban unblock t_5aeb01cb --reason "retry: finish all missing implementation, diagnose and fix Unity compiler errors, and identify exact checks requiring approved human execution; do not bypass restrictions or waive non-Unity requirements"
hermes kanban unblock t_5aeb01cb --reason "stop\""""

REAL_T_E290E33B = """NEEDS YOUR DECISION: Restore the reviewed starting state and make the design document accessible before retrying, or stop the job.
WHAT HAPPENED: Your retry launched the first fix round, but the developer stopped without changing files because the saved file list differs from the previously reviewed copy and the design document still could not be read. The independent checker confirmed the file-list mismatch, and the Claude reviewer stopped because there was no completed fix to review. The earlier bucket-storage, client and test defects remain unresolved.
WHY IT STOPPED: Continuing would require accepting an unexplained change to the starting files and proceeding without the authoritative design you required.
OPTIONS:
A) Restore the previously reviewed file list and make the authoritative design document readable, then retry (recommended); fixes will resume only after those prerequisites pass.
B) Stop; retain the local work but close the job as unsuccessful.
REPLY WITH:
hermes kanban unblock t_e290e33b --reason "retry: reviewed starting state restored and authoritative design document accessible at the requested path; check both prerequisites, reconcile the design, then fix all reported defects"
hermes kanban unblock t_e290e33b --reason "stop\""""

DOCKER_ONLY = """NEEDS YOUR DECISION: Start Docker so the server tests can run, or stop the job.
WHAT HAPPENED: The first build is complete and the Claude reviewer had no blocking problems. The independent check could not run the server tests because Docker was unavailable.
WHY IT STOPPED: The server tests are required for delivery and cannot run until Docker is available.
OPTIONS:
A) Start Docker and retry the check (recommended).
B) Stop the job.
REPLY WITH:
hermes kanban unblock {tid} --reason "retry: Docker is running again"
hermes kanban unblock {tid} --reason "stop\""""

DOCKER_AND_DEFECT = """NEEDS YOUR DECISION: Start Docker and approve another fix round, or stop.
WHAT HAPPENED: The first build compiles, but the security reviewer found a regression in the session token check. The independent check could not run the server tests because Docker was unavailable.
WHY IT STOPPED: Delivery needs the regression fixed and the server tests run.
OPTIONS:
A) Start Docker and run another fix round (recommended).
B) Stop the job.
REPLY WITH:
hermes kanban unblock {tid} --reason "retry: Docker is running; fix the token check regression"
hermes kanban unblock {tid} --reason "stop\""""

UNITY_BUSY = """NEEDS YOUR DECISION: Close the Unity Editor so the EditMode tests can run, or stop.
WHAT HAPPENED: The first build is complete and the Claude reviewer had no blocking problems. The Unity tests could not start because the Unity Editor already has the project open (PID 4242).
WHY IT STOPPED: The EditMode tests are required for delivery.
OPTIONS:
A) Close the Unity Editor and retry (recommended).
B) Stop the job.
REPLY WITH:
hermes kanban unblock {tid} --reason "retry: the Unity Editor is closed"
hermes kanban unblock {tid} --reason "stop\""""


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def blocked_root(self, tid, kind, reason):
        self.sb.add_task(tid, "FACTORY: some job", "blocked",
                         events=[(self.sb.now - 60, "blocked", {"kind": kind, "reason": reason})])

    def run_watchdog(self):
        r = self.sb.run("factory_watchdog.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_capability_decision_escalation_is_left_for_the_human(self):
        self.blocked_root("t_5aeb01cb", "capability", REAL_T_5AEB01CB)
        r = self.run_watchdog()
        self.assertIn("NEEDS YOU (t_5aeb01cb)", r.stdout)
        self.assertEqual(self.sb.calls("hermes", "unblock"), [])

    def test_capability_escalation_asking_human_to_restore_files_is_not_answered(self):
        self.blocked_root("t_e290e33b", "capability", REAL_T_E290E33B)
        r = self.run_watchdog()
        self.assertIn("NEEDS YOU (t_e290e33b)", r.stdout)
        self.assertEqual(self.sb.calls("hermes", "unblock"), [])

    def test_docker_only_block_is_retried_with_the_orchestrators_reply(self):
        self.blocked_root("t_d0c0e001", "needs_input", DOCKER_ONLY.format(tid="t_d0c0e001"))
        r = self.run_watchdog()
        self.assertIn("AUTO-RETRY 1/2 (t_d0c0e001)", r.stdout)
        self.assertEqual(self.sb.calls("hermes", "unblock"),
                         [["hermes", "kanban", "unblock", "t_d0c0e001", "--reason", "retry: Docker is running again"]])

    def test_docker_block_that_also_reports_a_defect_is_left_for_the_human(self):
        self.blocked_root("t_d0c0e002", "needs_input", DOCKER_AND_DEFECT.format(tid="t_d0c0e002"))
        r = self.run_watchdog()
        self.assertIn("NEEDS YOU (t_d0c0e002)", r.stdout)
        self.assertEqual(self.sb.calls("hermes", "unblock"), [])

    def test_unity_busy_block_is_retried_once_unity_is_closed(self):
        self.blocked_root("t_0b1e0001", "needs_input", UNITY_BUSY.format(tid="t_0b1e0001"))
        r = self.run_watchdog()
        self.assertIn("AUTO-RETRY 1/2 (t_0b1e0001)", r.stdout)
        self.assertEqual(len(self.sb.calls("hermes", "unblock")), 1)

    def test_same_block_is_reported_only_once(self):
        self.blocked_root("t_5aeb01cb", "capability", REAL_T_5AEB01CB)
        self.run_watchdog()
        second = self.run_watchdog()
        self.assertEqual(second.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
