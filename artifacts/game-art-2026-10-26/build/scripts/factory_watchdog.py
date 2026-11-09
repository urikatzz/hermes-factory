#!/usr/bin/env python3
"""Factory watchdog (no LLM). Recovers ENVIRONMENT blocks on FACTORY roots and leaves every judgment call to the human.

Per run:
  1. If any factory root is active (todo/ready/running) and Docker is down, try to start Docker (rate limited).
  2. Unity Editor busy: when a block is caused by the Unity Editor owning the project, ask Unity to quit GRACEFULLY
     (osascript quit; Unity shows its own save prompt, so unsaved work is never discarded) and retry. Never kill -9.
  3. For each blocked FACTORY root, look at its latest `blocked` event:
       - auto-retry ONLY when the block's reason names an environment cause (Docker unavailable, Unity Editor busy) and
         nothing else (no defects, unfinished work or regressions), the orchestrator's own printed reply line is free of
         waiver/approval/stop/deliver wording, preflight passes, and the card has retries left (MAX_AUTO_RETRIES per
         card). The reply sent is the orchestrator's own text, verbatim. The block KIND never counts: the orchestrator
         alternates needs_input/capability on repeated escalations, so kind=capability is routinely a human decision.
       - anything else (needs_input decisions, accepting failures, approving plans, publishing) is only reported.
  Usage: factory_watchdog.py [--dry-run]. stdout is the report (empty when nothing happened)."""
import json, os, re, subprocess, sys, time
from factory_lib import STATE_DIR, atomic_write_json, hermes, kanban_list, kanban_show, load_config

DRY = "--dry-run" in sys.argv
MAX_AUTO_RETRIES = 2
MAX_CARD_CHARS = 85000          # the orchestrator's tool output spills to an unreadable file around 100k chars
DOCKER_WAIT_SECONDS = 180
DOCKER_RETRY_COOLDOWN = 300
DOCKER_BOOT_GRACE = 240       # seconds a freshly started Docker VM may take before it counts as stuck
STATE = os.path.join(STATE_DIR, "watchdog.json")
UNITY_QUIT_WAIT_SECONDS = 90
UNITY_COOLDOWN = 600
BAD_REPLY = re.compile(r"\b(stop|accept|waive|waiver|approv\w*|exception\w*|substitut\w*|skip|ignore|override|disable|publish|merge|deliver\w*)\b", re.I)
DOCKER_BLOCK = re.compile(r"docker", re.I)
DOCKER_DOWN = re.compile(r"unavailable|not (running|available|reachable)|restore docker|make docker available|daemon|cannot connect", re.I)
UNITY_BUSY = re.compile(r"unity[^.\n]{0,80}\b(busy|already open|running|locked|owns the project)|editor[^.\n]{0,60}\b(busy|already open|running|locked)|\b(busy|open)[^.\n]{0,30}unity|PID \d+", re.I)
# Anything besides the environment in the same escalation (defects, unfinished work) needs a human decision.
NOT_ENV_ONLY = re.compile(r"incomplete|unfinished|not complete|defect|\bbugs?\b|regression|compiler? errors?|compilation errors?|"
                          r"asked for changes|found (a|an|one|two|three|\d+|several|some|problems?|issues?)\b", re.I)
REPLY = re.compile(r'hermes kanban unblock (t_[0-9a-f]+) --reason "([^"]+)"')


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"cards": {}, "docker_last_attempt": 0, "unity_last_attempt": 0}


def save_state(st):
    if DRY:
        return
    atomic_write_json(STATE, st, indent=1)


def docker_ok():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=25).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_docker(st, out):
    """Start Docker Desktop if it is down. Returns True when the daemon answers."""
    if docker_ok():
        return True
    if time.time() - st.get("docker_last_attempt", 0) < DOCKER_RETRY_COOLDOWN:
        return False
    st["docker_last_attempt"] = time.time()
    # "Running but dead": the app and VM are up yet the engine never answers (seen after a VM crash). `open -a` does nothing
    # then, so do a full graceful quit + restart. A just-launched Docker gets DOCKER_BOOT_GRACE seconds to finish booting.
    stuck = subprocess.run(["pgrep", "-f", "com.docker.virtualization"], capture_output=True).returncode == 0
    if stuck:
        age = subprocess.run("ps -o etime= -p $(pgrep -f com.docker.virtualization | head -1)", shell=True, capture_output=True, text=True).stdout.strip()
        secs = 0
        for part in age.replace("-", ":").split(":"):
            secs = secs * 60 + int(part or 0) if part.isdigit() else secs
        if secs < DOCKER_BOOT_GRACE:
            return False  # still booting; check again next tick
    if DRY:
        out.append("[dry-run] Docker is down; would %s" % ("quit and restart Docker Desktop (engine dead)" if stuck else "run `open -a Docker`"))
        return False
    if stuck:
        out.append("Docker Desktop is running but its engine is dead: restarting Docker Desktop")
        subprocess.run(["osascript", "-e", 'quit app "Docker"'], capture_output=True, timeout=30)
        for _ in range(20):
            if subprocess.run(["pgrep", "-f", "com.docker.virtualization"], capture_output=True).returncode != 0:
                break
            time.sleep(3)
        subprocess.run(["pkill", "-f", "Docker.app/Contents/MacOS/com.docker.backend"], capture_output=True)
        time.sleep(3)
    else:
        out.append("Docker is down while the factory is active: starting Docker Desktop")
    subprocess.run(["open", "-a", "Docker"], capture_output=True)
    deadline = time.time() + DOCKER_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(5)
        if docker_ok():
            out.append("Docker is up again")
            return True
    out.append("NEEDS YOU: Docker did not come up within %ds (a crash dialog may be open; quit and reopen Docker Desktop)" % DOCKER_WAIT_SECONDS)
    return False


