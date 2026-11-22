#!/bin/sh
# Unity gate for a factory worktree: compile + EditMode (or PlayMode) tests through Unity's official CLI.
# usage: unity_gate.sh <worktree-root> [EditMode|PlayMode] [project-subdir]   (the project is auto-detected when the subdir is omitted)
# - One Unity run at a time on this Mac (lock dir), the editor is heavy.
# - Seeds the worktree's Library/ from the main checkout with an APFS clone (instant, no extra disk) so the
#   first run is an incremental import, not a from-scratch import of a ~20 GB cache.
# Exit 0 = compiled and all tests passed. Prints one summary line; log and NUnit report are written to
# ~/.hermes/state/factory/unity-runs/<worktree name>/ (outside the worktree, so workers have no temp files to delete).
set -u
WT=${1:?worktree root}; MODE=${2:-EditMode}; SUB=${3:-}
WT=$(cd "$WT" && pwd)  # absolute path: callers pass "."
UNITY="$HOME/.unity/bin/unity"
if [ -z "$SUB" ]; then
  # No project subdirectory given: find the Unity project (the directory that holds ProjectSettings/ProjectVersion.txt) at the worktree root or up to two levels below.
  # Never a default tied to one game, never inside Library, Packages, build output, VCS data or other worktrees.
  FOUND=$(find "$WT" -maxdepth 4 -name ProjectVersion.txt -path '*/ProjectSettings/ProjectVersion.txt' \
            -not -path '*/Library/*' -not -path '*/Packages/*' -not -path '*/Temp/*' -not -path '*/.git/*' -not -path '*/.worktrees/*' -not -path '*/node_modules/*' 2>/dev/null \
          | sed -e 's|/ProjectSettings/ProjectVersion.txt$||' | sort)
  COUNT=$(printf '%s\n' "$FOUND" | grep -c . || true)
  if [ "$COUNT" -eq 0 ]; then echo "UNITY_GATE FAIL: no Unity project (ProjectSettings/ProjectVersion.txt) found under $WT; pass the project subdirectory as the third argument"; exit 2; fi
  if [ "$COUNT" -gt 1 ]; then echo "UNITY_GATE FAIL: more than one Unity project under $WT, pass the project subdirectory as the third argument: $(printf '%s' "$FOUND" | tr '\n' ' ')"; exit 2; fi
  SUB=${FOUND#"$WT"}; SUB=${SUB#/}; [ -n "$SUB" ] || SUB=.
fi
PROJ="$WT/$SUB"
[ -d "$PROJ/Assets" ] || { echo "UNITY_GATE FAIL: no Unity project at $PROJ"; exit 2; }
[ -x "$UNITY" ] || { echo "UNITY_GATE FAIL: unity CLI not found at $UNITY"; exit 2; }
LOCK="$HOME/.hermes/state/factory/unity.lock"; mkdir -p "$(dirname "$LOCK")"
i=0
while ! mkdir "$LOCK" 2>/dev/null; do
  if [ -f "$LOCK/pid" ] && ! kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  i=$((i+1)); [ $i -gt 360 ] && { echo "UNITY_GATE FAIL: waited 60 min for the Unity lock"; exit 3; }
  sleep 10
done
echo $$ > "$LOCK/pid"; trap 'rm -rf "$LOCK"' EXIT INT TERM
if [ ! -d "$PROJ/Library" ]; then
  COMMON=$(git -C "$WT" rev-parse --git-common-dir 2>/dev/null); MAIN=$(cd "$WT" && cd "$COMMON/.." 2>/dev/null && pwd)
  # Only clone a Library that belongs to a real Unity project (Assets + ProjectSettings next to it). Never $HOME/Library:
  # a scratch copy outside any repo resolves MAIN to $HOME, and that Library holds Keychains and app data.
  if [ -d "$MAIN/$SUB/Library" ] && [ -d "$MAIN/$SUB/Assets" ] && [ -d "$MAIN/$SUB/ProjectSettings" ] && [ "$MAIN" != "$HOME" ]; then
    cp -cR "$MAIN/$SUB/Library" "$PROJ/Library"
  else
    mkdir -p "$PROJ/Library"
  fi
fi
# A Library cloned from another checkout carries that checkout's Library/EditorInstance.json (the running Editor's pid and path); Unity's CLI reads it and reports this project as "already open in
# a running Editor". Keep the marker only when its process really has THIS project open.
if [ -f "$PROJ/Library/EditorInstance.json" ]; then
  EPID=$(sed -n 's/.*"process_id" *: *\([0-9][0-9]*\).*/\1/p' "$PROJ/Library/EditorInstance.json" | head -1)
  ECMD=$([ -n "$EPID" ] && ps -p "$EPID" -o command= 2>/dev/null || true)
  PLOG=$(cd "$PROJ" && pwd); PPHYS=$(cd "$PROJ" && pwd -P)    # the Editor's command line may name the project by either spelling
  case "$ECMD" in *"$PLOG"*|*"$PPHYS"*) ;; *) rm -f "$PROJ/Library/EditorInstance.json" ;; esac
