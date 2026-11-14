"""Highlights of your own room videos (cbvideos.py): the parts where something's happening,
cut together, the dead air left out. `python -m dreamfeed follow highlight <job>`, started by
the follow service for each request from a room's profile (the highlights table). CPU only,
at low priority.

How it picks: two quick passes over the video, at 2 looks a second:
- motion: how much each (small, grey) frame differs from the one before;
- sound: how loud it is.
Each look gets a score from how it ranks against the rest of the same video (motion counts
three times as much as sound: chatting is loud but still), smoothed over about 5 seconds. The
best-scoring share is kept (keep: 0.1 to 0.5), in stretches with a second either side; gaps
under 3 seconds are filled and stretches under 4 seconds dropped. The stretches are then
encoded into one MP4 (H.264 and AAC) in the room's highlights/ folder, next to the original,
which is left as it was; or, asked for after a recording (then_delete: a room's "highlights, then
delete the original"), moved to the trash once the highlights are checked to play (gone after
cbvideos.TRASH_DAYS; Undo on the profile until then). Either way, Updates says how it went.
"""
import json
import math
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

from . import cbvideos
from ..core import notices
from ..core.db import connect

STEP = 0.5            # seconds between looks
SMOOTH = 9            # looks averaged (about 4.5 s)
PAD, GAP, SHORTEST = 1.0, 3.0, 4.0
MOTION_WEIGHT = 0.75
NICE = ["nice", "-n", "15"]


def _threads() -> str:
    return os.environ.get("FOLLOW_THREADS", "").strip() or "2"


def _probe(src: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,avg_frame_rate",
                          "-of", "json", str(src)], capture_output=True, text=True, timeout=120)
    d = json.loads(out.stdout or "{}")
    streams = d.get("streams") or []
    rate = 30.0
    for s in streams:
        if s.get("codec_type") == "video":
            a, _, b = str(s.get("avg_frame_rate") or "30/1").partition("/")
            try:
                rate = float(a) / float(b or 1) or 30.0
            except (ValueError, ZeroDivisionError):
                pass
            break
    return {"duration": float((d.get("format") or {}).get("duration") or 0),
            "video": any(s.get("codec_type") == "video" for s in streams),
            "audio": any(s.get("codec_type") == "audio" for s in streams),
            "rate": min(60.0, max(10.0, round(rate, 3)))}


def _series(args: list[str], key: str, duration: float, report) -> list[tuple[float, float]]:
    """(time, value) of one metadata key, printed by ffmpeg's metadata filter."""
    cmd = NICE + ["ffmpeg", "-nostdin", "-v", "error", "-threads", _threads()] + args + ["-f", "null", "-"]
    out, t = [], 0.0
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as p:
        for line in p.stdout:
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                t = float(m.group(1))
                continue
            if line.startswith(key + "="):
                try:
                    v = float(line.split("=", 1)[1])
                except ValueError:
                    continue
                out.append((t, v if math.isfinite(v) else -100.0))
                if len(out) % 200 == 0:
                    report(t / duration if duration else 0)
    if p.returncode:
        raise RuntimeError("ffmpeg couldn't read the video")
    return out


def _ranks(values: list[float]) -> list[float]:
    """Each value's place among them all, 0 (lowest) to 1 (highest)."""
    order = sorted(range(len(values)), key=values.__getitem__)
    r = [0.0] * len(values)
    for place, i in enumerate(order):
        r[i] = place / max(1, len(values) - 1)
    return r


def _binned(series: list[tuple[float, float]], n: int, empty: float) -> list[float]:
    out = [empty] * n
    for t, v in series:
        b = min(n - 1, int(t / STEP))
        out[b] = max(out[b], v) if out[b] != empty else v
    return out


def pick(motion: list[tuple[float, float]], sound: list[tuple[float, float]] | None, duration: float,
         keep: float) -> list[tuple[float, float]]:
    """The stretches (start, end) worth keeping."""
    n = max(1, math.ceil(duration / STEP))
    score = _ranks(_binned(motion, n, 0.0))
    if sound:
        loud = _ranks(_binned(sound, n, -100.0))
        score = [MOTION_WEIGHT * m + (1 - MOTION_WEIGHT) * s for m, s in zip(score, loud)]
    half = SMOOTH // 2
    smooth = [sum(score[max(0, i - half):i + half + 1]) / len(score[max(0, i - half):i + half + 1]) for i in range(n)]
    cut = sorted(smooth)[min(n - 1, int(n * (1 - keep)))]
    spans, start = [], None
    for i, v in enumerate(smooth + [-1.0]):
        if v >= cut and start is None:
            start = i
        elif v < cut and start is not None:
            spans.append([start * STEP - PAD, i * STEP + PAD])
            start = None
    merged = []
    for a, b in spans:
        a, b = max(0.0, a), min(duration, b)
        if merged and a - merged[-1][1] < GAP:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in merged if b - a >= SHORTEST]


