"""`python -m dreamfeed report [--top N] [--dropped]`: what the taste profile looks like."""
import argparse

from . import db, media
from .config import Config


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="dreamfeed report")
    ap.add_argument("--top", type=int, default=25, help="tags to show per medium")
    ap.add_argument("--dropped", action="store_true", help="list dropped tweet IDs")
    args = ap.parse_args(argv)

    cfg = Config()
    conn = db.connect(cfg.db_path)
    total = conn.execute("SELECT count(*) FROM bookmarks").fetchone()[0]
    waiting = len(media.ready_files(cfg.bookmarks_dir, min_age=0))
    print(f"Bookmarks in profile: {total}   waiting to be tagged: {waiting}")

    kinds = dict(conn.execute("SELECT kind, count(*) FROM bookmarks GROUP BY kind").fetchall())
    print(f"  images {kinds.get('image', 0)}, videos {kinds.get('video', 0)}")

    print("\nBy medium:")
    mediums = conn.execute("SELECT medium, count(*) FROM bookmarks GROUP BY medium ORDER BY 2 DESC").fetchall()
    for medium, n in mediums:
        print(f"  {medium:6} {n:6}  {100 * n / max(total, 1):5.1f}%")

    print("\nDropped:")
    for reason, medium, n in conn.execute(
            "SELECT reason, coalesce(medium, '?'), count(*) FROM dropped GROUP BY 1, 2 ORDER BY 3 DESC"):
        print(f"  {reason:12} {medium:6} {n}")

    for medium, n in mediums:
        print(f"\nTop tags, {medium} (share of its {n} bookmarks):")
        rows = conn.execute(
            "SELECT t.tag, count(*) FROM bookmark_tags t JOIN bookmarks b ON b.id = t.bookmark_id"
            " WHERE b.medium = ? GROUP BY t.tag ORDER BY 2 DESC LIMIT ?", (medium, args.top)).fetchall()
        for tag, c in rows:
            print(f"  {100 * c / n:5.1f}%  {tag}")

    if args.dropped:
        print("\nDropped tweets (check them on X: https://x.com/i/status/<id>):")
        for tid, reason, medium, detail, at in conn.execute(
                "SELECT tweet_id, reason, coalesce(medium, '?'), detail, at FROM dropped ORDER BY at DESC"):
            print(f"  {at}  {tid}  {reason}  {medium}  {detail}")
