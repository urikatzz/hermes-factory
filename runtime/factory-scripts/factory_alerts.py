#!/usr/bin/env python3
"""Factory alerts (cron --no-agent, delivered to Telegram). Prints one message per newly noticed situation; empty
output = silent:
  - a card that entered BLOCKED or REVIEW (a human decision is needed)
  - a FACTORY root that Hermes's block-loop breaker moved to Triage (stuck: `unblock` no longer works there)
  - a card the dispatcher keeps holding because its last error looked like a quota/login failure (respawn guard
    `blocker_auth`), a hold that never lifts by itself
  - a FACTORY root that finished in the last day, with its outcome and, for AUTO_PR jobs, the draft PR link or why no
    PR was opened (waits up to 15 min for the publisher; a later publisher result goes out as PR UPDATE)
Routine root waits (kind=dependency) sit in `todo`, so they never alert. The very first run only records the current
state (no flood). State: state/factory/alerts_seen.json.
Usage: factory_alerts.py [--board SLUG] [--dry-run] [--no-seed]"""
import argparse, json, os, time
from factory_lib import fan_out, STATE_DIR, atomic_write_json, kanban_list, kanban_show, load_config

FINISHED_WINDOW = 24 * 3600  # announce roots that finished within the last day only
PR_WAIT = 15 * 60            # how long a finished AUTO_PR root waits for the publisher's result before announcing
STALL_AFTER = 15 * 60        # a blocker_auth hold at least this old is reported

ap = argparse.ArgumentParser()
ap.add_argument("--board", default=None)
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--no-seed", action="store_true")
args = ap.parse_args()
fan_out(args.board)  # one isolated run per registered run board, then the default board below
suffix = "_" + args.board if args.board else ""
seen_path = os.path.join(STATE_DIR, "alerts_seen%s.json" % suffix)
# A run board is born with its ticket, so nothing on it is old news: only the default board's first run seeds.
first = not os.path.exists(seen_path) and not args.no_seed and not args.board
prefix = load_config()["root_prefix"]
now_ts = time.time()


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


seen = load_json(seen_path)
published = load_json(os.path.join(STATE_DIR, "published%s.json" % suffix))
msgs, now = [], {}


def note(task_id, key, text):
    """Queue text unless this exact situation was already reported (or this is the seeding run)."""
    now[task_id] = key
    if seen.get(task_id) != key and not first:
        msgs.append(text)


def payload_of(e):
    p = e.get("payload")
    return json.loads(p) if isinstance(p, str) else (p or {})


def latest(events, kinds):
    """(created_at, payload) of the newest event of those kinds, or (0, {})."""
    for e in reversed(events):
        if e.get("kind") in kinds:
            return e.get("created_at", 0), payload_of(e)
    return 0, {}


def short_title(t):
    title = t.get("title") or ""
    return (title[len(prefix):].strip() if title.startswith(prefix) else title)[:80]


def header(body, key):
    for line in (body or "").splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def guard_hold_since(events):
    """Start of the current, unbroken blocker_auth respawn-guard hold, or None."""
    since = None
    for e in reversed(events):
        if e.get("kind") == "heartbeat":
            continue
        if e.get("kind") != "respawn_guarded" or payload_of(e).get("reason") != "blocker_auth":
            break
        since = e.get("created_at")
    return since


for status in ("blocked", "review"):
    for t in kanban_list(args.board, status):
        d = kanban_show(t["id"], args.board)
        task = d["task"]
        eid, payload = latest(d.get("events", []), {"blocked"} if status == "blocked" else {"review_requested", "review", "request_review"})
        key = "%s@%s" % (status, eid or t.get("started_at") or t.get("created_at"))
        if status == "blocked":
            reason = (payload.get("reason") or task.get("last_failure_error") or "").strip()
            text = "%s %s | %s\n%s" % ("NEEDS YOUR DECISION" if "NEEDS YOUR DECISION" in reason else "BLOCKED", t["id"],
                                       short_title(t), reason[:900] or "(no reason recorded)")
            if "REPLY WITH" not in reason:
                text += "\nReply: hermes kanban unblock %s --reason \"retry | waive <ids> | stop\"" % t["id"]
        else:
            text = "REVIEW %s | %s\n%s" % (t["id"], t["title"][:80], (t.get("result") or "ready for your review")[:300])
        note(t["id"], key, text)

for t in kanban_list(args.board, "triage"):
    if not t["title"].startswith(prefix):
        continue  # tickets wait in Triage by design
    eid, payload = latest(kanban_show(t["id"], args.board).get("events", []), {"block_loop_detected", "blocked"})
    reason = (payload.get("reason") or "").strip()
    note(t["id"], "triage@%s" % (eid or t.get("created_at")),
         "STUCK %s | %s\nHermes moved this job to Triage after it blocked twice in a row, so `hermes kanban unblock` "
         "no longer works on it.\n%s\nResume it from the Kanban dashboard, or stop it: hermes kanban archive %s"
         % (t["id"], short_title(t), reason[:900] or "(no reason recorded)", t["id"]))

for t in kanban_list(args.board, "ready"):
    if not t.get("last_failure_error"):
        continue  # the blocker_auth hold only exists after a recorded quota/login failure
    since = guard_hold_since(kanban_show(t["id"], args.board).get("events", []))
    if not since or now_ts - since < STALL_AFTER:
        continue
    note(t["id"], "stall@%s" % since,
         "STALLED %s | %s\nThe dispatcher has not started this card for %d min: its last error looked like a quota or "
         "login failure (%s), and that hold never lifts by itself.\nIf the provider works again, release it:\n"
         "hermes kanban block --kind transient %s clear stale quota error\nhermes kanban unblock %s"
         % (t["id"], short_title(t), (now_ts - since) // 60, t["last_failure_error"][:160], t["id"], t["id"]))

for t in kanban_list(args.board, "done"):
    done_at = t.get("completed_at") or 0
    if not t["title"].startswith(prefix) or now_ts - done_at > FINISHED_WINDOW:
        continue
    pub, prev = published.get(t["id"], {}), seen.get(t["id"], "")
    if header(t.get("body"), "AUTO_PR") != "yes":
        pr, line = "none", ""
    elif "url" in pub:
        pr, line = "url", "PR (draft): " + pub["url"]
    elif "skipped" in pub:
        pr, line = "skipped", "No PR: " + pub["skipped"]
    elif pub.get("n", 0) >= 3:
        pr, line = "failed", "PR NOT OPENED after 3 tries: " + (pub.get("error") or "")[:400]
    elif now_ts - done_at < PR_WAIT and not prev.startswith("done@"):
        continue  # give the publisher a few minutes to open the PR
    else:
        pr, line = "pending", "PR not opened yet; the publisher is still working on it."
    if prev.startswith("done@%s|" % done_at):
        text = "PR UPDATE %s | %s\n%s" % (t["id"], short_title(t), line)
    else:
        summary = (kanban_show(t["id"], args.board).get("latest_summary") or t.get("result") or "").strip()
        text = "FINISHED %s | %s\n%s%s" % (t["id"], short_title(t), summary[:500], "\n" + line if line else "")
    note(t["id"], "done@%s|%s" % (done_at, pr), text)

if not args.dry_run:
    atomic_write_json(seen_path, now)
if msgs:
    print("\n\n".join(msgs))
