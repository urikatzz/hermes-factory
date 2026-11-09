#!/bin/sh
# Install the art-production worker skill: skill text, art profile souls, factory_art + art_production, scripts.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
skills=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}
dest=$skills/art-production
if [ -e "$dest" ]; then
  echo "install_art_production: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts" "$dest/souls"
rsync -a --exclude __pycache__ --exclude install "$root/factory_art/" "$dest/factory_art/"
rsync -a --exclude __pycache__ --exclude install "$root/art_production/" "$dest/art_production/"
for name in sprite_fit.py check_png.py tripo_model.py blender_model.py codex_image.sh blender_run.sh; do
  cp "$root/scripts/$name" "$dest/scripts/$name"
done
chmod +x "$dest"/scripts/*
esc() { printf '%s' "$1" | sed 's/[|&\\]/\\&/g'; }
fill() {
  sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" -e "s|\${ART_REVIEW_DIR}|$(esc "$skills/art-review")|g" "$1" > "$2"
}
fill "$root/art_production/install/SKILL.md" "$dest/SKILL.md"
fill "$root/art_production/install/art-director.SOUL.md" "$dest/souls/art-director.SOUL.md"
fill "$root/art_production/install/artist.SOUL.md" "$dest/souls/artist.SOUL.md"
echo "installed $dest"
