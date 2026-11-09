#!/usr/bin/env python3
"""fw.py - software-factory worker helper. Standard library only, Python 3.9+, never runs git.

  manifest PROJECT_DIR                  writer: rebuild .factory/SHA256SUMS from .factory/include.txt
  check    PROJECT_DIR [--expect S12]   verify the manifest (read-only)
  snapshot PROJECT_DIR WS [--expect S12]
                                        reader: WS/src-<sha12>.tgz (manifest files only) + WS/src-<sha12>/
  delta    BASE_TGZ NEW_DIR OUT_DIFF    cycle>=2 reader: extract BASE_TGZ beside OUT_DIFF, diff -ruN
  audit    DIR [--project-dir P]        verifier release audit of the manifest in DIR (read-only)
  publish-cmds PROJECT_DIR SLUG         text only: git/gh commands a HUMAN may run to publish
  clean    WS                           remove the src-*/base-* copies this script made in WS

Each command prints one JSON object. Exit codes: 0 ok, 2 usage/unsafe argument, 3 include list names
an excluded/unsafe/missing path, 4 manifest check failed, 5 sha12 mismatch. audit always exits 0.
Exclusions are case-insensitive (macOS volumes usually are), apply to every path component, and a path
whose real location differs from its spelling (a symlink anywhere in it) is refused.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

MANIFEST, INCLUDE, PLAN, MARKER = ".factory/SHA256SUMS", ".factory/include.txt", ".factory/PLAN.md", ".fw-snapshot"
TGZ_ATTACH_MAX = 25 * 1024 * 1024  # kanban attachment cap (hermes_cli/kanban_db.py:132)
# Never in a manifest and never copied (user decision (e); critic M4/M5). All lower case; compared casefolded.
EXCLUDED_DIRS = {".git", ".hg", ".svn", "node_modules", "dist", ".worktrees", "n8n", "__pycache__", ".venv",
                 "venv", ".cache", "coverage", "screenshots", ".pytest_cache", ".next", ".parcel-cache",
                 ".ssh", ".aws", ".gnupg", ".docker", ".kube"}
ENV_NAMES = (".env*", "*.env")  # .env, .env.local, .envrc, .env-prod, .env_prod, prod.env ...
EXCLUDED_NAMES = ENV_NAMES + (
    ".ds_store", "._*", "*.pem", "*.key", "*.p12", "*.pfx", "*.ppk", "*.keystore", "*.jks", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "id_xmss*", ".npmrc", ".netrc", ".pypirc", ".pgpass",
    ".htpasswd", ".git-credentials", "credentials", "credentials.json", "auth.json", "*service-account*.json",
    "serviceaccount*.json", "*.tgz", "*.tar.gz", "*.tar", "*.zip", "*.log", "*.sqlite", "*.sqlite3", "*.db",
    MARKER)
SECRETS = [(k, re.compile(p)) for k, p in (
    ("private_key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("github_token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    ("api_key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{24,}"),
    ("slack_token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    ("assigned_secret", r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b\s*[:=]\s*['\"][^'\"\s]{16,}['\"]"))]
DEBUG_FAIL = [(k, re.compile(p, re.M)) for k, p in (
    ("debugger_statement", r"^\s*debugger\s*;?\s*$"), ("focused_test", r"\b(?:it|describe|test)\.only\s*\("),
    ("pdb_trace", r"\b(?:pdb|ipdb)\.set_trace\s*\("), ("breakpoint_call", r"^\s*breakpoint\(\)\s*$"))]
DEBUG_INFO = [("console_log", re.compile(r"\bconsole\.log\s*\(")), ("todo_fixme", re.compile(r"\b(?:TODO|FIXME|XXX)\b"))]
LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")


class Refused(Exception):
    def __init__(self, msg, code=3, **extra):
        super().__init__(msg)
        self.code, self.extra = code, extra


def emit(obj, code=0):
    sys.stdout.write(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    sys.exit(code)


def abs_dir(path, what):
    if not path or not os.path.isabs(path) or not os.path.isdir(path):
        raise Refused("%s must be an existing absolute directory: %r" % (what, path), 2)
    return os.path.realpath(path)


def safe_rel(rel):
    rel = (rel or "").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.rstrip("/")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or "\\" in rel or any(ord(c) < 32 for c in rel) \
            or any(p in ("", ".", "..") for p in parts):
        raise Refused("unsafe path %r (list explicit relative paths; '.' and '..' are not allowed)" % rel)
    return rel


def is_env(name):
    return any(fnmatch.fnmatchcase(name.lower(), pat) for pat in ENV_NAMES)


def excluded(rel):
    """Why rel may never be in a manifest, or None. Case-insensitive; every component is checked."""
    parts = [p.lower() for p in rel.split("/")]
    hit = next((p for p in parts if p in EXCLUDED_DIRS or is_env(p)), None)
    if hit:
        return "excluded path component %s" % hit
    if parts[0] == ".factory" and rel.lower() not in (PLAN.lower(), INCLUDE.lower()):
        return "excluded path %s (only .factory/PLAN.md and .factory/include.txt are delivered)" % rel
    return next(("excluded name %s" % pat for pat in EXCLUDED_NAMES if fnmatch.fnmatchcase(parts[-1], pat)), None)


def unsafe_link(root, rel):
    """True if any component of root/rel is a symlink (its real location differs from its spelling)."""
    full = os.path.join(root, rel)
    return os.path.islink(full) or os.path.realpath(full) != os.path.join(os.path.realpath(root), rel)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha12(root):
    return sha256(os.path.join(root, MANIFEST))[:12]


def walk(root, top, skipped):
    """Regular files under root/top (relative), pruning excluded dirs; never follows symlinks."""
    found = []
    for cur, dirs, files in os.walk(os.path.join(root, top) if top else root):
        rel_cur = os.path.relpath(cur, root)
        rel_cur = "" if rel_cur == "." else rel_cur + "/"
        keep = []
        for d in sorted(dirs):
            why = "symlink" if os.path.islink(os.path.join(cur, d)) else excluded(rel_cur + d)
            if why:
                skipped.append({"path": rel_cur + d + "/", "why": why})
            else:
                keep.append(d)
        dirs[:] = keep
        for name in sorted(files):
            why = "symlink" if os.path.islink(os.path.join(cur, name)) else excluded(rel_cur + name)
            if why:
                skipped.append({"path": rel_cur + name, "why": why})
            else:
                found.append(rel_cur + name)
    return found


def rows(root):
    path = os.path.join(root, MANIFEST)
    if not os.path.isfile(path):
        raise Refused("missing %s" % MANIFEST, 4)
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                m = LINE.match(line.rstrip("\n"))
                if not m:
                    raise Refused("%s line %d is malformed" % (MANIFEST, n), 4)
                out.append((m.group(1), safe_rel(m.group(2))))
    return out


def ac_ids(root):
    path = os.path.join(root, PLAN)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return ["AC%d" % i for i in sorted({int(x) for x in re.findall(r"\bAC(\d{1,3})\b", f.read())})]


def check(root, expect=None):
    missing, mismatched, bad = [], [], []
    manifest = rows(root)
    for digest, rel in manifest:
        full = os.path.join(root, rel)
        if excluded(rel):
            bad.append({"path": rel, "why": excluded(rel)})
        elif unsafe_link(root, rel):
            bad.append({"path": rel, "why": "symlink in path"})
        if os.path.islink(full) or not os.path.isfile(full):
            missing.append(rel)
        elif sha256(full) != digest:
            mismatched.append(rel)
    res = {"ok": not (missing or mismatched or bad), "sha12": sha12(root), "files": len(manifest),
           "missing": missing[:50], "mismatched": mismatched[:50], "excluded_listed": bad[:50],
           "ac_ids": ac_ids(root), "dir": root}
    if not res["ok"]:
        return res, 4
    if expect is not None:
        want = expect.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{12,64}", want):
            raise Refused("--expect needs the 12-hex manifest sha12, got %r" % expect, 2)
        if want[:12] != res["sha12"]:
            res.update(ok=False, error="manifest sha12 %s != expected %s" % (res["sha12"], want[:12]))
            return res, 5
    return res, 0


def cmd_manifest(a):
    root = abs_dir(a.project_dir, "PROJECT_DIR")
    inc = os.path.join(root, INCLUDE)
    if not os.path.isfile(inc):
        raise Refused("missing %s (one relative file or directory per line, from PLAN.md)" % INCLUDE)
    with open(inc, encoding="utf-8") as f:
        entries = [safe_rel(l.split("#", 1)[0]) for l in f if l.split("#", 1)[0].strip()]
    entries += [e for e in (PLAN, INCLUDE) if os.path.isfile(os.path.join(root, e)) and e not in entries]
    refused, missing, skipped, files = [], [], [], set()
    for rel in entries:
        full = os.path.join(root, rel)
        why = excluded(rel) or ("symlink in path" if os.path.lexists(full) and unsafe_link(root, rel) else None)
        if why:
            refused.append({"path": rel, "why": why})
        elif os.path.isdir(full):
            files.update(walk(root, rel, skipped))
        elif os.path.isfile(full):
            files.add(rel)
        else:
            missing.append(rel)
    if refused or missing:
        raise Refused("include list names excluded, unsafe or missing paths; fix %s" % INCLUDE, 3,
                      refused=refused, missing=missing)
    os.makedirs(os.path.join(root, ".factory"), exist_ok=True)
    tmp = os.path.join(root, MANIFEST + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines("%s  %s\n" % (sha256(os.path.join(root, r)), r) for r in sorted(files))
    os.replace(tmp, os.path.join(root, MANIFEST))
    unlisted = [r for r in walk(root, "", []) if r not in files and not r.startswith(".factory/")]
    emit({"ok": True, "manifest": MANIFEST, "sha12": sha12(root), "files": len(files), "ac_ids": ac_ids(root),
          "unlisted_not_in_manifest": unlisted[:50], "excluded_inside_listed_dirs": skipped[:30], "dir": root})


def extract(tgz, dest):
    """Extract a tarball written by snapshot: regular files with safe names only."""
    if os.path.lexists(dest):
        if not os.path.isfile(os.path.join(dest, MARKER)):
            raise Refused("refusing to replace %s: not created by fw.py" % dest, 2)
        shutil.rmtree(dest)
    os.makedirs(dest)
    with tarfile.open(tgz, "r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                raise Refused("non-file member %r in %s" % (m.name, tgz), 4)
            target = os.path.join(dest, safe_rel(m.name))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tar.extractfile(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            os.chmod(target, (m.mode & 0o755) | 0o644)
            os.utime(target, (m.mtime, m.mtime))
    with open(os.path.join(dest, MARKER), "w") as f:
        f.write("created by fw.py from %s\n" % tgz)


def cmd_check(a):
    emit(*check(abs_dir(a.project_dir, "PROJECT_DIR"), a.expect))


def cmd_snapshot(a):
    root, ws = abs_dir(a.project_dir, "PROJECT_DIR"), abs_dir(a.workspace, "WS")
    if ws == root or ws.startswith(root + os.sep):
        raise Refused("WS must be your own scratch workspace, never inside PROJECT_DIR", 2)
    res, code = check(root, a.expect)
    if code:
        emit(res, code)
    s12, tgz = res["sha12"], os.path.join(ws, "src-%s.tgz" % res["sha12"])
    with tarfile.open(tgz + ".tmp", "w:gz", format=tarfile.PAX_FORMAT) as tar:
        for rel in [MANIFEST] + [r for _, r in rows(root)]:
            st = os.stat(os.path.join(root, rel))
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = st.st_size, int(st.st_mtime), (st.st_mode & 0o755) | 0o644
            with open(os.path.join(root, rel), "rb") as f:
                tar.addfile(info, f)
    os.replace(tgz + ".tmp", tgz)
    src = os.path.join(ws, "src-" + s12)
    extract(tgz, src)
    copy, code = check(src, s12)
    size = os.path.getsize(tgz)
    emit({"ok": code == 0, "sha12": s12, "tgz": tgz, "tgz_bytes": size, "attachable": size <= TGZ_ATTACH_MAX,
          "src_dir": src, "files": copy["files"], "ac_ids": res["ac_ids"], "project_dir": root}, code)


def cmd_delta(a):
    new = abs_dir(a.new_dir, "NEW_DIR")
    if not os.path.isabs(a.out_diff) or not os.path.isfile(a.base_tgz):
        raise Refused("OUT_DIFF must be absolute and BASE_TGZ must exist", 2)
    ws = abs_dir(os.path.dirname(a.out_diff), "OUT_DIFF directory")
    tmp = os.path.join(ws, "base-extract")
    extract(a.base_tgz, tmp)
    base_res, code = check(tmp)
    if code:
        emit(dict(base_res, error="baseline snapshot fails its own manifest"), 4)
    base = os.path.join(ws, "base-" + base_res["sha12"])
    if os.path.lexists(base):
        extract(a.base_tgz, base)  # replaces an earlier fw.py copy (refuses anything else)
        shutil.rmtree(tmp)
    else:
        os.rename(tmp, base)
    new_res, code = check(new)
    if code:
        emit(dict(new_res, error="NEW_DIR fails its manifest"), 4)
    cmd = ["diff", "-ruN", "-x", "package-lock.json", "-x", "SHA256SUMS", "-x", MARKER]
    for pat in sorted(EXCLUDED_DIRS) + list(EXCLUDED_NAMES):
        cmd += ["-x", pat]
    proc = subprocess.run(cmd + [os.path.relpath(base, ws), os.path.relpath(new, ws)], cwd=ws,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, errors="replace")
    if proc.returncode > 1:  # diff: 0 same, 1 different, 2 trouble
        raise Refused("diff failed rc=%d: %s" % (proc.returncode, proc.stderr[:300]), 4)
    lines = [("diff -ruN %s %s\n" % tuple(l.split()[-2:])) if l.startswith("diff -ruN ") else l
             for l in proc.stdout.splitlines(True)]  # drop the long -x list from each file header
    with open(a.out_diff, "w", encoding="utf-8") as f:
        f.writelines(lines)
    changed = [l.split()[-1].split("/", 1)[-1] for l in lines if l.startswith("diff -ruN ")]
    lb, ln = os.path.join(base, "package-lock.json"), os.path.join(new, "package-lock.json")
    lock = os.path.isfile(lb) != os.path.isfile(ln) or (os.path.isfile(lb) and sha256(lb) != sha256(ln))
    emit({"ok": True, "base_sha12": base_res["sha12"], "new_sha12": new_res["sha12"], "base_dir": base,
          "diff": a.out_diff, "diff_lines": proc.stdout.count("\n"), "changed_files": changed[:100],
          "lockfile_changed": lock})


def cmd_audit(a):
    root = abs_dir(a.dir, "DIR")
    secrets, env, stray, large, debug, forbidden = [], [], [], [], [], []
    info = {k: 0 for k, _ in DEBUG_INFO}
    manifest = rows(root)
    for _, rel in manifest:
        full, base = os.path.join(root, rel), rel.split("/")[-1]
        if any(is_env(part) for part in rel.split("/")):
            env.append(rel)
        elif excluded(rel):
            forbidden.append({"path": rel, "why": excluded(rel)})
        if base.lower() == ".ds_store" or base.startswith("._"):
            stray.append(rel)
        if not os.path.isfile(full):
            continue
        if os.path.getsize(full) > 5 * 1024 * 1024:
            large.append(rel)
            continue
        with open(full, "rb") as f:
            data = f.read()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        for bucket, pats in ((secrets, SECRETS), (debug, DEBUG_FAIL)):  # never print matched values
            bucket += [{"path": rel, "line": text.count("\n", 0, m.start()) + 1, "kind": k}
                       for k, p in pats for m in p.finditer(text)]
        for k, p in DEBUG_INFO:
            info[k] += len(p.findall(text))
    sensitive = []
    if a.project_dir and os.path.isdir(a.project_dir):
        sensitive = [n for n in sorted(os.listdir(a.project_dir)) if n.lower() == "n8n" or is_env(n)]
    emit({"verdict": "FAIL" if (secrets or env or stray or debug or forbidden) else "PASS", "sha12": sha12(root),
          "manifest_files": len(manifest), "secrets": secrets[:30], "env_in_manifest": env,
          "excluded_in_manifest": forbidden[:30],
          "stray_in_manifest": stray, "debug_blockers": debug[:30], "large_files": large, "info_counts": info,
          "sensitive_present_not_in_manifest": sensitive, "note": "values are never printed"})


def cmd_publish(a):
    root = abs_dir(a.project_dir, "PROJECT_DIR")
    res, code = check(root)
    if code:
        emit(res, code)
    slug = re.sub(r"[^a-z0-9-]+", "-", a.slug.lower()).strip("-") or "factory-delivery"
    s12, msg = res["sha12"], shlex.quote("%s: factory delivery %s" % (slug, res["sha12"]))
    add = ["sed -E 's/^[0-9a-f]{64}  //' .factory/SHA256SUMS | git --literal-pathspecs add --pathspec-from-file=-",
           "git add .factory/SHA256SUMS", "git diff --cached --name-only   # must list only manifest files"]
    cmds = ["# Optional; run these yourself only if you want to publish. They stage exactly the %d files of "
            "manifest %s." % (res["files"], s12), "cd %s" % shlex.quote(root)]
    sensitive = [n for n in sorted(os.listdir(root)) if n.lower() == "n8n" or is_env(n)]
    if sensitive:
        cmds.append("# never commit these; add them to .gitignore first: %s" % " ".join(sensitive))
    gitpath = os.path.join(root, ".git")
    if os.path.isfile(gitpath):
        # Linked worktree created by the intake pump: the job's branch already exists and is checked out here.
        # Read-only parse of the .git pointer file; base = the branch the main checkout is on.
        def head_branch(d):
            try:
                with open(os.path.join(d, "HEAD")) as f:
                    ref = f.read().strip()
            except OSError:
                return None
            return ref[len("ref: refs/heads/"):] if ref.startswith("ref: refs/heads/") else None
        with open(gitpath) as f:
            gd = f.read().strip()
        gd = gd[len("gitdir:"):].strip() if gd.startswith("gitdir:") else ""
        br = head_branch(gd) or "factory/" + slug
        base = head_branch(os.path.dirname(os.path.dirname(gd))) or "main"
        cmds += add + ["git commit -m " + msg, "git push -u origin " + br,
                       "gh pr create --base %s --head %s --title %s --body-file .factory/PLAN.md"
                       % (shlex.quote(base), shlex.quote(br), shlex.quote(slug)),
                       "# when done: git -C %s worktree remove %s" % (shlex.quote(os.path.dirname(os.path.dirname(os.path.dirname(gd)))), shlex.quote(root))]
    elif os.path.lexists(gitpath):
        base, head = "main", os.path.join(root, ".git", "HEAD")
        if os.path.isfile(head):
            with open(head) as f:
                ref = f.read().strip()
            base = ref[len("ref: refs/heads/"):] if ref.startswith("ref: refs/heads/") else base
        br = "factory/" + slug
        cmds += ["git switch -c " + br] + add + ["git commit -m " + msg, "git push -u origin " + br,
                 "gh pr create --base %s --head %s --title %s --body-file .factory/PLAN.md"
                 % (shlex.quote(base), br, shlex.quote(slug))]
    else:
        cmds += ["git init -b main"] + add + ["git commit -m " + msg,
                 "# optional: create a NEW private GitHub repository and push to it",
                 "gh repo create %s --private --source . --remote origin --push" % shlex.quote(slug)]
    emit({"ok": True, "sha12": s12, "publish_commands": cmds})


def cmd_clean(a):
    ws, removed = abs_dir(a.workspace, "WS"), []
    for name in sorted(os.listdir(ws)):
        path = os.path.join(ws, name)
        if name.startswith(("src-", "base-")) and os.path.isdir(path) and not os.path.islink(path) \
                and os.path.isfile(os.path.join(path, MARKER)):
            shutil.rmtree(path)
            removed.append(name)
    emit({"ok": True, "removed": removed, "kept": sorted(os.listdir(ws))[:50]})


def main():
    p = argparse.ArgumentParser(prog="fw.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    for name, fn, args, opts in (("manifest", cmd_manifest, ["project_dir"], []),
                                 ("check", cmd_check, ["project_dir"], ["--expect"]),
                                 ("snapshot", cmd_snapshot, ["project_dir", "workspace"], ["--expect"]),
                                 ("delta", cmd_delta, ["base_tgz", "new_dir", "out_diff"], []),
                                 ("audit", cmd_audit, ["dir"], ["--project-dir"]),
                                 ("publish-cmds", cmd_publish, ["project_dir", "slug"], []),
                                 ("clean", cmd_clean, ["workspace"], [])):
        s = sub.add_parser(name)
        for arg in args:
            s.add_argument(arg)
        for opt in opts:
            s.add_argument(opt)
        s.set_defaults(fn=fn)
    a = p.parse_args()
    if not getattr(a, "fn", None):
        p.print_help()
        sys.exit(2)
    try:
        a.fn(a)
    except Refused as exc:
        emit(dict(exc.extra, ok=False, error=str(exc)), exc.code)
    except SystemExit:
        raise
    except Exception as exc:  # report as JSON, never a raw traceback
        emit({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}, 2)


if __name__ == "__main__":
    main()
