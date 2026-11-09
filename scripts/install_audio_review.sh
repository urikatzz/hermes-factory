#!/bin/sh
# Install the audio-review worker skill: skill text, reviewer soul, factory_audio + factory_art.findings, audio_lint.py.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
skills=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}
dest=$skills/audio-review
if [ -e "$dest" ]; then
  echo "install_audio_review: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts" "$dest/factory_art"
rsync -a --exclude __pycache__ --exclude install "$root/factory_audio/" "$dest/factory_audio/"
cp "$root/factory_art/__init__.py" "$root/factory_art/findings.py" "$dest/factory_art/"
cp "$root/scripts/audio_lint.py" "$dest/scripts/audio_lint.py"
chmod +x "$dest/scripts/audio_lint.py"
esc() { printf '%s' "$1" | sed 's/[|&\\]/\\&/g'; }
sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" "$root/factory_audio/install/SKILL.md" > "$dest/SKILL.md"
sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" "$root/factory_audio/install/SOUL.md" > "$dest/SOUL.md"
echo "installed $dest"
