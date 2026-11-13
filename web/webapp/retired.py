"""What's left of the personas and their generated posts, retired with the generation pipeline:
the header's summary (now just how many of your rooms are live), and empty answers where the iOS
app still asks (its persona feed, personas, styles, the dashboard's runs) so it shows nothing
there rather than failing, until it stops asking. Nothing is made or trained any more.
"""
import sqlite3

from .common import db


def summary() -> dict:
    """{"live": rooms you follow that are live; "liked", "unrated": 0 (the persona posts are gone)}."""
    out = {"unrated": 0, "liked": 0, "last_run": None, "live": 0}
    try:
        with db() as conn:
            out["live"] = conn.execute("SELECT count(*) FROM follows WHERE live = 1").fetchone()[0]
    except sqlite3.OperationalError:     # (follows: the follow service hasn't started yet)
        pass
    return out


def personas() -> dict:
    return {"personas": []}


def persona_config() -> dict:
    return {"personas": [], "styles": [], "voices": {}}


def styles() -> dict:
    return {"styles": []}


def dashboard() -> dict:
    return {"runs": [], "jobs": [], "liked": 0, "window": ""}


def draft_status(job: int) -> dict:
    return {"status": "gone", "error": "personas aren't made any more"}
