"""Tag phase: sort, tag and check every downloaded bookmark, then delete the file."""
import io
import json
import time
import urllib.request
from pathlib import Path

from . import db, media, safety
from .config import Config

COPY_DIR = Path("/copy")   # permanent bookmark copy (BOOKMARK_COPY_DIR)


def pick_medium(a, cfg: Config) -> str:
    medium = max(a.medium_probs, key=a.medium_probs.get)
    furry = max(a.general.get(t, 0.0) for t in safety.FURRY_TAGS)
    if medium == "anime" and furry >= cfg.furry_threshold:
        medium = "furry"
    return medium


def face_ages(frames, cfg: Config) -> list[float]:
    """MiVOLO estimates for clearly visible faces in any frame. Body-only estimates are
    too unreliable to use (they swing by decades between frames of one video)."""
    ages = []
    for frame in frames:
        buf = io.BytesIO()
        frame.save(buf, format="PNG")
        req = urllib.request.Request(f"{cfg.agecheck_url}/estimate", data=buf.getvalue(), method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:   # unreachable: batch stops, file stays
            people = json.load(resp)["people"]
        ages += [p["age"] for p in people if p["face_px"] >= cfg.min_face_px]
    return ages


def drop_reason(a, medium: str, frames, cfg: Config) -> tuple[str, str] | None:
    hits = safety.youth_tag_hits(a.general, cfg.youth_tag_threshold)
    if hits:
        return "youth-tag", ", ".join(f"{h} {a.general[h]:.2f}" for h in hits)
    if medium == "photo":
        ages = face_ages(frames, cfg)
        if ages:
            youngest = min(ages)
            return ("age-estimate", f"{youngest:.0f}") if youngest < cfg.photo_min_age else None
    # Drawings, or photos with no face clear enough to estimate.
    if a.youth_prob >= cfg.age_threshold:
        return "age-check", f"{a.youth_prob:.2f}"
    return None


def run_once(cfg: Config) -> None:
    sweep_copy(cfg)
    files = media.ready_files(cfg.bookmarks_dir)
    if not files:
        return
    from .vision import Vision   # loads torch only when there is work
    vision = Vision(cfg.models_dir)
    conn = db.connect(cfg.db_path)
    counts = {"kept": 0, "dropped": 0}
    start = time.time()

    for path in files:
        name, tid = path.name, media.tweet_id(path)
        try:
            frames = media.load_frames(path)
        except media.Unreadable as e:
            _drop(conn, name, tid, "unreadable", str(e)[:300], None)
            path.unlink(missing_ok=True)
            counts["dropped"] += 1
            continue

        a = vision.analyze(frames)   # a GPU error here stops the batch; the file stays for next time
        medium = pick_medium(a, cfg)
        reason = drop_reason(a, medium, frames, cfg)
        if reason:
            _drop(conn, name, tid, *reason, medium)
            print(f"tag: dropped tweet {tid} ({reason[0]}: {reason[1]})", flush=True)
            counts["dropped"] += 1
        else:
            _store(conn, cfg, name, tid, media.kind(path), medium, a)
            counts["kept"] += 1
        path.unlink(missing_ok=True)

    conn.close()
    print(f"tag: {counts['kept']} kept, {counts['dropped']} dropped in {time.time() - start:.0f}s", flush=True)


def sweep_copy(cfg: Config) -> None:
    """Posts rejected by the age checks don't stay in the permanent bookmark copy either.
    Runs on every check because the copy can be downloaded after the post was rejected."""
    if not COPY_DIR.is_dir():
        return
    conn = db.connect(cfg.db_path)
    tids = [r[0] for r in conn.execute("SELECT DISTINCT tweet_id FROM dropped WHERE reason != 'unreadable'"
                                       " AND tweet_id IS NOT NULL")]
    conn.close()
    for tid in tids:
        for f in COPY_DIR.glob(f"{tid}_*"):
            f.unlink(missing_ok=True)
            print(f"tag: removed {f.name} from the bookmark copy", flush=True)


def _drop(conn, name, tid, reason, detail, medium):
    with conn:
        conn.execute("INSERT OR REPLACE INTO dropped(file, tweet_id, reason, detail, medium) VALUES (?,?,?,?,?)",
                     (name, tid, reason, detail, medium))


def _store(conn, cfg, name, tid, kind, medium, a):
    tags = {t: s for t, s in a.general.items()
            if s >= cfg.tag_threshold and t not in safety.NEVER_PROMPT_TAGS}
    with conn:
        conn.execute("DELETE FROM bookmarks WHERE file = ?", (name,))
        cur = conn.execute(
            "INSERT INTO bookmarks(file, tweet_id, kind, medium, medium_probs, rating, embedding)"
            " VALUES (?,?,?,?,?,?,?)",
            (name, tid, kind, medium, json.dumps({k: round(v, 3) for k, v in a.medium_probs.items()}),
             a.rating, a.embedding.tobytes()),
        )
        conn.executemany("INSERT INTO bookmark_tags(bookmark_id, tag, score) VALUES (?,?,?)",
                         [(cur.lastrowid, t, round(s, 3)) for t, s in tags.items()])