fi
OUT="$HOME/.hermes/state/factory/unity-runs/$(basename "$WT")"; mkdir -p "$OUT"; XML="$OUT/unity-$(echo "$MODE" | tr 'A-Z' 'a-z').xml"; rm -f "$XML"  # outside the worktree: nothing to clean up in the job folder
# Known-hanging test classes (one name per line) are excluded; see state/factory/unity_exclude.txt.
EXCL="$HOME/.hermes/state/factory/unity_exclude.txt"; FILTER=""
[ -f "$EXCL" ] && FILTER=$(grep -v '^#' "$EXCL" | grep -v '^$' | sed 's/^/!/' | tr '\n' ';' | sed 's/;$//')
set -- "$UNITY" test "$PROJ" --mode "$MODE" --output "$XML" --timeout "${UNITY_GATE_TIMEOUT:-900}" --non-interactive --no-banner
[ -n "$FILTER" ] && set -- "$@" --filter "$FILTER"
"$@" > "$OUT/unity-test.log" 2>&1
RC=$?
# Unity's Addressables step deletes this tracked file on every run; put it back so the worktree only holds the real change.
for f in Assets/AddressableAssetsData/link.xml Assets/AddressableAssetsData/link.xml.meta; do
  [ -e "$PROJ/$f" ] || git -C "$WT" restore --quiet -- "$SUB/$f" 2>/dev/null
done
if [ -f "$XML" ]; then
  SUM=$(grep -o '<test-run [^>]*' "$XML" | head -1 | grep -oE '(result|total|passed|failed|skipped)="[^"]*"' | tr '\n' ' ')
else
  SUM="no report written (compile error or editor failed to start); see $OUT/unity-test.log"
fi
# Exit 8 = some tests failed. Pass when every failure is already in the baseline (tests broken on main before the change).
if [ $RC -eq 8 ] && [ -f "$XML" ]; then
  NEW=$(python3 - "$XML" "$HOME/.hermes/state/factory/unity_baseline.txt" <<'PY'
import re, sys
x = open(sys.argv[1]).read()
base = {l.strip() for l in open(sys.argv[2]) if l.strip() and not l.startswith("#")} if len(sys.argv) > 2 else set()
fails = re.findall(r'<test-case [^>]*?fullname="([^"]*)"[^>]*?result="Failed"', x)
print("\n".join(f for f in fails if f not in base))
PY
)
  if [ -z "$NEW" ]; then echo "UNITY_GATE PASS $MODE (only known baseline failures): $SUM"; exit 0; fi
  echo "UNITY_GATE FAIL $MODE: new failing tests:"; echo "$NEW"; exit 8
fi
# A pass needs proof that tests ran: Unity exiting 0 without writing a test report (an editor that never started, a project with no tests assembly) is a FAIL, never a green gate.
if [ $RC -eq 0 ] && [ ! -f "$XML" ]; then echo "UNITY_GATE FAIL $MODE: Unity exited 0 but wrote no test report, so no test ran: $SUM"; tail -n 15 "$OUT/unity-test.log" 2>/dev/null; exit 4; fi
if [ $RC -eq 0 ]; then echo "UNITY_GATE PASS $MODE: $SUM"; else echo "UNITY_GATE FAIL $MODE (exit $RC): $SUM"; tail -n 15 "$OUT/unity-test.log"; fi
exit $RC