def unity_pids():
    """PIDs of Unity Editors that have a BouncingGems project open."""
    try:
        out = subprocess.run(["pgrep", "-f", "Unity.app/Contents/MacOS/Unity"], capture_output=True, text=True).stdout.split()
    except OSError:
        return []
    pids = []
    for pid in out:
        args = subprocess.run(["ps", "-o", "args=", "-p", pid], capture_output=True, text=True).stdout
        if "BouncingGems" in args or "-projectPath" not in args:
            pids.append(pid)
    return pids


def ensure_unity_closed(st, out):
    """Ask Unity to quit gracefully. Returns True when no Editor holds the project."""
    if not unity_pids():
        return True
    if time.time() - st.get("unity_last_attempt", 0) < UNITY_COOLDOWN:
        return False
    st["unity_last_attempt"] = time.time()
    if DRY:
        out.append("[dry-run] Unity Editor is open; would run `osascript -e 'quit app \"Unity\"'`")
        return False
    out.append("Unity Editor is open and blocking a factory run: asking Unity to quit (it will prompt to save unsaved work)")
    subprocess.run(["osascript", "-e", 'tell application "Unity" to quit'], capture_output=True, timeout=30)
    deadline = time.time() + UNITY_QUIT_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(3)
        if not unity_pids():
            out.append("Unity closed")
            return True
    out.append("NEEDS YOU: Unity did not quit within %ds (it is probably asking to save unsaved changes); save or discard and close it, and the retry will go out on the next check" % UNITY_QUIT_WAIT_SECONDS)
    return False


def last_event(events, kind):
    hit = [e for e in events if (e.get("kind") or e.get("type")) == kind]
    return hit[-1] if hit else None


def main():
    cfg = load_config()
    prefix = cfg.get("root_prefix", "FACTORY:")
    st = load_state()
    out = []

    active = [t for s in ("todo", "ready", "running") for t in kanban_list(status=s) if t.get("title", "").startswith(prefix)]
    if active:
        ensure_docker(st, out)

    for t in kanban_list(status="blocked"):
        if not t.get("title", "").startswith(prefix):
            continue
        tid = t["id"]
        d = kanban_show(tid)
        ev = d.get("events", [])
        blk = last_event(ev, "blocked")
        if not blk:
            continue
        unb = last_event(ev, "unblocked")
        ts = blk.get("created_at") or 0
        if unb and (unb.get("created_at") or 0) > ts:
            continue  # already unblocked after that block; board status is stale or transitioning
        payload = blk.get("payload") or {}
        reason = payload.get("reason") or ""
        card = st["cards"].setdefault(tid, {"retries": 0, "seen": 0})
        if card["seen"] == ts:
            continue  # already handled this exact block
        docker_cause = bool(DOCKER_BLOCK.search(reason) and DOCKER_DOWN.search(reason))
        unity_cause = bool(UNITY_BUSY.search(reason))
        env = (docker_cause or unity_cause) and not NOT_ENV_ONLY.search(reason)
        head = reason.strip().splitlines()[0][:160] if reason.strip() else "(no reason)"

        if not env:
            card["seen"] = ts
            out.append("NEEDS YOU (%s): %s -> %s" % (tid, t["title"][:60], head))
            continue
        if card["retries"] >= MAX_AUTO_RETRIES:
            card["seen"] = ts
            out.append("NEEDS YOU (%s): auto-retry limit (%d) reached; last block: %s" % (tid, MAX_AUTO_RETRIES, head))
            continue
        replies = [m.group(2) for m in REPLY.finditer(reason) if m.group(1) == tid and not BAD_REPLY.search(m.group(2))]
        if not replies:
            card["seen"] = ts
            out.append("NEEDS YOU (%s): environment block but no safe retry reply offered: %s" % (tid, head))
            continue
        if docker_cause and not ensure_docker(st, out):
            continue  # try again next tick; do not mark as seen
        if unity_cause and not ensure_unity_closed(st, out):
            continue  # same: retry next tick, never mark as seen
        size = len(json.dumps(d))
        if size > MAX_CARD_CHARS:
            card["seen"] = ts
            out.append("NEEDS YOU (%s): card is %d chars (> %d); the orchestrator cannot read it. Shorten the card body or archive old comments first." % (tid, size, MAX_CARD_CHARS))
            continue
        if DRY:
            out.append("[dry-run] would unblock %s with: %s" % (tid, replies[0][:140]))
            continue
        hermes(["unblock", tid, "--reason", replies[0]])
        card["retries"] += 1
        card["seen"] = ts
        out.append("AUTO-RETRY %d/%d (%s): %s" % (card["retries"], MAX_AUTO_RETRIES, tid, replies[0][:140]))

    save_state(st)
    if out:
        print("\n".join(out))


if __name__ == "__main__":
    main()
