/* The Live player: a room's own video (HLS) straight from Chaturbate's video servers, played
   here; hls.js where the browser can't play HLS itself (Android, desktop), Safari natively.
   It starts muted (browsers only autoplay that way); ‹ › go through the live rooms. */
const pl = { hls: null, rooms: [], i: 0, muted: true, gen: 0, lib: null, timer: null };
// The room's title and viewers while you watch (Chaturbate's, every minute).
function plInfo(r, title, viewers) {
  const i = r.info || {};
  $("pl-info").textContent = [title ?? i.title, viewers != null ? `${Number(viewers).toLocaleString()} watching` : "",
    (i.tags || []).map(t => "#" + t).join(" ")].filter(Boolean).join("  ");
}
function plWatch(gen) {
  clearTimeout(pl.timer);
  pl.timer = setTimeout(async () => {
    if (gen !== pl.gen || $("player").hidden || pl.mode !== "live") return;
    const r = pl.rooms[pl.i];
    try {
      const d = await api(`api/live/stream?name=${encodeURIComponent(r.name)}`);
      if (gen !== pl.gen) return;
      r.info = { ...(r.info || {}), title: d.title || (r.info || {}).title, viewers: d.viewers };
      plInfo(r, d.title, d.viewers);
      if (!d.hls && d.status !== "unreachable") plMsg({ private: "In a private show right now.", hidden: "The show is hidden right now.",
                                                        away: "Away for a moment." }[d.status] || "The show ended.");
    } catch {}
    plWatch(gen);
  }, 60000);
}
function plFollowBtn(r) {
  const fb = $("pl-follow"), followed = (follow.names || new Set()).has(r.name);
  fb.hidden = pl.mode !== "live" || followed; fb.disabled = false; fb.textContent = "Follow";
  fb.onclick = async () => {
    fb.disabled = true; fb.textContent = "Following…";
    try { await api("api/live/follow", { name: r.name, follow: true }); fb.textContent = "Followed ✓"; setTimeout(refreshFollowing, 8000); }
    catch (err) { toast(err.message); fb.disabled = false; fb.textContent = "Follow"; }
  };
}
$("pl-multi").onclick = () => openMulti([pl.rooms[pl.i]]);
function hlsLib() {
  if (!pl.lib) pl.lib = new Promise((ok, no) => {
    const sc = document.createElement("script"); sc.src = "vendor/hls.min.js";
    sc.onload = () => ok(window.Hls); sc.onerror = () => no(new Error("the player didn't load")); document.head.append(sc);
  });
  return pl.lib;
}
// A Reddit video (HLS, with sound): hls.js when it's played (Safari plays it itself); its
// plain MP4 (no sound) if hls.js won't load.
function feedHls(v, m) {
  if (v.canPlayType("application/vnd.apple.mpegurl")) { v.src = m.url; return; }
  let started = false;
  v.addEventListener("play", async () => {
    if (started) return; started = true;
    try {
      const Hls = await hlsLib();
      if (!Hls.isSupported()) throw new Error();
      const h = new Hls({ capLevelToPlayerSize: true }); h.loadSource(m.url); h.attachMedia(v);
      h.on(Hls.Events.MANIFEST_PARSED, () => v.play().catch(() => {}));
    } catch { if (m.fallback) { v.src = m.fallback; v.play().catch(() => {}); } }
  });
  if (m.fallback) v.dataset.fallback = m.fallback;
}
function showRoom(r, list) {
  pl.mode = "live"; pl.rooms = (list || follow.live || []).slice(); pl.i = Math.max(0, pl.rooms.findIndex(x => x.name === r.name));
  if (!pl.rooms.length) pl.rooms = [r];
  $("player").hidden = false; playRoom();
}
function plMsg(t) { $("pl-msg").textContent = t || ""; $("pl-msg").hidden = !t; }
function stopVideo() {
  if (pl.hls) { pl.hls.destroy(); pl.hls = null; }
  const v = $("pl-video"); v.pause(); v.removeAttribute("src"); v.load();
}
async function playRoom() {
  if (pl.mode === "file") return playFile();
  const r = pl.rooms[pl.i], i = r.info || {}, gen = ++pl.gen, v = $("pl-video");
  stopVideo(); v.onerror = null; $("pl-open").hidden = false; v.loop = false;
  $("pl-title").textContent = r.name;
  plInfo(r, null, i.viewers);
  plFollowBtn(r); $("pl-multi").hidden = false;
  $("pl-open").href = `https://chaturbate.com/${encodeURIComponent(r.name)}/`;
  $("pl-prev").disabled = $("pl-next").disabled = pl.rooms.length < 2;
  plMsg("Loading…");
  let d;
  try { d = await api(`api/live/stream?name=${encodeURIComponent(r.name)}`); } catch (err) { if (gen === pl.gen) plMsg(err.message); return; }
  if (gen !== pl.gen) return;
  if (!d.hls) {
    return plMsg({ private: "In a private show right now.", hidden: "The show is hidden right now.", away: "Away for a moment.",
                   unreachable: "Chaturbate didn't answer. Try again in a moment." }[d.status] || "Not live right now.");
  }
  v.muted = pl.muted; $("pl-sound").hidden = !pl.muted;
  const Hls = await hlsLib().catch(() => null);
  if (gen !== pl.gen) return;
  if (Hls && Hls.isSupported()) {
    pl.hls = new Hls({ lowLatencyMode: true, liveSyncDurationCount: 3 });
    pl.hls.on(Hls.Events.ERROR, (_, e) => { if (e.fatal && gen === pl.gen) plMsg("The stream stopped. Tap › and ‹ to try again."); });
    pl.hls.loadSource(d.hls); pl.hls.attachMedia(v);
  } else if (v.canPlayType("application/vnd.apple.mpegurl")) v.src = d.hls;
  else return plMsg("This browser can't play live video.");
  v.onplaying = () => { if (gen === pl.gen) plMsg(""); };
  v.play().catch(() => {});
  noteHistory("room", r.name, r.name, `room/${r.name}/watch`, r.thumb || `follow/thumb/chaturbate/${r.name}.jpg`);
  if (d.title) { r.info = { ...(r.info || {}), title: d.title }; plInfo(r, d.title, d.viewers); }
  plWatch(gen);
}
$("pl-sound").onclick = () => { pl.muted = false; const v = $("pl-video"); v.muted = false; v.play().catch(() => {}); $("pl-sound").hidden = true; };
$("pl-video").onvolumechange = () => { pl.muted = $("pl-video").muted; $("pl-sound").hidden = !pl.muted; };
$("pl-prev").onclick = () => { pl.i = (pl.i - 1 + pl.rooms.length) % pl.rooms.length; playRoom(); setUrl(playerPath()); };
$("pl-next").onclick = () => { pl.i = (pl.i + 1) % pl.rooms.length; playRoom(); setUrl(playerPath()); };
// A video from the room's profile: ‹ › go through that room's videos. With sound, since it
// was a tap that opened it (muted only if the browser refuses).
function playFile() {
  const f = pl.rooms[pl.i], gen = ++pl.gen, v = $("pl-video");
  stopVideo();
  $("pl-title").textContent = `${pf.room.name}: ${f.title}`;
  $("pl-info").textContent = [vidDate(f), vidLength(f.duration), vidSize(f.size)].filter(Boolean).join(" · ");
  $("pl-open").hidden = true; $("pl-follow").hidden = true; $("pl-multi").hidden = true;
  $("pl-prev").disabled = $("pl-next").disabled = pl.rooms.length < 2;
  plMsg("");
  v.onplaying = null;
  v.onerror = () => { if (gen === pl.gen) plMsg("This browser can't play this video (MP4 plays everywhere)."); };
  v.muted = false; v.src = f.url;
  noteHistory("recording", f.path, `${pf.room.name}: ${f.title}`, `room/${pf.room.name}/video/${f.path.split("/").map(enc).join("/")}`, f.poster || null);
  v.play().catch(() => { if (gen !== pl.gen) return; v.muted = true; $("pl-sound").hidden = false; v.play().catch(() => {}); });
  $("pl-sound").hidden = true;
}
function vidLength(s) {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}
function vidSize(b) { return b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(b / 1e6))} MB`; }
function vidDate(f) { return new Date(f.mtime * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); }

