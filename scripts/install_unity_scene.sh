#!/bin/sh
# Install the unity-scene worker skill (skill text, factory_unity package with the engine editor script, capture CLI).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
dest=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}/unity-scene
if [ -e "$dest" ]; then
  echo "install_unity_scene: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts"
rsync -a --exclude __pycache__ --exclude install "$root/factory_unity/" "$dest/factory_unity/"
# the capture CLI imports factory_unity from its parent directory
cp "$root/scripts/unity_scene_capture.py" "$dest/scripts/"
chmod +x "$dest/scripts/unity_scene_capture.py"
cap=$(printf '%s' "$dest/scripts/unity_scene_capture.py" | sed 's/[|&\\]/\\&/g')
sed -e "s|python3 \${HERMES_SKILL_DIR}/scripts/unity_scene_capture.py|python3 $cap|g" "$root/factory_unity/install/SKILL.md" > "$dest/SKILL.md"
echo "installed $dest"
