import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import factory_lib  # noqa: E402


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class AtomicWriteJsonTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="factory-lib-test-")
        self.path = os.path.join(self.dir, "state.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_replaces_the_file_contents(self):
        factory_lib.atomic_write_json(self.path, {"a": 1})
        factory_lib.atomic_write_json(self.path, {"b": 2})
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"b": 2})

    def test_keeps_the_existing_file_permissions(self):
        with open(self.path, "w") as f:
            f.write("{}")
        os.chmod(self.path, 0o644)
        factory_lib.atomic_write_json(self.path, {"a": 1})
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_failed_write_keeps_the_previous_state_and_leaves_no_temp_file(self):
        factory_lib.atomic_write_json(self.path, {"a": 1})
        with self.assertRaises(TypeError):
            factory_lib.atomic_write_json(self.path, {"a": 1, "bad": object()})
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"a": 1})
        self.assertEqual(os.listdir(self.dir), ["state.json"])


class RunGateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="factory-gate-test-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_returns_exit_code_and_output(self):
        rc, out, err, timed_out = factory_lib.run_gate("echo hello; echo oops >&2; exit 3", self.dir, timeout=30)
        self.assertEqual((rc, out, err, timed_out), (3, "hello", "oops", False))

    def test_timeout_kills_the_whole_process_group(self):
        pidfile = os.path.join(self.dir, "child.pid")
        started = time.time()
        rc, out, err, timed_out = factory_lib.run_gate("sleep 60 & echo $! > %s; wait" % pidfile, self.dir, timeout=1)
        self.assertTrue(timed_out)
        self.assertLess(time.time() - started, 20)
        with open(pidfile) as f:
            child = int(f.read())
        deadline = time.time() + 5
        while alive(child) and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(alive(child), "the gate's background child survived the timeout")


if __name__ == "__main__":
    unittest.main()
