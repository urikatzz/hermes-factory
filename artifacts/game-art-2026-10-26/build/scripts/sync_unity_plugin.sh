#!/bin/sh
# Refresh the Hermes copy of Unity's official Claude Code plugin skills (workers load them on demand).
# Run after `claude plugin update unity@claude-plugins-official`.
set -e
SRC=$(ls -d "$HOME"/.claude/plugins/cache/claude-plugins-official/unity/* | sort -V | tail -1)
DST="$HOME/.hermes/factory-skills/worker/unity-plugin"
mkdir -p "$DST"
cp -R "$SRC/skills/." "$DST/"
cp "$SRC/LICENSE.md" "$DST/"
echo "unity@claude-plugins-official $(basename "$SRC"); copied $(date +%F)" > "$DST/VERSION.txt"
echo "synced $(basename "$SRC") -> $DST"
