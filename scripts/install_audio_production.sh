#!/bin/sh
# Install the audio-production worker skill: skill text, audio profile souls, packages and scripts.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
skills=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}
dest=$skills/audio-production
if [ -e "$dest" ]; then
  echo "install_audio_production: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts" "$dest/souls" "$dest/factory_art"
rsync -a --exclude __pycache__ --exclude install "$root/factory_audio/" "$dest/factory_audio/"
rsync -a --exclude __pycache__ --exclude install "$root/audio_production/" "$dest/audio_production/"
cp "$root/factory_art/__init__.py" "$root/factory_art/findings.py" "$dest/factory_art/"
for name in sfx_synth.py music_process.py; do cp "$root/scripts/$name" "$dest/scripts/$name"; done
chmod +x "$dest"/scripts/*
esc() { printf '%s' "$1" | sed 's/[|&\\]/\\&/g'; }
fill() {
  sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" -e "s|\${AUDIO_REVIEW_DIR}|$(esc "$skills/audio-review")|g" "$1" > "$2"
}
fill "$root/audio_production/install/SKILL.md" "$dest/SKILL.md"
fill "$root/audio_production/install/audio-director.SOUL.md" "$dest/souls/audio-director.SOUL.md"
fill "$root/audio_production/install/sound-designer.SOUL.md" "$dest/souls/sound-designer.SOUL.md"
echo "installed $dest"
