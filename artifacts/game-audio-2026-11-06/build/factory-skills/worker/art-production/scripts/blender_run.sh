#!/bin/sh
# Run blender_model.py in headless Blender and print its one-line JSON result.
# usage: blender_run.sh cleanup <in.glb> <out.glb> --height <m> [--origin bottom_center|center]
#        blender_run.sh blockout <concept.png> <out.glb> --height <m> --spec <parts.json> [--palette <file.gpl>] [--origin ...]
# exit: 0 done, 1 failed or timed out, 2 usage, 4 Blender not found
# env: BLENDER (executable), BLENDER_TIMEOUT seconds (default 300)
set -u
here=$(cd "$(dirname "$0")" && pwd)
case "${1:-}" in cleanup|blockout) ;; *) echo "usage: blender_run.sh cleanup|blockout ..." >&2; exit 2 ;; esac
if [ -n "${BLENDER:-}" ]; then
  blender=$BLENDER
elif command -v blender >/dev/null 2>&1; then
  blender=$(command -v blender)
else
  blender=/Applications/Blender.app/Contents/MacOS/Blender
fi
[ -x "$blender" ] || { echo "blender_run: Blender not found ($blender); set BLENDER" >&2; exit 4; }
limit=${BLENDER_TIMEOUT:-300}
log=$(mktemp "${TMPDIR:-/tmp}/blender-run.XXXXXX") || exit 1
trap 'rm -f "$log"' EXIT
"$blender" -b --factory-startup --python-exit-code 1 -P "$here/blender_model.py" -- "$@" > "$log" 2>&1 &
child=$!
# Watchdog: polls once a second and stops the child after $limit seconds; it ends by itself with the child.
( elapsed=0
  while kill -0 "$child" 2>/dev/null; do
    if [ "$elapsed" -ge "$limit" ]; then
      kill -TERM "$child" 2>/dev/null; sleep 5; kill -KILL "$child" 2>/dev/null; break
    fi
    sleep 1; elapsed=$((elapsed + 1))
  done ) &
watcher=$!
wait "$child"
status=$?
wait "$watcher"
if [ "$status" -ge 128 ]; then
  echo "blender_run: Blender timed out after ${limit}s" >&2
  exit 1
fi
if [ "$status" -ne 0 ] || ! grep -q '^BLENDER_MODEL ' "$log"; then
  grep '^BLENDER_MODEL_ERROR ' "$log" >&2 || tail -n 20 "$log" >&2
  exit 1
fi
grep '^BLENDER_MODEL ' "$log" | tail -n 1 | sed 's/^BLENDER_MODEL //'
