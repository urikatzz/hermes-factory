#!/usr/bin/env python3
"""Factory publisher (cron --no-agent). Host code, not a worker: for each finished FACTORY root with
OUTCOME=LOCAL_DELIVERED, AUTO_PR: yes and ISOLATION: worktree it commits ONLY the verified manifest files
(never .factory/), pushes the job branch and opens a DRAFT pull request. Never merges. Idempotent via
state/factory/published.json. Prints one line per action (empty = silent).
Usage: factory_publish.py [--board SLUG] [--dry-run]"""
import argparse, json, os, re, shlex, shutil, subprocess, sys, tempfile
from factory_lib import (HOME, STATE_DIR, atomic_write_json, git, kanban_list, kanban_show, load_config, load_repos,
                         run_gate)

FW = os.path.join(HOME, "factory-skills", "worker", "factory-worker", "scripts", "fw.py")
ap = argparse.ArgumentParser()
ap.add_argument("--board", default=None)
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()
state_path = os.path.join(STATE_DIR, "published%s.json" % ("_" + args.board if args.board else ""))
try:
    state = json.load(open(state_path))
except (OSError, ValueError):
    state = {}
cfg_all = load_config()
gate_timeout = cfg_all["writer_gate_timeout"]
out = []
# A pr-writer body must carry the factory-pr template's sections, or the plain plan body is used instead.
PR_SECTIONS = ("## Summary", "## Evidence", "## Merge Danger", "**Door:**", "**Blast Radius:**")


def save_state():
    """After every root, atomically: a sweep killed mid-way (cron stops a script after 3600 s) keeps its progress."""
    if not args.dry_run:
        atomic_write_json(state_path, state, indent=1)


def hv(body, key):
    for line in (body or "").splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def fail(rid, why):
    ent = state.get(rid, {})
    ent["error"], ent["n"] = why, ent.get("n", 0) + 1
    state[rid] = ent
    if ent["n"] == 1:
        out.append("PUBLISH FAILED %s: %s" % (rid, why))


def write_dossier(folder, d, body, blob, wt, base, files, plan):
    """What the pr-writer reads: the job, the plan, the committed diff and every stage card's runs (data only)."""
    dossier = os.path.join(folder, "dossier")
    os.makedirs(dossier)
    rng = "%s...HEAD" % base
    if git(wt, "rev-parse", "--verify", "-q", base)[0] != 0:  # worktree without a local base branch
        rng = "origin/%s...HEAD" % base
    _, stat, _ = git(wt, "diff", "--no-color", "--stat=120", rng, "--", *files)
    _, patch, _ = git(wt, "diff", "--no-color", rng, "--", *files)
    if len(patch) > 80000:
        patch = patch[:80000] + "\n... diff cut at 80000 chars; diffstat.txt is complete ...\n"
    runs = "\n".join("- %s: %s" % (r.get("outcome"), r.get("summary")) for r in d.get("runs") or [])
    root_md = "# %s\n\n## Root header and request\n%s\n\n## Final result\n%s\n\n## Root runs\n%s\n" % (
        d["task"]["title"], body, blob.strip(), runs)
    stages = []
    for pid in d.get("parents") or []:
        pid = pid if isinstance(pid, str) else pid.get("id")
        try:
            t, stage_runs = kanban_show(pid, args.board), []
        except Exception as ex:
            stages.append({"id": pid, "error": "unreadable: %s" % ex})
            continue
        for r in t.get("runs") or []:
            meta = r.get("metadata")
            if len(json.dumps(meta, default=str)) > 6000:
                meta = json.dumps(meta, default=str)[:6000] + " ...cut"
            stage_runs.append(dict({k: r.get(k) for k in ("profile", "outcome", "summary", "error")}, metadata=meta))
        stages.append({"id": pid, "title": t["task"].get("title"), "assignee": t["task"].get("assignee"),
                       "status": t["task"].get("status"), "runs": stage_runs})
    for name, text in (("root.md", root_md), ("PLAN.md", plan), ("diff.patch", patch), ("diffstat.txt", stat),
                       ("stages.json", json.dumps(stages, indent=1, default=str))):
        with open(os.path.join(dossier, name), "w") as f:
            f.write(text)
    return dossier


