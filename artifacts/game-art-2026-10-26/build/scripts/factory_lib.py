"""Shared helpers for the factory intake / alert scripts (stdlib only, no LLM)."""
import json, os, re, signal, subprocess, sys, tempfile

HOME = os.path.expanduser("~/.hermes")
STATE_DIR = os.path.join(HOME, "state", "factory")
CONFIG = os.path.join(STATE_DIR, "config.json")
# writer_gate_timeout: seconds the publisher gives one host-side writer gate (Unity compile + tests). Cron kills a
# script job after 3600 s, so this stays below that. pr_writer_profile: Hermes profile that writes the draft PR body
# (factory-pr skill); empty = always the plain plan body. pr_writer_timeout: seconds for its one oneshot run (the
# gate and the writer together stay below the cron limit).
DEFAULTS = {"max_roots": 2, "max_roots_per_repo": 2, "root_assignee": "factory-orchestrator",
            "ticket_prefix": "TICKET:", "root_prefix": "FACTORY:", "reviewers": "claude", "writer_gate_timeout": 3000,
            "pr_writer_profile": "pr-writer", "pr_writer_timeout": 420}
OPEN_FOR_CAP = {"triage", "todo", "scheduled", "ready", "running", "review"}  # blocked roots wait for a human, not compute


def atomic_write_json(path, obj, **dump_kw):
    """Write JSON via a temp file in the same folder and os.replace, so a crash or error mid-write never leaves a
    truncated state file behind (a corrupt alerts/published state re-sends old alerts or re-runs old work)."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        os.fchmod(fd, mode)  # mkstemp creates 0600; keep the file's usual permissions
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, **dump_kw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_gate(cmd, cwd, timeout):
    """Run a shell gate command in its own process group. On timeout stop the WHOLE group (TERM, then KILL), so
    nothing it started (a Unity editor, a test server) outlives it holding locks. -> (rc, stdout, stderr, timed_out)"""
    proc = subprocess.Popen(["sh", "-c", cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out.strip(), err.strip(), False
    except subprocess.TimeoutExpired:
        pass
    out = err = ""
    for sig, grace in ((signal.SIGTERM, 15), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            out, err = proc.communicate(timeout=grace)
            break
        except subprocess.TimeoutExpired:
            continue
    else:  # a process that left the group still holds our pipes: drop its output rather than hang
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass
        proc.wait(timeout=5)
    return proc.returncode, (out or "").strip(), (err or "").strip(), True


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        atomic_write_json(CONFIG, DEFAULTS, indent=2)
    return cfg


def hermes(args, board=None, stdin=None, check=True):
    cmd = ["hermes", "kanban"] + (["--board", board] if board else []) + list(args)
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError("%s -> exit %d: %s" % (" ".join(cmd), r.returncode, (r.stderr or r.stdout).strip()[:400]))
    return r


def kanban_list(board=None, status=None):
    args = ["list", "--json"] + (["--status", status] if status else [])
    out = hermes(args, board).stdout
    return json.loads(out[out.index("["):]) if "[" in out else []


def kanban_show(task_id, board=None):
    out = hermes(["show", task_id, "--json"], board).stdout
    return json.loads(out[out.index("{"):])


def git(path, *args):
    r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


REPOS = os.environ.get("FACTORY_REPOS") or os.path.join(STATE_DIR, "repos.json")


def load_repos():
    try:
        with open(REPOS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"default": None, "repos": {}}


def resolve_project(value):
    """'new' | alias | '' (default alias) | absolute path -> (kind, path_or_None, alias_or_None, repo_cfg)."""
    reg = load_repos()
    v = (value or "").strip()
    if v.lower() == "new":
        return "new", None, None, {}
    if not v:
        v = reg.get("default") or ""
    cfg = reg.get("repos", {}).get(v.lower())
    if cfg:
        return "existing", os.path.realpath(os.path.expanduser(cfg["path"])), v.lower(), cfg
    path = os.path.realpath(os.path.expanduser(v))
    for alias, c in reg.get("repos", {}).items():
        if os.path.realpath(os.path.expanduser(c["path"])) == path:
            return "existing", path, alias, c
    return "existing", path, None, {}


FIELD = re.compile(r"^([A-Z_]+):[ \t]*(.*)$")


def parse_ticket(body):
    """FACTORY_TICKET v1 header: single-line fields, then ACCEPTANCE:/REQUEST: blocks run to the next field."""
    if (body or "").startswith(("FACTORY_TICKET v2\n", "FACTORY_TICKET v3\n")):
        fields = json.loads(body.split("\n", 1)[1])
        allowed = {"PROJECT", "TYPE", "ACCEPTANCE", "REQUEST"}
        if (body or "").startswith("FACTORY_TICKET v3\n"):
            allowed.add("WORKFLOW")
        if not isinstance(fields, dict) or set(fields) != allowed:
            raise ValueError("Invalid structured Factory ticket fields")
        if "WORKFLOW" in fields:
            selection = fields["WORKFLOW"]
            if not isinstance(selection, dict) or set(selection) != {"id", "revision"} or not isinstance(selection["id"], str) or type(selection["revision"]) is not int:
                raise ValueError("Invalid Factory workflow selection")
        if any(not isinstance(value, str) for key, value in fields.items() if key != "WORKFLOW"):
            raise ValueError("Factory ticket values must be text")
        if not fields["PROJECT"].strip() or not fields["REQUEST"].strip():
            raise ValueError("Factory ticket requires project and request")
        if fields["TYPE"] not in {"feature", "bug", "chore", "art"}:
            raise ValueError("Invalid Factory ticket type")
        return fields
    fields, cur = {}, None
    for line in (body or "").splitlines():
        m = FIELD.match(line)
        if m and m.group(1) in {"PROJECT", "SLUG", "NEW_DIR", "ACCEPTANCE", "REQUEST", "DECOMPOSE", "ISOLATION", "TYPE"}:
            cur = m.group(1)
            fields[cur] = m.group(2)
        elif cur:
            fields[cur] += "\n" + line
    return {k: v.strip() for k, v in fields.items()}


def slugify(s):
    return "-".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split()[:5]) or "factory-job"


def capacity_roots(tasks, prefix, board_path):
    """Controller-held active roots consume slots; human-blocked/legacy semantics stay intact."""
    import sqlite3
    from pathlib import Path
    from contextlib import closing
    from urllib.parse import quote
    managed=set()
    if board_path and Path(board_path).is_file():
        with closing(sqlite3.connect('file:'+quote(str(Path(board_path).resolve()))+'?mode=ro',uri=True)) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='factory_workflow_roots'").fetchone():
                managed={row[0] for row in conn.execute("SELECT root_id FROM factory_workflow_roots WHERE phase IN ('preparing','implementing','reviewing','repairing')")}
    return [task for task in tasks if task['id'] in managed or (task['title'].startswith(prefix) and task['status'] in OPEN_FOR_CAP)]
