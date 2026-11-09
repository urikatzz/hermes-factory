#!/bin/sh
# Install the art-review worker skill (skill text, profile soul, factory_art package, scripts).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
dest=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}/art-review
if [ -e "$dest" ]; then
  echo "install_art_review: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts"
cp "$root/factory_art/install/SOUL.md" "$dest/"
rsync -a --exclude __pycache__ --exclude install "$root/factory_art/" "$dest/factory_art/"
cp "$root/scripts/art_lint.py" "$root/scripts/art_check.sh" "$dest/scripts/"
chmod +x "$dest/scripts/art_lint.py" "$dest/scripts/art_check.sh"
lint=$(printf '%s' "$dest/scripts/art_lint.py" | sed 's/[|&\\]/\\&/g')
sed "s|python3 \${HERMES_SKILL_DIR}/scripts/art_lint.py|python3 $lint|g" \
  "$root/factory_art/install/SKILL.md" > "$dest/SKILL.md"
echo "installed $dest"
