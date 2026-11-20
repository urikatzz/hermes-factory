#!/usr/bin/env python3
"""Hermes patch guard (cron --no-agent). The Factory needs local patches in the Hermes source tree (runtime/hermes-patches); a Hermes
update resets that tree and removes them. This checks the tree against the patch manifest, records the result in
state/factory/hermes-patches.json (the intake pump starts no new work while patches are missing) and prints one message per change
(empty output = silent):
  - patches missing or conflicting after an update
  - patches restored (by --repair or by hand), with the reminder that a running gateway must be restarted to load them
--repair applies missing patches that apply cleanly, with backups and rollback (hermes_patches.py apply). It waits until the same problem
has been seen for SETTLE seconds, never runs while a Hermes update is in progress, and never touches a conflict (a human resolves it).
It never restarts anything.
Usage: factory_patch_check.py [--repair] [--source DIR] [--dry-run]"""
import argparse, contextlib, io, json, os, subprocess, sys, time
from factory_lib import HOME, STATE_DIR, atomic_write_json

PATCH_HOME = os.environ.get("HERMES_PATCHES_DIR") or os.path.join(HOME, "hermes-patches")
STATE = os.path.join(STATE_DIR, "hermes-patches.json")
SETTLE = 120  # seconds the same problem must persist before --repair acts (an update may still be writing the tree)


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def update_running(source):
    if os.path.exists(os.path.join(source, ".git", "index.lock")):
        return True
    try:
        found = subprocess.run(["pgrep", "-f", "hermes update|desktop-update/update-panel|hermes-agent/scripts/desktop-update"],
                               capture_output=True, text=True, timeout=10)
        return found.returncode == 0 and bool(found.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--source", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.path.insert(0, PATCH_HOME)
    try:
        import hermes_patches as hp
    except ImportError:
        print("Hermes patch guard cannot run: %s/hermes_patches.py is missing (copy runtime/hermes-patches to ~/.hermes/hermes-patches)." % PATCH_HOME)
        return
    source = str(hp.source_dir(args.source))
    report = hp.status(hp.source_dir(args.source))
    now = int(time.time())
    previous = load_state()
    signature = json.dumps([report["head"], report["missing"], report["conflicts"]])
    first_seen = previous.get("first_seen", now) if previous.get("signature") == signature and not report["ok"] else now
    messages, repaired = [], []
    if not report["ok"] and args.repair and not args.dry_run and not report["conflicts"] \
            and now - first_seen >= SETTLE and not update_running(source):
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            code = hp.cmd_apply(argparse.Namespace(source=source, dry_run=False))
        report = hp.status(hp.source_dir(args.source))
        if code == 0 and report["ok"]:
            repaired = [p["id"] for p in previous.get("patches", []) if p["state"] != "applied"] or previous.get("missing", [])
            messages.append("HERMES PATCHES REAPPLIED (%s) on Hermes %s. Restart the Hermes gateway to load them." % (", ".join(repaired), report["head"][:12]))
    state = dict(ok=report["ok"], checked_at=now, head=report["head"], known_head=report["known_head"], missing=report["missing"],
                 conflicts=report["conflicts"], patches=report["patches"], signature=json.dumps([report["head"], report["missing"], report["conflicts"]]),
                 first_seen=first_seen if not report["ok"] else now, reapplied=repaired or previous.get("reapplied", []))
    if not report["ok"] and previous.get("signature") != state["signature"]:
        what = ("conflict with this Hermes version (a human must resolve it, see runtime/hermes-patches/README.md): " + ", ".join(report["conflicts"])
                if report["conflicts"] else "missing: " + ", ".join(report["missing"]))
        messages.append("HERMES PATCHES %s (Hermes %s). The Factory cannot create stages until they are restored: run `hermes_patches.py apply` "
                        "(or enable --repair on this job), then restart the Hermes gateway. New factory work is paused." % (what, report["head"][:12]))
    elif report["ok"] and previous.get("ok") is False and not repaired:
        messages.append("Hermes patches are present again on Hermes %s. Restart the Hermes gateway if it started before they were restored." % report["head"][:12])
    if not args.dry_run:
        atomic_write_json(STATE, state, indent=1)
    for line in messages:
        print(line)


if __name__ == "__main__":
    main()
