#!/usr/bin/env python3
"""Plain-English status of a factory job. Usage: factory_status.py [root id] [--board RUN_BOARD]   (default: newest open FACTORY job)
Translates cards (c3, REVERIFY, ...) into words, shows who did what and how long, and what the job is waiting for."""
import argparse, re, sys, time
from factory_lib import board_of_root, kanban_list, kanban_show

ap = argparse.ArgumentParser()
ap.add_argument("root", nargs="?")
ap.add_argument("--board", default=None)
a = ap.parse_args()
board = a.board or (board_of_root(a.root) if a.root else None)  # a root id finds its own run board
tasks = kanban_list(board)
roots = [t for t in tasks if t["title"].startswith("FACTORY:")]
if a.root:
    root = next((t for t in roots if t["id"] == a.root), None)
else:
    openr = [t for t in roots if t["status"] != "done"] or roots
    root = max(openr, key=lambda t: t.get("created_at") or 0) if openr else None
if not root:
    sys.exit("no factory job found")

WHO = {"architect": "architect", "developer": "developer", "verifier": "verifier", "claude-reviewer": "Claude reviewer",
       "codex-reviewer": "Codex reviewer", "security-reviewer": "security reviewer", "ux-reviewer": "UX reviewer",
       "ui-reviewer": "UI reviewer", "factory-orchestrator": "orchestrator"}
VERDICT = {"PASS": "passed", "FAIL": "FAILED", "DONE": "done", "BLOCKED": "BLOCKED", "NO_BLOCKING_FINDINGS": "no blocking problems",
           "CHANGES_REQUIRED": "asked for changes"}

REVIEW_KIND = {"CLAUDE": ("Claude review", 2), "CODEX": ("Codex review", 3), "SECURITY": ("Security review", 4),
               "UX": ("UX review", 5), "UI": ("UI review", 6)}


def stage_name(title):
    t = re.sub(r"\s*\(t_[0-9a-f]+\)\s*$", "", title)
    m = re.match(r"(RE)?(VERIFY|(CLAUDE|CODEX|SECURITY|UX|UI) (?:RE-)?REVIEW)\s+c(\d)", t) or None
    n = int(m.group(4)) if m else 0
    when = "first build" if n == 1 else "after fix round %d" % (n - 1)
    if t.startswith("PLAN"):
        return 0, "Plan"
    if t.startswith("IMPLEMENT"):
        return 1, "First build"
    if t.startswith("FIX"):
        k = int(re.search(r"c(\d)", t).group(1))
        return k * 10, "Fix round %d" % (k - 1)
    if m:
        kind, order = ("Independent check", 1) if m.group(2) == "VERIFY" else REVIEW_KIND[m.group(3)]
        return n * 10 + order, "%s (%s)" % (kind, when)
    return 99, t


def mins(sec):
    return "%d min" % round(sec / 60) if sec >= 60 else "%d s" % sec


d = kanban_show(root["id"], board)
kids = [t for t in tasks if re.search(r"\(%s\)\s*$" % re.escape(root["id"]), t["title"])]
rows = []
for k in kids:
    kd = kanban_show(k["id"], board)
    runs = [r for r in kd.get("runs", []) if r.get("started_at")]
    last = runs[-1] if runs else None
    dur = ((last.get("ended_at") or time.time()) - last["started_at"]) if last else 0
    summ = (kd.get("latest_summary") or "").strip()
    v = re.match(r"VERDICT=(\w+)", summ)
    body = re.sub(r"^VERDICT=\S+.*\n?", "", summ).strip().replace("\n", " ")
    order, name = stage_name(k["title"])
    state = {"done": "✔", "running": "▶", "ready": "…", "todo": "·", "blocked": "✖", "archived": "-"}.get(k["status"], "?")
    res = VERDICT.get(v.group(1), v.group(1).lower()) if v else {"running": "working", "ready": "queued", "todo": "waiting"}.get(k["status"], k["status"])
    rows.append((order, "%s %-38s %-16s %-9s %s" % (state, name, WHO.get(k["assignee"], k["assignee"]), mins(dur) if last else "", res), body[:170]))
rows.sort(key=lambda r: r[0])
age = time.time() - (root.get("created_at") or time.time())
print("JOB: %s" % root["title"][len("FACTORY:"):].strip())
HUMAN = {"blocked": "NEEDS YOUR DECISION", "done": "FINISHED", "archived": "CANCELLED"}
nowrun = [r for r in rows if r[1].startswith("▶")] or [r for r in rows if r[1].startswith("…")]
where = (" - now: " + re.split(r"\s{2,}", nowrun[0][1][2:].strip())[0]) if nowrun and root["status"] not in ("blocked", "done") else ""
print("STATE: %s%s   (age %s, id %s)\n" % (HUMAN.get(root["status"], "IN PROGRESS"), where, mins(age), root["id"]))
for _, line, body in rows:
    print(line)
    if body:
        print("      " + body + ("..." if len(body) >= 170 else ""))
status_cmts = [c for c in d.get("comments", []) if (c.get("body") or "").startswith("STATUS:")]
print()
if status_cmts:
    print("LATEST UPDATE FROM THE FACTORY:\n" + status_cmts[-1]["body"][7:].strip() + "\n")
if root["status"] == "blocked":
    reason = ""
    for e in reversed(d.get("events", [])):
        if e.get("kind") == "blocked":
            import json
            p = e.get("payload"); p = json.loads(p) if isinstance(p, str) else (p or {})
            reason = (p.get("reason") or "").strip(); break
    print("WAITING FOR YOU:\n" + reason)