def write_pr_body(rid, d, body, blob, wt, base, files, plan):
    """One oneshot run of the pr-writer profile (factory-pr skill). -> (markdown or None, why it was not used)."""
    profile = cfg_all.get("pr_writer_profile")
    if not profile:
        return None, "disabled"
    # A kanban-style scratch workspace: the profile's workspace-write-guard lets write_file reach only this folder.
    ws_root = os.path.join(HOME, "kanban", "workspaces")
    os.makedirs(ws_root, exist_ok=True)
    folder = tempfile.mkdtemp(prefix="pr-%s-" % rid, dir=ws_root)
    try:
        dossier = write_dossier(folder, d, body, blob, wt, base, files, plan)
        query = os.path.join(folder, "query.txt")
        with open(query, "w") as f:
            f.write("DOSSIER=%s\nOUT=%s\nJOB=%s\nWrite the draft PR body for this factory job. Follow the factory-pr "
                    "skill.\n" % (dossier, folder, rid))
        cmd = ["hermes", "-p", profile, "chat", "--oneshot", "-Q", "-s", "factory-pr", "--in", folder,
               "--query-file", query]
        # Own process group + timeout, like the writer gates: a hung agent is stopped, the PR still opens.
        rc, o, e, timed_out = run_gate("HERMES_KANBAN_WORKSPACE=%s %s" % (shlex.quote(folder), shlex.join(cmd)), folder,
                                       cfg_all["pr_writer_timeout"])
        if timed_out or rc != 0:
            return None, "timed out" if timed_out else "exit %d: %s" % (rc, (e or o)[-200:])
        try:
            text = open(os.path.join(folder, "PR.md")).read().strip()
        except OSError:
            return None, "no PR.md written"
        missing = [h for h in PR_SECTIONS if h not in text]
        if missing or len(text) > 50000:
            return None, "PR.md rejected (%s)" % ("missing " + ", ".join(missing) if missing else "over 50000 chars")
        return text, ""
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def publish(root):
    rid, body = root["id"], root.get("body") or ""
    d = kanban_show(rid, args.board)
    blob = "%s\n%s" % (d["task"].get("result") or "", d.get("latest_summary") or "")
    if "OUTCOME=LOCAL_DELIVERED" not in blob:
        state[rid] = {"skipped": "outcome is not LOCAL_DELIVERED"}
        return
    wt, branch, repo = hv(body, "PROJECT_DIR"), hv(body, "BRANCH"), hv(body, "REPO_DIR")
    alias, base = hv(body, "REPO"), hv(body, "BASE_BRANCH") or "main"
    cfg = load_repos().get("repos", {}).get(alias, {})
    if not (wt and branch and repo and cfg.get("remote")):
        state[rid] = {"skipped": "no worktree/remote configured"}
        return
    rc, user, _ = run(["gh", "api", "user", "--jq", ".login"])
    if rc != 0 or user != cfg.get("gh_user", user):
        return fail(rid, "gh active account is %r, repo needs %r (gh auth switch -u %s)" % (user, cfg.get("gh_user"), cfg.get("gh_user")))
    rc, o, e = run(["python3", FW, "check", wt])
    if rc != 0:
        return fail(rid, "manifest check failed: " + (o or e)[:200])
    sha12 = json.loads(o)["sha12"]
    files = []
    for line in open(os.path.join(wt, ".factory", "SHA256SUMS")):
        p = line.rstrip("\n").split("  ", 1)[-1]
        if p and not p.startswith(".factory/"):
            files.append(p)
    porcelain = subprocess.run(["git", "-C", wt, "status", "--porcelain", "--untracked-files=all"],
                               capture_output=True, text=True, timeout=60).stdout  # raw: leading spaces are significant
    changed = {l[3:].split(" -> ")[-1].strip('"') for l in porcelain.splitlines()}
    stray = sorted(p for p in changed if not p.startswith(".factory/") and p not in files)
    if stray:
        return fail(rid, "worktree has changes outside the verified manifest, refusing to publish: " + ", ".join(stray[:8]))
    if not any(p in changed for p in files):
        state[rid] = {"skipped": "manifest has no changes against the branch"}
        return
    # Independent host-side gate before anything leaves this machine: the repo's writer_gates (Unity compile + tests
    # through the Unity CLI) run on the finished worktree, whichever agent wrote the code.
    for g in cfg.get("writer_gates", []):
        if any(p == g["when"] or p.startswith(g["when"].rstrip("/") + "/") for p in files):
            # Own process group + timeout: a hung gate (a Unity editor waiting on a lock) is stopped with everything
            # it started, instead of being orphaned with the Unity lock held.
            rc, o, e, timed_out = run_gate(g["cmd"], wt, gate_timeout)
            if timed_out:
                return fail(rid, "writer gate timed out after %ds and was stopped (%s): %s"
                            % (gate_timeout, g["cmd"][:60], (o or e)[-300:]))
            if rc != 0:
                return fail(rid, "writer gate failed (%s): %s" % (g["cmd"][:60], (o or e)[-400:]))
    title = root["title"][len("FACTORY:"):].strip()
    # Conventional-commit style PR/commit title: "feat: ...", "fix: ...", "chore: ...", "feat(art): ...", "feat(audio): ..." (from the job's TYPE).
    ctype = {"bug": "fix", "chore": "chore", "art": "feat(art)", "audio": "feat(audio)"}.get(hv(body, "TYPE").lower(), "feat")
    if ctype in ("fix", "chore"):
        title = re.sub(r"^%s\s+" % ctype, "", title, flags=re.I) or title  # "Fix score overflow" -> "fix: score overflow"
    if not re.match(r"^(feat|fix|chore|docs|refactor|test)(\(.+\))?!?:", title):
        title = "%s: %s" % (ctype, title[:1].lower() + title[1:] if title[:2].upper() != title[:2] else title)
    plan = ""
    try:
        plan = open(os.path.join(wt, ".factory", "PLAN.md")).read()
    except OSError:
        pass
    note = ("\n\n> Client/Unity compile and EditMode tests are not run by the factory; the repository's CI is the gate for them.\n"
            if hv(body, "UNITY_CI") == "yes" else "")
    pr_body = ("Opened automatically by the Hermes software factory (draft; never auto-merged).\n"
               "Factory job `%s`, verified manifest `%s`, branch `%s`.%s\n\n## Factory result\n%s\n\n## Plan\n%s\n"
               % (rid, sha12, branch, note, blob.strip()[:6000], plan[:20000]))
    msg = "%s\n\nHermes factory job %s, manifest %s" % (title, rid, sha12)
    if args.dry_run:
        out.append("would publish %s: %d files, branch %s -> %s (%s)" % (rid, len(files), branch, cfg["remote"], base))
        return
    for cmd in (["git", "-C", wt, "--literal-pathspecs", "add", "--"] + files,
                ["git", "-C", wt] + sum((["-c", "user.%s=%s" % (k, cfg["git_" + k])] for k in ("name", "email") if cfg.get("git_" + k)), [])
                + ["commit", "-m", msg],
                ["git", "-C", wt, "push", "-u", "origin", branch]):
        rc, o, e = run(cmd)
        if rc != 0 and not ("commit" in cmd and "nothing to commit" in (o + e)):
            return fail(rid, "%s failed: %s" % ("commit" if "commit" in cmd else cmd[3] if cmd[3] in ("add", "push") else "git", (e or o)[:240]))
    # The pr-writer needs the commit (diff against base), so it runs after the push; any failure keeps the plan body.
    written, why = write_pr_body(rid, d, body, blob, wt, base, files, plan)
    if written:
        pr_body = "%s\n\n---\n\n<details><summary>Factory result and plan</summary>\n\n%s\n</details>\n" % (written, pr_body)
    elif why != "disabled":
        out.append("pr-writer not used for %s (%s); opened with the plan body" % (rid, why))
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
        tf.write(pr_body)
    rc, o, e = run(["gh", "pr", "create", "--repo", cfg["remote"], "--draft", "--base", base, "--head", branch,
                    "--title", title, "--body-file", tf.name])
    os.unlink(tf.name)
    if rc != 0:
        rc2, o2, _ = run(["gh", "pr", "view", branch, "--repo", cfg["remote"], "--json", "url", "--jq", ".url"])
        if rc2 != 0:
            return fail(rid, "gh pr create failed: " + (e or o)[:240])
        o = o2
    url = o.strip().splitlines()[-1]
    state[rid] = {"url": url}
    subprocess.run(["hermes", "kanban"] + (["--board", args.board] if args.board else []) + ["comment", rid, "PR (draft): " + url],
                   capture_output=True, text=True)
    out.append("PR opened (draft) %s | %s\n%s" % (rid, title, url))


for r in kanban_list(args.board, "done"):
    if not r["title"].startswith("FACTORY:") or r["id"] in state and ("url" in state[r["id"]] or "skipped" in state[r["id"]] or state[r["id"]].get("n", 0) >= 3):
        continue
    if hv(r.get("body"), "AUTO_PR") != "yes":
        continue
    try:
        publish(r)
    except Exception as ex:  # never let one root stop the sweep
        fail(r["id"], "unexpected: %s" % ex)
    save_state()
if out:
    print("\n\n".join(out))
