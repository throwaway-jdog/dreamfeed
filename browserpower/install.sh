#!/bin/sh
# Installs what starts and stops dreamfeed's server browser (power.sh), for this checkout:
#   sudo browserpower/install.sh
# The script goes to /usr/local/lib/dreamfeed-browser (root's: only root can change what runs),
# with systemd units that run it with a fixed action when the web app leaves a request file in
# <this folder>/data/browser-power, and each minute to stop it when it's not in use. They run as
# this checkout's owner (who can use Docker). Run it again after changing power.sh.
# sudo browserpower/install.sh --remove takes it all away again.
set -eu
[ "$(id -u)" = 0 ] || { echo "run it with sudo" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")/.." && pwd)
DIR="$HERE/data/browser-power"
OWNER=$(stat -c %U "$HERE")
LIB=/usr/local/lib/dreamfeed-browser
UNITS=/etc/systemd/system
ENV="Environment=BROWSER_CONTAINER=dreamfeed-browser BROWSER_POWER_DIR=$DIR BROWSER_IDLE=600"

if [ "${1:-}" = --remove ]; then
  systemctl disable --now dreamfeed-browser-start.path dreamfeed-browser-stop.path dreamfeed-browser-idle.timer 2>/dev/null || true
  rm -f $UNITS/dreamfeed-browser-*.service $UNITS/dreamfeed-browser-*.path $UNITS/dreamfeed-browser-idle.timer
  rm -rf "$LIB"; systemctl daemon-reload; echo removed; exit 0
fi
id -nG "$OWNER" | tr ' ' '\n' | grep -qx docker || { echo "$OWNER isn't in the docker group" >&2; exit 1; }

install -d -o root -g root -m 755 "$LIB"
install -o root -g root -m 755 "$HERE/browserpower/power.sh" "$LIB/power.sh"
install -d -o "$OWNER" -g "$(stat -c %G "$HERE")" -m 755 "$DIR"

for action in start stop idle; do
  cat > "$UNITS/dreamfeed-browser-$action.service" <<UNIT
[Unit]
Description=dreamfeed's server browser: $action
[Service]
Type=oneshot
User=$OWNER
$ENV
ExecStart=$LIB/power.sh $action
UNIT
done
for action in start stop; do
  cat > "$UNITS/dreamfeed-browser-$action.path" <<UNIT
[Unit]
Description=dreamfeed's server browser: $action when asked
[Path]
PathExists=$DIR/$action
Unit=dreamfeed-browser-$action.service
[Install]
WantedBy=multi-user.target
UNIT
done
cat > "$UNITS/dreamfeed-browser-idle.timer" <<UNIT
[Unit]
Description=dreamfeed's server browser: stopped when not in use
[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now dreamfeed-browser-start.path dreamfeed-browser-stop.path dreamfeed-browser-idle.timer
echo "installed: requests in $DIR, run as $OWNER"
