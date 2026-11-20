"""Test sandbox for the factory cron scripts: runs a real script the way cron does, but with a temporary HOME
and fake `hermes`, `docker`, `gh`, `pgrep`, `ps`, `osascript`, `open` and `pkill` first on PATH, so nothing on
the real board, Docker, Unity or GitHub is touched. Every fake logs its argv to calls.jsonl."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(os.path.dirname(SCRIPTS), "factory-skills", "worker", "factory-worker", "scripts", "fw.py")
if not os.path.exists(FW):  # tracked copy: the worker skill's scripts live only in the Hermes home
    FW = os.path.expanduser("~/.hermes/factory-skills/worker/factory-worker/scripts/fw.py")

FAKE_HERMES = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(["hermes"] + argv) + "\n")
with open(os.environ["FAKE_FIXTURE"]) as f:
    fx = json.load(f)
if argv[:1] == ["-p"] and "chat" in argv:
    # pr-writer: FAKE_PR_WRITER=ok writes FAKE_PR_TEXT to OUT/PR.md, fail exits 1, unset = not installed
    mode = os.environ.get("FAKE_PR_WRITER", "")
    if not mode:
        sys.exit("fake hermes: profile not found")
    query = dict(l.split("=", 1) for l in open(argv[argv.index("--query-file") + 1]).read().splitlines() if "=" in l)
    with open(os.environ["FAKE_CALLS"] + ".dossier", "w") as f:
        json.dump({n: open(os.path.join(query["DOSSIER"], n)).read() for n in os.listdir(query["DOSSIER"])}, f)
    assert os.environ["HERMES_KANBAN_WORKSPACE"] == query["OUT"], "writer folder is not its kanban workspace"
    if mode == "fail":
        sys.exit(1)
    with open(os.path.join(query["OUT"], "PR.md"), "w") as f:
        f.write(os.environ["FAKE_PR_TEXT"])
    print("PR_BODY_WRITTEN")
    sys.exit(0)
if argv[:1] == ["kanban"]:
    argv = argv[1:]
board = None
if argv[:1] == ["--board"]:
    board = argv[1]
    argv = argv[2:]
if board and board in fx.get("boards", {}):  # run boards carry their own cards
    fx = fx["boards"][board]
cmd = argv[0] if argv else ""
if cmd == "list":
    status = argv[argv.index("--status") + 1] if "--status" in argv else None
    print(json.dumps([t for t in fx["tasks"] if status is None or t["status"] == status]))
elif cmd == "show":
    print(json.dumps(fx["show"][argv[1]]))
elif cmd == "create":
    key = argv[argv.index("--idempotency-key") + 1] if "--idempotency-key" in argv else "x"
    print(json.dumps({"id": "t_root_" + key.replace("intake-", "")}))
elif cmd in ("unblock", "block", "comment", "complete", "archive", "specify", "decompose", "promote"):
    print(json.dumps({"ok": True}))
else:
    sys.exit("fake hermes: unsupported " + " ".join(argv))
'''

FAKE_LOGGER = r'''#!/bin/sh
python3 -c 'import json, os, sys; open(os.environ["FAKE_CALLS"], "a").write(json.dumps(sys.argv[1:]) + "\n")' "$(basename "$0")" "$@"
'''

FAKE_EXIT = {"docker": "exit ${FAKE_DOCKER_RC:-0}", "pgrep": "exit 1", "ps": "exit 0", "osascript": "exit 0",
             "open": "exit 0", "pkill": "exit 0"}

FAKE_GH = r'''
case "$1 $2" in
  "api user") echo "${FAKE_GH_USER:-tester}" ;;
  "pr create") prev=; for a in "$@"; do [ "$prev" = --body-file ] && [ -n "$FAKE_GH_BODY" ] && cp "$a" "$FAKE_GH_BODY"; prev=$a; done
               echo "https://github.com/example/demo/pull/7" ;;
  *) exit 1 ;;
esac
'''


class Sandbox:
    def __init__(self, now=None):
        self.root = tempfile.mkdtemp(prefix="factory-test-")
        self.home = os.path.join(self.root, "home")
        self.state_dir = os.path.join(self.home, ".hermes", "state", "factory")
        self.bin = os.path.join(self.root, "bin")
        self.calls_path = os.path.join(self.root, "calls.jsonl")
        self.fixture_path = os.path.join(self.root, "fixture.json")
        self.repos_path = os.path.join(self.root, "repos.json")
        self.now = int(now or time.time())
        self.tasks, self.show = [], {}
        self.boards = {}
        os.makedirs(self.state_dir)
        os.makedirs(self.bin)
        self._write_exe("hermes", FAKE_HERMES)
        for name, body in FAKE_EXIT.items():
            self._write_exe(name, FAKE_LOGGER + body + "\n")
        self._write_exe("gh", FAKE_LOGGER + FAKE_GH)
        fw_dst = os.path.join(self.home, ".hermes", "factory-skills", "worker", "factory-worker", "scripts")
        os.makedirs(fw_dst)
        shutil.copy(FW, fw_dst)
        self.write_json(self.repos_path, {"default": None, "repos": {}})

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_exe(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(body if body.startswith("#!") else "#!/bin/sh\n" + body)
        os.chmod(path, 0o755)

    @staticmethod
    def write_json(path, obj):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(obj, f)

    def state(self, name):
        with open(os.path.join(self.state_dir, name)) as f:
            return json.load(f)

    def set_state(self, name, obj):
        self.write_json(os.path.join(self.state_dir, name), obj)

    def add_task(self, tid, title, status, body="", events=(), comments=(), summary="", result=None, **extra):
        task = dict(id=tid, title=title, status=status, body=body, assignee=extra.pop("assignee", "factory-orchestrator"),
                    created_at=extra.pop("created_at", self.now - 7200), started_at=extra.pop("started_at", None),
                    completed_at=extra.pop("completed_at", None), result=result, last_failure_error=None, priority=0, **extra)
        self.tasks.append(task)
        self.show[tid] = {"task": task, "events": [dict(created_at=ts, kind=kind, payload=payload, run_id=None)
                                                   for ts, kind, payload in events],
                          "comments": [dict(body=b, author="default", created_at=ts) for ts, b in comments],
                          "runs": [], "parents": [], "children": [], "latest_summary": summary}
        return task

    def add_run_board(self, slug, ticket, root, status="active", tasks=(), show=None):
        """Register a run board (the real registry schema, read-only for the scripts) and give the fake hermes its cards."""
        import sqlite3
        from contextlib import closing
        path = os.path.join(self.state_dir, "board-registry.db")
        with closing(sqlite3.connect(path)) as c, c:
            c.execute("CREATE TABLE IF NOT EXISTS factory_boards(board_id TEXT PRIMARY KEY, db_path TEXT NOT NULL, source_board_id TEXT NOT NULL DEFAULT 'default', "
                      "ticket_id TEXT NOT NULL, root_id TEXT, status TEXT NOT NULL, created_at REAL NOT NULL DEFAULT 0)")
            c.execute("INSERT INTO factory_boards(board_id,db_path,ticket_id,root_id,status) VALUES(?,?,?,?,?)",
                      (slug, os.path.join(self.root, "boards", slug, "kanban.db"), ticket, root, status))
        self.boards[slug] = {"tasks": list(tasks), "show": show or {}}

    def run(self, script, *args, timeout=60, env=None):
        self.write_json(self.fixture_path, {"tasks": self.tasks, "show": self.show, "boards": self.boards})
        full_env = dict(os.environ, HOME=self.home, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""),
                        FAKE_CALLS=self.calls_path, FAKE_FIXTURE=self.fixture_path, FACTORY_REPOS=self.repos_path,
                        GIT_AUTHOR_NAME="Factory Test", GIT_AUTHOR_EMAIL="test@example.com",
                        GIT_COMMITTER_NAME="Factory Test", GIT_COMMITTER_EMAIL="test@example.com")
        full_env.update(env or {})
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args), env=full_env,
                              capture_output=True, text=True, timeout=timeout)

    def calls(self, prog=None, verb=None):
        """Logged argv lists, optionally only one program and (for hermes) one kanban verb."""
        try:
            with open(self.calls_path) as f:
                rows = [json.loads(l) for l in f if l.strip()]
        except OSError:
            return []
        if prog:
            rows = [r for r in rows if r[0] == prog]
        if verb:
            rows = [r for r in rows if verb in r[1:4]]
        return rows
