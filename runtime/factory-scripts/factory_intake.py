#!/usr/bin/env python3
"""Factory intake pump (cron --no-agent; deterministic, zero tokens).

Triage lane tickets ("TICKET: ...", created by factory_ticket.py or `hermes kanban create --triage`) become
FACTORY roots for the factory-orchestrator, up to `max_roots` open roots at once (state/factory/config.json).
Existing git projects get their own linked worktree (<repo>/.worktrees/<ticket id>, branch factory/<ticket id>)
created HERE, before the root exists, so parallel jobs on one repo never share a folder. Workers still never run git;
the root just gets an ordinary PROJECT_DIR. Prints a line per action; empty output = nothing happened (silent).
Usage: factory_intake.py [--board SLUG] [--dry-run] [--assignee PROFILE]"""
import argparse, json, os, re, subprocess, sys
from factory_lib import (HOME, STATE_DIR, capacity_roots, gateway_supports_boards, git, hermes, hermes_patches_ok, kanban_list, kanban_show, load_config,
                         parse_ticket, record_activation, reserved_run, resolve_project, run_boards, RegistryUnreadable, slugify)

BOARDS_CLI = os.path.join(HOME, "factory-dashboard", "scripts", "factory_boards.py")
HERMES_PYTHON = os.path.join(HOME, "hermes-agent", "venv", "bin", "python")


def boards_cli(*argv):
    """Run the run-board CLI; -> (ok, parsed JSON or text). Provisioning and root binding live there so this script stays stdlib-only."""
    r = subprocess.run([HERMES_PYTHON, BOARDS_CLI, *argv], capture_output=True, text=True, timeout=300)
    text = (r.stdout or "").strip()
    try:
        return r.returncode == 0, json.loads(text)
    except ValueError:
        return r.returncode == 0, (text or (r.stderr or "").strip()[-400:])

ap = argparse.ArgumentParser()
ap.add_argument("--board", default=None)
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--assignee", default=None, help="override root assignee (tests only)")
args = ap.parse_args()
if not hermes_patches_ok():
    sys.exit(0)  # the patch guard job reports it; new roots on an unpatched Hermes would fail at their first stage
cfg = load_config()
assignee = args.assignee or cfg["root_assignee"]
out = []


def say(msg):
    out.append(msg)


def block_ticket(t, why):
    say("ticket %s blocked: %s" % (t["id"], why))
    if not args.dry_run:
        hermes(["block", "--kind", "needs_input", t["id"], "intake: " + why], args.board, check=False)


def header_val(body, key):
    for line in (body or "").splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""


tasks = kanban_list(args.board)
# Managed workflow execution is registered only on the configured default Factory board.
# Compare durable IDs with this board's task list; ordinary named-board roots retain legacy behavior.
workflow_board=os.path.join(HOME,'kanban.db')
roots = capacity_roots(tasks,cfg['root_prefix'],workflow_board) if args.board in (None,'default') else capacity_roots(tasks,cfg['root_prefix'],'')
# Dedicated run boards: every new root gets its own board (config `dedicated_boards`). Their roots count toward the same
# capacity and per-repo limits as the default board's, so concurrency stays bounded across all boards.
dedicated = bool(cfg.get("dedicated_boards")) and args.board in (None, "default")
if dedicated and not args.dry_run:
    if gateway_supports_boards():
        record_activation("active")
    else:  # fall back to the legacy default-board root until the gateway has loaded the new plugin
        dedicated = False
        record_activation("waiting-for-gateway-restart", "dedicated_boards is on, but the running gateway has not loaded the run-board plugin yet")
if args.board in (None, "default"):
    try:
        for rb in run_boards():
            roots += capacity_roots(kanban_list(rb["board"]), cfg["root_prefix"], rb["db_path"])
    except (RegistryUnreadable, RuntimeError) as exc:
        # Admission needs the full picture of running work; without it nothing new may start.
        print("intake paused: %s" % exc)
        sys.exit(0)
