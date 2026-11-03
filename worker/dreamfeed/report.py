"""`python -m dreamfeed report`: posts, likes and drops per persona, and recent runs."""
from . import db
from .config import Config


def main(argv: list[str]) -> None:
    cfg = Config()
    conn = db.connect(cfg.db_path)
    print(f"{'persona':16} {'in feed':>8} {'liked':>6} {'skipped':>8} {'dropped':>8}")
    for handle, feed, liked, skipped, dropped in conn.execute(
            "SELECT g.persona, sum(g.status = 'feed'), sum(f.action = 'like'), sum(f.action = 'skip'),"
            " sum(g.status = 'dropped') FROM generations g LEFT JOIN feedback f ON f.generation_id = g.id"
            " WHERE g.persona IS NOT NULL GROUP BY g.persona ORDER BY g.persona"):
        print(f"{handle:16} {feed or 0:8} {liked or 0:6} {skipped or 0:8} {dropped or 0:8}")

    print("\nDropped by the checks:")
    for reason, n in conn.execute(
            "SELECT substr(reason, 1, instr(reason || ':', ':') - 1), count(*) FROM generations"
            " WHERE status = 'dropped' GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {reason:20} {n}")

    print("\nRecent runs:")
    for night, status, stats in conn.execute("SELECT night, status, stats FROM runs ORDER BY started_at DESC LIMIT 8"):
        print(f"  {night:22} {status:9} {stats or ''}")
