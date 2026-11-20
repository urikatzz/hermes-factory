import unittest

from sandbox import Sandbox

ESCALATION = "NEEDS YOUR DECISION: Restore access to the job history so I can safely continue, or stop this job."
DELIVERED = "OUTCOME=LOCAL_DELIVERED MANIFEST=66c963d521f0 PROJECT_DIR=/tmp/demo\nAll checks passed."


class AlertsTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.sb.set_state("alerts_seen.json", {})  # not the very first run (that one only seeds)

    def tearDown(self):
        self.sb.cleanup()

    def run_alerts(self):
        r = self.sb.run("factory_alerts.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def finished_root(self, tid, minutes_ago, auto_pr="no", summary=DELIVERED):
        body = "FACTORY_ROOT v2\nDELIVERY: local\nAUTO_PR: %s\nREQUEST:\nx\n" % auto_pr
        return self.sb.add_task(tid, "FACTORY: Add daily reward popup", "done", body=body, summary=summary,
                                result=summary, completed_at=self.sb.now - minutes_ago * 60)

    # --- existing behaviour that must keep working
    def test_very_first_run_only_records_state(self):
        self.sb.cleanup()
        self.sb = Sandbox()
        self.sb.add_task("t_00000001", "FACTORY: x", "blocked",
                         events=[(self.sb.now - 60, "blocked", {"kind": "needs_input", "reason": ESCALATION})])
        self.assertEqual(self.run_alerts(), "")

    def test_blocked_card_alerts_once(self):
        self.sb.add_task("t_00000002", "FACTORY: Fix score overflow", "blocked",
                         events=[(self.sb.now - 60, "blocked", {"kind": "needs_input", "reason": ESCALATION})])
        first = self.run_alerts()
        self.assertIn("NEEDS YOUR DECISION t_00000002 | Fix score overflow", first)
        self.assertEqual(self.run_alerts(), "")

    # --- a root the loop breaker moved to Triage is stuck and silent today
    def test_root_moved_to_triage_by_the_loop_breaker_alerts_once(self):
        self.sb.add_task("t_a91f2418", "FACTORY: Menu economy phase 0", "triage", events=[
            (self.sb.now - 900, "blocked", {"kind": "needs_input", "reason": ESCALATION}),
            (self.sb.now - 300, "block_loop_detected", {"reason": ESCALATION})])
        first = self.run_alerts()
        self.assertIn("STUCK t_a91f2418 | Menu economy phase 0", first)
        self.assertIn(ESCALATION, first)
        self.assertIn("hermes kanban archive t_a91f2418", first)
        self.assertEqual(self.run_alerts(), "")

    def test_ticket_waiting_in_triage_is_not_an_alert(self):
        self.sb.add_task("t_00000003", "TICKET: Add daily reward popup", "triage")
        self.assertEqual(self.run_alerts(), "")

    # --- finished jobs
    def test_finished_job_is_announced_once_with_its_outcome(self):
        self.finished_root("t_00000004", minutes_ago=2)
        first = self.run_alerts()
        self.assertIn("FINISHED t_00000004 | Add daily reward popup", first)
        self.assertIn("OUTCOME=LOCAL_DELIVERED", first)
        self.assertEqual(self.run_alerts(), "")

    def test_jobs_finished_before_today_are_not_announced(self):
        self.finished_root("t_00000005", minutes_ago=3 * 24 * 60)
        self.assertEqual(self.run_alerts(), "")

    def test_auto_pr_job_is_announced_with_its_pr_link(self):
        self.finished_root("t_00000006", minutes_ago=2, auto_pr="yes")
        self.assertEqual(self.run_alerts(), "", "announced before the publisher had a chance to open the PR")
        self.sb.set_state("published.json", {"t_00000006": {"url": "https://github.com/example/demo/pull/7"}})
        msg = self.run_alerts()
        self.assertIn("FINISHED t_00000006", msg)
        self.assertIn("PR (draft): https://github.com/example/demo/pull/7", msg)

    def test_auto_pr_job_that_could_not_be_published_says_why(self):
        self.finished_root("t_00000007", minutes_ago=4, auto_pr="yes")
        self.sb.set_state("published.json", {"t_00000007": {"error": "writer gate failed (sh unity_gate.sh): CS0246", "n": 3}})
        msg = self.run_alerts()
        self.assertIn("FINISHED t_00000007", msg)
        self.assertIn("PR NOT OPENED", msg)
        self.assertIn("CS0246", msg)

    def test_slow_publish_is_announced_after_fifteen_minutes_then_updated(self):
        self.finished_root("t_00000008", minutes_ago=16, auto_pr="yes")
        self.assertIn("PR not opened yet", self.run_alerts())
        self.sb.set_state("published.json", {"t_00000008": {"url": "https://github.com/example/demo/pull/8"}})
        update = self.run_alerts()
        self.assertIn("PR UPDATE t_00000008", update)
        self.assertIn("https://github.com/example/demo/pull/8", update)
        self.assertEqual(self.run_alerts(), "")

    # --- a card held by the dispatcher's quota guard never runs and nobody is told
    def guarded_card(self, tid, minutes):
        events = [(self.sb.now - 7200, "promoted", {})]
        events += [(self.sb.now - minutes * 60 + i * 10, "respawn_guarded", {"reason": "blocker_auth"})
                   for i in range(minutes * 6)]
        self.sb.add_task(tid, "FACTORY: Menu button opens google.com", "ready", events=events)

    def test_card_held_by_the_quota_guard_for_long_alerts_once_with_the_fix(self):
        self.guarded_card("t_36ab9253", minutes=40)
        self.sb.tasks[-1]["last_failure_error"] = "HTTP 429: usage limit has been reached"
        first = self.run_alerts()
        self.assertIn("STALLED t_36ab9253", first)
        self.assertIn("hermes kanban block --kind transient t_36ab9253", first)
        self.assertIn("hermes kanban unblock t_36ab9253", first)
        self.assertEqual(self.run_alerts(), "")

    def test_short_quota_hold_is_not_an_alert(self):
        self.guarded_card("t_36ab9254", minutes=5)
        self.sb.tasks[-1]["last_failure_error"] = "HTTP 429: usage limit has been reached"
        self.assertEqual(self.run_alerts(), "")


if __name__ == "__main__":
    unittest.main()
