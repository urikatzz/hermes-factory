#!/bin/sh
# Generate one PNG with Codex's built-in image_gen tool through non-interactive `codex exec`.
# usage: codex_image.sh <prompt-file> <out.png>
# exit: 0 out.png written and decodes, 1 no image / bad image / timeout, 2 usage, 4 codex CLI not found
# env: CODEX_BIN (default codex), CODEX_HOME (default $HERMES_REAL_HOME/.codex, else $HOME/.codex),
#      CODEX_IMAGE_TIMEOUT seconds (default 300), CODEX_IMAGE_MODEL (optional -m)
set -u
usage() { echo "codex_image: $1" >&2; echo "usage: codex_image.sh <prompt-file> <out.png>   (the prompt file must already exist: write the prompt text to it first; out.png must end in .png)" >&2; exit 2; }
[ $# -eq 2 ] || usage "expected exactly 2 arguments, got $#"
[ -f "$1" ] || usage "prompt file not found: $1 (create it with the prompt text before calling this script)"
case "$2" in *.png) ;; *) usage "output must end in .png: $2" ;; esac
here=$(cd "$(dirname "$0")" && pwd)
out=$2
codex=${CODEX_BIN:-codex}
command -v "$codex" >/dev/null 2>&1 || { echo "codex_image: codex CLI not found ($codex)" >&2; exit 4; }
CODEX_HOME=${CODEX_HOME:-${HERMES_REAL_HOME:-$HOME}/.codex}
export CODEX_HOME
limit=${CODEX_IMAGE_TIMEOUT:-300}
work=$(mktemp -d "${TMPDIR:-/tmp}/codex-image.XXXXXX") || exit 1
trap 'rm -rf "$work"' EXIT
gen="$CODEX_HOME/generated_images"
list_pngs() { [ -d "$gen" ] && find "$gen" -type f -name '*.png' 2>/dev/null | sort; }
list_pngs > "$work/before.txt"
request="Use your built-in image_gen tool exactly once to create the image described below. Do not write code, do not use the imagegen CLI fallback and do not change any file except ./image.png.
When the image is generated, copy the generated PNG file to ./image.png in the current directory, then reply DONE.

$(cat "$1")"
set -- exec --skip-git-repo-check --ephemeral --enable image_generation -s workspace-write -C "$work" \
  --color never -o "$work/last-message.txt"
[ -z "${CODEX_IMAGE_MODEL:-}" ] || set -- "$@" -m "$CODEX_IMAGE_MODEL"
"$codex" "$@" "$request" > "$work/codex.log" 2>&1 &
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
  echo "codex_image: codex timed out after ${limit}s" >&2
  tail -n 20 "$work/codex.log" >&2
  exit 1
fi
image="$work/image.png"
# Fallback when codex did not copy ./image.png: generated_images is shared by every run, so take a file from it
# only when exactly one PNG appeared there during this run AND this run's codex output names it.
if [ ! -s "$image" ]; then
  list_pngs > "$work/after.txt"
  comm -13 "$work/before.txt" "$work/after.txt" > "$work/new.txt"
  count=$(wc -l < "$work/new.txt" | tr -d ' ')
  if [ "$count" -gt 1 ]; then
    echo "codex_image: $count new images in $gen during this run (concurrent runs?); not guessing which is ours" >&2
    exit 1
  fi
  if [ "$count" -eq 1 ]; then
    candidate=$(cat "$work/new.txt")
    if cat "$work/codex.log" "$work/last-message.txt" 2>/dev/null | grep -qF "${candidate#"$gen"/}"; then
      image=$candidate
    else
      echo "codex_image: new image $candidate is not referenced in this run's codex output; not taking it" >&2
      exit 1
    fi
  fi
fi
if [ ! -s "$image" ]; then
  echo "codex_image: codex exited $status without an image" >&2
  tail -n 20 "$work/codex.log" >&2
  exit 1
fi
python3 "$here/check_png.py" "$image" > /dev/null || { echo "codex_image: the generated file is not a decodable PNG" >&2; exit 1; }
mkdir -p "$(dirname "$out")" || exit 1
cp "$image" "$out.part" && mv "$out.part" "$out" || exit 1
python3 "$here/check_png.py" "$out"