def cut(src: Path, dest: Path, spans: list[tuple[float, float]], info: dict, report) -> None:
    """The stretches of src, one after another, encoded into dest."""
    between = "+".join(f"between(t,{a},{b})" for a, b in spans)
    graph = f"[0:v]fps={info['rate']},select='{between}',setpts=N/({info['rate']}*TB)[v]"
    maps = ["-map", "[v]"]
    if info["audio"]:
        graph += f";[0:a]aselect='{between}',asetpts=N/SR/TB[a]"
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    script = dest.with_name(dest.name + ".graph")
    script.write_text(graph)
    total = sum(b - a for a, b in spans)
    cmd = NICE + ["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", _threads(), "-i", str(src),
                  "-filter_complex_script", str(script)] + maps + [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-progress", "pipe:1", "-f", "mp4", str(dest)]
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as p:
            for line in p.stdout:
                if line.startswith("out_time_us="):
                    try:
                        report(int(line.split("=")[1]) / 1e6 / total)
                    except ValueError:
                        pass
            err = p.stderr.read()
        if p.returncode:
            raise RuntimeError(f"ffmpeg couldn't cut it ({err.strip()[-200:]})")
    finally:
        script.unlink(missing_ok=True)


def run(job_id: int) -> None:
    data = Path(os.environ["DATA_DIR"])
    conn = connect(data / "feed.db")
    job = conn.execute("SELECT room, path, keep, then_delete FROM highlights WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return
    room, rel, keep, then_delete = job
    title = Path(rel).stem.replace("_", " ")

    def report(phase: str, pct: float) -> None:
        with conn:
            conn.execute("UPDATE highlights SET progress = ? WHERE id = ?",
                         (json.dumps({"phase": phase, "pct": round(max(0.0, min(1.0, pct)) * 100)}), job_id))

    with conn:
        conn.execute("UPDATE highlights SET status = 'running', error = NULL WHERE id = ?", (job_id,))
    try:
        rooms = [n for (n,) in conn.execute("SELECT name FROM follows WHERE source = 'chaturbate'")]
        src = cbvideos.file(room, rel, rooms)
        if not src:
            raise RuntimeError("the video isn't there any more")
        if cbvideos.is_highlight(rel):
            raise RuntimeError("that's already highlights")
        info = _probe(src)
        if not info["video"] or info["duration"] < 30:
            raise RuntimeError("too short to cut (under 30 seconds)")
        d = info["duration"]
        report("motion", 0)
        motion = _series(["-an", "-i", str(src), "-vf", f"fps={1 / STEP},scale=160:-2,format=gray,"
                          "tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-"],
                         "lavfi.signalstats.YAVG", d, lambda f: report("motion", f))
        sound = None
        if info["audio"]:
            report("sound", 0)
            sound = _series(["-vn", "-i", str(src), "-af", f"aresample=8000,asetnsamples=n={int(8000 * STEP)}:p=0,"
                             "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"],
                            "lavfi.astats.Overall.RMS_level", d, lambda f: report("sound", f))
        if not motion:
            raise RuntimeError("couldn't read the picture")
        spans = pick(motion, sound, d, keep)
        if not spans:
            raise RuntimeError("found nothing to keep")
        out_rel = cbvideos.highlight_of(rel, room)
        dest = cbvideos.root() / out_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name("." + dest.name + ".part")      # hidden until it's done
        report("cutting", 0)
        try:
            cut(src, part, spans, info, lambda f: report("cutting", f))
            part.replace(dest)
        finally:
            part.unlink(missing_ok=True)
        kept = sum(b - a for a, b in spans)
        trashed = None
        if then_delete:            # the original into the trash, once its highlights are known to play
            made = _probe(dest)
            if made["video"] and made["duration"] >= min(kept, 10) * 0.8:
                trashed = cbvideos.trash(src)
            else:
                print(f"follow: highlights of {rel} don't look right: the original is kept", flush=True)
        with conn:
            conn.execute("UPDATE highlights SET status = 'done', progress = NULL, result = ? WHERE id = ?",
                         (json.dumps({"path": out_rel, "kept": round(kept), "of": round(d), "parts": len(spans),
                                      "trashed": trashed}), job_id))
            notices.add(conn, "recordings", f"hl:{job_id}", f"Highlights of {room}: {_length(kept)} of {_length(d)}",
                        title + (f" · the original is in the trash (gone after {cbvideos.TRASH_DAYS} days)" if trashed
                                 else " · the original was kept: its highlights didn't check out" if then_delete else ""),
                        f"room/{room}/video/{urllib.parse.quote(out_rel)}", None)
        print(f"follow: highlights of {rel}: {round(kept)} s of {round(d)} s in {len(spans)} parts"
              + (", original in the trash" if trashed else ""), flush=True)
    except Exception as e:      # any failure is the job's, shown on the profile
        with conn:
            conn.execute("UPDATE highlights SET status = 'failed', progress = NULL, error = ? WHERE id = ?",
                         (str(e)[:300], job_id))
            notices.add(conn, "recordings", f"hl:{job_id}", f"Highlights of {room} failed", f"{title} · {str(e)[:200]}"
                        + (" · the original was kept" if then_delete else ""), f"room/{room}", None)
        print(f"follow: highlights of {rel} failed: {e}", flush=True)


def _length(s: float) -> str:
    s = int(s)
    return f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{max(1, s // 60)} min"
