#!/usr/bin/env bash
# Installs Wallqueue for the current user. Safe to run again after an update.
set -euo pipefail

project="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="$HOME/.local/bin"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

mkdir -p "$bin_dir" "$unit_dir" "$app_dir"

cat > "$bin_dir/wallqueue" <<EOF
#!/bin/sh
PYTHONPATH="$project" exec /usr/bin/python3 -m wallqueue "\$@"
EOF
chmod +x "$bin_dir/wallqueue"

install -m 644 "$project/data/wallqueue.service" "$project/data/wallqueue.timer" "$unit_dir/"
install -m 644 "$project/data/wallqueue.desktop" "$app_dir/"

systemctl --user daemon-reload
systemctl --user enable --now wallqueue.timer

echo "Wallqueue installed. Open it from the menu or run: wallqueue gui"
