#!/bin/sh
# Downloads new X bookmarks every SYNC_INTERVAL_HOURS. The archive remembers what was
# already fetched, so files the worker deletes after tagging aren't downloaded again.
set -u
: "${SYNC_INTERVAL_HOURS:?set SYNC_INTERVAL_HOURS}"
[ -r /config/cookies.txt ] || { echo "sync: /config/cookies.txt missing or unreadable (X_COOKIES_FILE)"; exit 1; }

while true; do
    echo "sync: $(date -Is) fetching bookmarks"
    gallery-dl --config /app/gallery-dl.conf --cookies /config/cookies.txt \
        "https://x.com/i/bookmarks" \
        || echo "sync: gallery-dl failed (expired cookies or X changed; try updating GALLERY_DL_VERSION)"
    echo "sync: $(date -Is) done, next run in ${SYNC_INTERVAL_HOURS}h"
    sleep "$((SYNC_INTERVAL_HOURS * 3600))"
done