tickets = [t for t in tasks if t["title"].startswith(cfg["ticket_prefix"]) and t["status"] == "triage"]
tickets.sort(key=lambda t: (-(t.get("priority") or 0), t.get("created_at") or 0))
repo_load, dirs_busy = {}, set()
for r in roots:
    repo = header_val(r.get("body"), "REPO_DIR")
    if repo:
        repo_load[repo] = repo_load.get(repo, 0) + 1
    elif header_val(r.get("body"), "PROJECT_MODE") == "existing":
        dirs_busy.add(header_val(r.get("body"), "PROJECT_DIR"))
slots = cfg["max_roots"] - len(roots)

for t in tickets:
    f = parse_ticket(t.get("body"))
    if re.search(r"<[a-z][a-z ]*>", (f.get("REQUEST", "") + t["title"]).lower()) and not f.get("REQUEST", "").strip().count(" ") > 12:
        block_ticket(t, "ticket still contains placeholder text like <task> or <details>; re-file it with real content")
        continue
    if not f.get("REQUEST"):
        # Under-specified idea: let Hermes's specifier flesh it out (it promotes the card to todo), then a human re-files it.
        say("ticket %s under-specified -> kanban specify" % t["id"])
        if not args.dry_run:
            hermes(["specify", t["id"]], args.board, check=False)
        continue
    if f.get("DECOMPOSE", "").lower().startswith("y"):
        say("ticket %s decompose -> children land in triage as separate tickets" % t["id"])
        if not args.dry_run:
            hermes(["decompose", t["id"]], args.board, check=False)
        continue
    if slots <= 0:
        break
    kind, path, alias, rcfg = resolve_project(f.get("PROJECT"))
    title = t["title"][len(cfg["ticket_prefix"]):].strip() or "untitled"
    slug = f.get("SLUG") or slugify(title)
    hdr = ["FACTORY_ROOT v2", "DELIVERY: local", "TYPE: " + (f.get("TYPE") or "feature"), "REVIEWERS: " + cfg.get("reviewers", "claude")]
    if kind == "new":
        hdr += ["PROJECT_MODE: new", "PROJECT_DIR: " + (f.get("NEW_DIR") or "auto"), "ISOLATION: dir"]
    else:
        if not path or not os.path.isdir(path):
            block_ticket(t, "PROJECT folder does not exist: %s" % path)
            continue
        rc, top, _ = git(path, "rev-parse", "--show-toplevel")
        if rc == 0 and os.path.realpath(top) == path and git(path, "rev-parse", "--verify", "HEAD")[0] == 0:
            if repo_load.get(path, 0) >= cfg["max_roots_per_repo"]:
                continue
            # Readable names: branch = <type>/<slug> (feature/, fix/, chore/, art/), folder = <slug>-<id suffix>; the branch gets the
            # id suffix only if that name is already taken.
            prefix = {"bug": "fix", "chore": "chore", "art": "art", "audio": "audio"}.get((f.get("TYPE") or "feature").lower(), "feature")
            branch = "%s/%s" % (prefix, slug[len(prefix) + 1:] if slug.startswith(prefix + "-") and len(slug) > len(prefix) + 1 else slug)
            wt = os.path.join(path, ".worktrees", "%s-%s" % (slug, t["id"][-4:]))
            reserved = reserved_run(t["id"])
            if reserved and reserved["branch"]:
                # A retry after a partial failure reuses exactly the branch and worktree it reserved, never a second name.
                branch, wt = reserved["branch"], reserved["project_dir"] or wt
            elif git(path, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0 or \
                    git(path, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/" + branch)[0] == 0:
                branch += "-" + t["id"][-4:]
            start = "HEAD"
            if rcfg.get("base") and not args.dry_run:
                git(path, "fetch", "origin", rcfg["base"])  # best effort: start from the latest remote base
                if git(path, "rev-parse", "--verify", "origin/" + rcfg["base"])[0] == 0:
                    start = "origin/" + rcfg["base"]
            base = git(path, "rev-parse", "--short=12", start)[1]
            dirty = "yes" if git(path, "status", "--porcelain")[1] else "no"
            if not args.dry_run:
                if not os.path.isdir(wt):
                    rc, _, err = git(path, "worktree", "add", "-b", branch, wt, start)
                    if rc != 0:
                        block_ticket(t, "git worktree add failed: " + err[:200])
                        continue
                excl = os.path.join(path, ".git", "info", "exclude")
                if os.path.isfile(excl) and ".worktrees/" not in open(excl).read():
                    with open(excl, "a") as fh:
                        fh.write("\n.worktrees/\n")
            hdr += ["PROJECT_MODE: existing", "PROJECT_DIR: " + wt, "ISOLATION: worktree", "REPO_DIR: " + path,
                    "BRANCH: " + branch, "BASE_COMMIT: " + base, "MAIN_TREE_DIRTY: " + dirty]
            if alias:
                hdr += ["REPO: " + alias, "BASE_BRANCH: " + rcfg.get("base", "main"),
                        "AUTO_PR: " + ("yes" if rcfg.get("auto_pr") else "no"),
                        "UNITY_CI: " + ("yes" if rcfg.get("unity_ci") else "no")]
                if rcfg.get("read_first"):
                    hdr.append("READ_FIRST: " + ", ".join(rcfg["read_first"]))
                for g in rcfg.get("gates", []):
                    hdr.append("GATE: %s => %s" % (g["when"], g["cmd"]))
                for g in rcfg.get("writer_gates", []):
                    hdr.append("WRITER_GATE: %s => %s" % (g["when"], g["cmd"]))
            repo_load[path] = repo_load.get(path, 0) + 1
        else:
            if path in dirs_busy:
                continue  # plain folder (no git root with a commit): one root at a time
            hdr += ["PROJECT_MODE: existing", "PROJECT_DIR: " + path, "ISOLATION: dir"]
            dirs_busy.add(path)
    body = "\n".join(hdr + ["SLUG: " + slug, "USER_ACCEPTANCE: " + (f.get("ACCEPTANCE") or "none"),
                            "REQUEST:", f["REQUEST"], ""])
    say("ticket %s -> root (%s%s)" % (t["id"], next(h for h in hdr if h.startswith("ISOLATION")), " " + alias if kind != "new" and alias else ""))
    if not args.dry_run:
        target = args.board
        if dedicated:
            # Idempotent: a retry after any partial failure finds the same board; the root's idempotency key finds the same root.
            project_dir = next((h.split(": ", 1)[1] for h in hdr if h.startswith("PROJECT_DIR:") and not h.endswith(": auto")), "")
            branch_name = next((h.split(": ", 1)[1] for h in hdr if h.startswith("BRANCH:")), "")
            ok, info = boards_cli("provision", t["id"], "--name", title, "--project", alias or (f.get("PROJECT") or ""),
                                  "--project-dir", project_dir, "--branch", branch_name)
            if not ok:
                msg = info.get("error") if isinstance(info, dict) else str(info)
                if isinstance(info, dict) and info.get("status") == "failed":
                    block_ticket(t, "run board could not be created: " + str(msg)[:300])
                else:
                    say("ticket %s: run board not ready yet (will retry): %s" % (t["id"], str(msg)[:200]))
                continue
            target = info["board"]
        r = hermes(["create", "FACTORY: " + title, "--assignee", assignee, "--skill", "software-factory",
                    "--max-runtime", "900", "--created-by", "factory-intake",
                    "--idempotency-key", "intake-" + t["id"], "--body-file", "-", "--json"], target, stdin=body)
        made = json.loads(r.stdout[r.stdout.index("{"):])
        rid = made.get("id") or made.get("task", {}).get("id")
        if dedicated:
            ok, info = boards_cli("bind-root", target, rid)
            if not ok:
                say("ticket %s: root %s created on %s but could not be bound (will retry): %s" % (t["id"], rid, target, str(info)[:200]))
                continue
        hermes(["comment", t["id"], "Spawned root %s%s" % (rid, " on board " + target if dedicated else "")], args.board, check=False)
        if hermes(["complete", t["id"], "--result", "root " + rid], args.board, check=False).returncode != 0:
            hermes(["archive", t["id"]], args.board, check=False)
    slots -= 1

if out:
    print("\n".join(out))
