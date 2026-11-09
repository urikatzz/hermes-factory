#!/bin/sh
# Standalone art review: copy the bible and art into a private workspace, then run the art-reviewer once.
# usage: art_check.sh <repo> [path...]   (paths relative to repo; default: whole repo)
set -eu
usage() { echo "usage: art_check.sh <repo> [path...]" >&2; exit 2; }
[ $# -ge 1 ] && [ -d "$1" ] || usage
repo=$(cd "$1" && pwd -P)
shift
here=$(cd "$(dirname "$0")" && pwd)
inside() {
  case "$1" in "$repo"|"$repo"/*) ;; *) echo "art_check: $2 resolves outside $repo" >&2; exit 2 ;; esac
}
for path in "$@"; do
  case "$path" in
    /*|..|../*|*/..|*/../*) echo "art_check: $path must be relative to the repo, without .." >&2; exit 2 ;;
  esac
  [ -e "$repo/$path" ] || { echo "art_check: $path does not exist in $repo" >&2; exit 2; }
  if [ -d "$repo/$path" ]; then
    inside "$(cd "$repo/$path" && pwd -P)" "$path"
  else
    dir=$(cd "$(dirname "$repo/$path")" && pwd -P)
    inside "$dir" "$path"
    [ ! -L "$repo/$path" ] || { echo "art_check: $path is a symlink" >&2; exit 2; }
  fi
done
out=${ART_CHECK_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/art-check.XXXXXX")}
mkdir -p "$out/src"
chmod 700 "$out"
cd "$repo"
if [ -d art/style ]; then rsync -a --relative --no-links art/style "$out/src/"; fi
[ $# -gt 0 ] || set -- .
for path in "$@"; do set -- "$@" "./$path"; shift; done
rsync -a --relative --no-links --exclude '.?*' --exclude node_modules --exclude Library \
  --exclude Temp --exclude Logs "$@" "$out/src/"
cat > "$out/query.txt" <<EOF
MODE=standalone
SRC_DIR=$out/src
OUT_DIR=$out
LINT=python3 $here/art_lint.py
Review the game art in SRC_DIR against SRC_DIR/art/style. Follow the art-review skill, standalone mode.
EOF
status=0
hermes -p "${ART_REVIEWER_PROFILE:-art-reviewer}" chat --oneshot -Q -s art-review --in "$out" \
  --query-file "$out/query.txt" || status=$?
echo "REPORT=$out/report.md"
exit "$status"
