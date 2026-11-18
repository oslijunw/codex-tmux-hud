#!/bin/sh
set -eu
cd "$(dirname "$0")"
prefix=${PREFIX:-"$HOME/.local"}
for tool in python3 tmux codex; do
    command -v "$tool" >/dev/null || { echo "Missing dependency: $tool" >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo 'Python 3.9+ required' >&2; exit 1; }
dest="$prefix/share/codex-tmux-hud"
mkdir -p "$dest/collector/web" "$prefix/bin"
install -m 755 oai "$dest/oai"
install -m 644 collector/*.py collector/LICENSE "$dest/collector/"
install -m 644 collector/web/index.html "$dest/collector/web/"
install -m 644 LICENSE "$dest/LICENSE"
ln -sf "$dest/oai" "$prefix/bin/oai"
echo "Installed $prefix/bin/oai"
