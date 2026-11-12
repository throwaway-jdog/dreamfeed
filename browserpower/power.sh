#!/bin/sh
# Starts and stops dreamfeed's server browser (the browser service) for the web app, which has
# no say over Docker: it only leaves a file named start or stop in the request folder, and
# systemd runs this (installed root-owned by install.sh) with a fixed action:
#   start   start the container
#   stop    stop it, unless someone's watching it
#   idle    (each minute) stop it once no one's watched it for IDLE seconds
# Whatever the files say is ignored. Each run writes status.json there: {"running", "viewers", "at"}.
set -eu
ACTION=${1:?start, stop or idle}
NAME=${BROWSER_CONTAINER:?}
DIR=${BROWSER_POWER_DIR:?}
IDLE=${BROWSER_IDLE:-600}
SCREEN=16A8                       # 5800, its page's port, as /proc/net/tcp writes it

running() { [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ]; }
viewers() {                       # open connections to its page: someone watching it
  docker exec "$NAME" cat /proc/net/tcp /proc/net/tcp6 2>/dev/null |
    awk -v p=":$SCREEN" 'substr($2, length($2) - 4) == p && $4 == "01" { n++ } END { print n + 0 }'
}
status() {
  if running; then on=true; v=$(viewers); else on=false; v=0; fi
  printf '{"running": %s, "viewers": %s, "at": %s}\n' "$on" "$v" "$(date +%s)" > "$DIR/.status.json"
  mv "$DIR/.status.json" "$DIR/status.json"
}

case $ACTION in
  start)
    rm -f "$DIR/start"
    running || docker start "$NAME" >/dev/null
    touch "$DIR/last-used" ;;
  stop)
    rm -f "$DIR/stop"
    if running && [ "$(viewers)" -eq 0 ]; then docker stop -t 20 "$NAME" >/dev/null; fi ;;
  idle)
    if running; then
      if [ "$(viewers)" -gt 0 ] || [ ! -e "$DIR/last-used" ]; then touch "$DIR/last-used"
      elif [ $(( $(date +%s) - $(stat -c %Y "$DIR/last-used") )) -ge "$IDLE" ]; then docker stop -t 20 "$NAME" >/dev/null
      fi
    fi ;;
  *) echo "start, stop or idle" >&2; exit 2 ;;
esac
status
