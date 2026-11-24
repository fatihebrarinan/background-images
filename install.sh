#!/usr/bin/env bash
# Installs Wallqueue for the current user. Safe to run again after an update.
set -euo pipefail

project="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="$HOME/.local/bin"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
share_dir="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$share_dir/applications"
icon_dir="$share_dir/icons/hicolor"
action_dir="$share_dir/nemo/actions"

mkdir -p "$bin_dir" "$unit_dir" "$app_dir" "$icon_dir/scalable/apps" "$icon_dir/symbolic/apps" \
    "$action_dir"

cat > "$bin_dir/wallqueue" <<EOF
#!/bin/sh
PYTHONPATH="$project" exec /usr/bin/python3 -m wallqueue "\$@"
EOF
chmod +x "$bin_dir/wallqueue"

install -m 644 "$project/data/wallqueue.service" "$project/data/wallqueue.timer" "$unit_dir/"
install -m 644 "$project/data/wallqueue.desktop" "$app_dir/"
install -m 644 "$project/data/icons/wallqueue.svg" "$icon_dir/scalable/apps/"
install -m 644 "$project/data/icons/wallqueue-symbolic.svg" "$icon_dir/symbolic/apps/"
touch "$icon_dir"  # Tells running apps the icon theme changed.

# "Sonraki duvar kâğıdı" in the desktop's right-click menu. Nemo may not have
# ~/.local/bin on its PATH, so the action calls the launcher by its full path.
sed "s|^Exec=wallqueue |Exec=$bin_dir/wallqueue |" "$project/data/wallqueue-next.nemo_action" \
    > "$action_dir/wallqueue-next.nemo_action"

systemctl --user daemon-reload
systemctl --user enable --now wallqueue.timer

echo "Wallqueue installed. Open it from the menu or run: wallqueue gui"
