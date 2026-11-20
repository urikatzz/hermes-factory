#!/usr/bin/env python3
"""Drop a ticket into the factory intake queue (Triage lane). The intake pump turns it into a FACTORY root.
  factory_ticket.py --title "Add daily reward popup" --project bouncinggems --type feature \
      --acceptance "popup shows once per day" --request "..."
  --project new   -> brand-new project (optional --new-dir /abs/path)."""
import argparse, os, re, subprocess, sys
from factory_lib import hermes, load_config, load_repos, resolve_project, git

p = argparse.ArgumentParser()
p.add_argument("--title", required=True)
p.add_argument("--project", default="", help="repo alias from state/factory/repos.json (default repo if omitted), an absolute path, or 'new'")
p.add_argument("--type", default="feature", choices=["feature", "bug", "chore", "art", "audio"])
p.add_argument("--request", required=True)
p.add_argument("--acceptance", default="")
p.add_argument("--new-dir", default="")
p.add_argument("--decompose", action="store_true", help="let `kanban decompose` split a large ticket first")
p.add_argument("--priority", default="0")
p.add_argument("--board", default=None)
p.add_argument("--force", action="store_true", help="skip the body-size and unreadable-path checks")

MAX_BODY = 12000  # the orchestrator cannot read a card whose output exceeds ~100k chars; long text belongs in a committed file


def preflight(a):
    """Refuse tickets that the factory workers cannot act on. Returns a list of problems."""
    problems = []
    text = "\n".join([a.request, a.acceptance])
    if len(text) > MAX_BODY:
        problems.append("ticket text is %d chars (limit %d): commit the long plan to the repo on the base branch and reference its repo-relative path" % (len(text), MAX_BODY))
    try:
        kind, path, alias, rcfg = resolve_project(a.project)
    except Exception:
        kind, path, rcfg = None, None, {}
    if path:
        base = (rcfg or {}).get("base")
        for m in set(re.findall(r"(/Users/[^\s`\"'<>)]+)", text)):
            m = m.rstrip(".,;:")
            if not m.startswith(path.rstrip("/") + "/") or "/.worktrees/" in m:
                continue
            rel = m[len(path.rstrip("/")) + 1:]
            if base:
                git(path, "fetch", "origin", base)
            ref = "origin/%s:%s" % (base, rel) if base else "HEAD:%s" % rel
            if git(path, "cat-file", "-e", ref)[0] != 0:
                problems.append("%s is not on %s: workers only see their own worktree, so this path will be 'File not found'. Commit and push it on the base branch (then reference %s), or inline the needed text" % (m, base or "HEAD", rel))
    return problems


def docker_note(a):
    text = (a.request + a.acceptance).lower()
    if any(k in text for k in ("server/nakama", "protogen", "make -c server")):
        try:
            ok = subprocess.run(["docker", "info"], capture_output=True, timeout=25).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if not ok:
            print("WARNING: Docker is not answering, and this ticket needs it (server tests / protogen). The watchdog will try to start it once the card is active.", file=sys.stderr)


a = p.parse_args()
if not a.force:
    probs = preflight(a)
    if probs:
        print("TICKET REFUSED:\n- " + "\n- ".join(probs) + "\n(use --force to override)", file=sys.stderr)
        sys.exit(2)
docker_note(a)
cfg = load_config()
lines = ["FACTORY_TICKET v1", "PROJECT: " + a.project, "TYPE: " + a.type]
if a.new_dir:
    lines.append("NEW_DIR: " + a.new_dir)
if a.decompose:
    lines.append("DECOMPOSE: yes")
lines += ["ACCEPTANCE: " + (a.acceptance or "none"), "REQUEST:", a.request]
r = hermes(["create", "%s %s" % (cfg["ticket_prefix"], a.title), "--triage", "--priority", a.priority,
            "--created-by", "factory-ticket", "--body-file", "-", "--json"], a.board, stdin="\n".join(lines) + "\n")
print(r.stdout.strip())
