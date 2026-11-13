/* ---------- videos ----------
   The Videos tab: long videos (xvideos), For you from what you watch here, search, Continue
   watching; and dreamfeed's own player for them (also a profile's xvideos tab): their stream (up
   to 1080p; its MP4 where HLS can't play), where you left off, 👍 / 👎, and Up next when one ends.
   While one plays, how far you are is told to the server (what it learns your taste from). */
const vs = { length: "", offset: 0, more: false, q: "", page: 0, loading: false, gen: 0 };
try { const l = localStorage.getItem("vidsLength"); if (["", "10", "20"].includes(l)) vs.length = l; } catch {}
$("vs-len").value = vs.length;
const vidLen = s => !s ? "" : s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`
  : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function vidCard(v) {
  const b = el("button", "pf-vid" + (v.seen ? " seen" : "")), shot = el("span", "shot"); b.type = "button";
  if (v.thumb || v.poster) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = v.thumb || v.poster; shot.append(im); }
  else shot.append(el("span", "ph"));
  if (v.duration) shot.append(el("span", "len", vidLen(v.duration)));
  if (v.resume && v.duration) { const bar = el("span", "bar"), i = el("i"); i.style.width = `${Math.min(100, v.resume / v.duration * 100)}%`; bar.append(i); shot.append(bar); }
  b.append(shot, el("b", null, v.title || "xvideos"), el("small", null, [v.uploader, v.views && `${v.views} views`, v.rating].filter(Boolean).join(" · ")));
  if (v.why) b.append(el("span", "why", v.why));
  b.onclick = () => openVid(v);
  return b;
}
function openVid(v) { nav.xv.set(v.id, v); go(`xvideos/${encodeURIComponent(v.id)}`); }
async function loadVids(more) {
  const gen = more ? vs.gen : ++vs.gen;
  if (vs.loading && more) return;
  vs.loading = true; $("vg-more").hidden = true;
  const searching = !!vs.q;
  $("vg-title").textContent = searching ? `“${vs.q}”` : "For you"; $("vg-back").hidden = !searching;
  if (!more) { vs.offset = 0; vs.page = 0; $("vg").replaceChildren(); $("vg-note").textContent = searching ? "Searching…" : "Finding videos for you…"; }
  let d;
  try {
    d = searching ? await api(`api/vids/search?q=${encodeURIComponent(vs.q)}&page=${vs.page}&length=${vs.length}`)
                  : await api(`api/vids?length=${vs.length}&offset=${vs.offset}`);
  } catch (err) { if (gen === vs.gen) { $("vg-note").textContent = err.message; vs.loading = false; } return; }
  if (gen !== vs.gen) return;
  vs.loading = false;
  if (!more && !searching) {
    $("vc-sec").hidden = !(d.continue || []).length;
    $("vc-row").replaceChildren(...(d.continue || []).map(vidCard));
  }
  if (!more) $("vc-sec").hidden = searching || !(d.continue || []).length;
  $("vg").append(...d.videos.map(vidCard));
  const t = d.taste || {};
  $("vg-note").textContent = searching ? (!d.videos.length && !more ? "Nothing found." : "")
    : !$("vg").children.length ? "Nothing yet." : t.n ? `From what you watch here${t.tags && t.tags.length ? ": " + t.tags.slice(0, 6).join(", ") : ""}.`
    : "To start, from the rooms you follow. It learns from what you watch (and 👍 / 👎 in the player).";
  vs.more = d.more; $("vg-more").hidden = !d.more;
  if (searching) vs.page++; else vs.offset += d.videos.length;
}
$("vs-form").onsubmit = e => { e.preventDefault(); vs.q = $("vs-q").value.trim(); loadVids(); };
$("vs-len").onchange = () => { vs.length = $("vs-len").value; remember("vidsLength", vs.length); loadVids(); };
$("vg-more").onclick = () => loadVids(true);
$("vg-back").onclick = () => { vs.q = ""; $("vs-q").value = ""; loadVids(); };
$("f-saved").onclick = () => go(tabPath("liked"));
$("sheet-saved").onclick = () => { $("sheet").hidden = true; $("menu-btn").setAttribute("aria-expanded", "false"); go(tabPath("liked")); };

// The player
const xv = { hls: null, gen: 0, id: null, sent: 0, played: 0, last: null, timer: null, next: null, nextTimer: null, vote: 0 };
function xvReport() {             // how far you are (only for videos with a page: the Videos tab's, a profile's)
  const v = $("xv-video");
  if (!xv.id || !v.duration || !isFinite(v.duration)) return;
  const delta = Math.round(xv.played - xv.sent); xv.sent = xv.played;
  api("api/vids/watch", { id: xv.id, position: Math.round(v.currentTime), duration: Math.round(v.duration), delta }).catch(() => {});
}
function xvStop() {
  if (xv.id) xvReport();
  xv.gen++; xv.id = null; clearInterval(xv.timer); clearTimeout(xv.nextTimer); $("xv-next").hidden = true;
  if (xv.hls) { xv.hls.destroy(); xv.hls = null; }
  const v = $("xv-video"); v.pause(); v.removeAttribute("src"); v.removeAttribute("poster"); v.load();
  $("xv-msg").hidden = true; $("xv-up").hidden = $("xv-down").hidden = true;
}
{
  const v = $("xv-video");
  v.addEventListener("timeupdate", () => {          // seconds actually watched (not skipped over)
    if (xv.last !== null && !v.paused) { const d = v.currentTime - xv.last; if (d > 0 && d < 2) xv.played += d; }
    xv.last = v.currentTime;
  });
  v.addEventListener("seeking", () => { xv.last = null; });
  v.addEventListener("pause", () => xvReport());
  v.addEventListener("ended", () => { xvReport(); upNext(); });
}
function xvMarkVote() {
  $("xv-up").setAttribute("aria-pressed", String(xv.vote === 1)); $("xv-down").setAttribute("aria-pressed", String(xv.vote === -1));
}
async function xvVote(n) {
  if (!xv.id) return;
  const want = xv.vote === n ? 0 : n;
  try { xv.vote = (await api("api/vids/vote", { id: xv.id, vote: want })).vote; xvMarkVote(); if (want === -1) toast("Less like this: noted."); }
  catch (err) { toast(err.message); }
}
$("xv-up").onclick = () => xvVote(1);
$("xv-down").onclick = () => xvVote(-1);
function upNext() {
  const n = xv.next; if (!n) return;
  const card = $("xv-next-card"), im = el("img"); im.alt = ""; im.src = n.thumb || "";
  const d = el("div"); d.append(el("b", null, n.title), el("small", null, [n.uploader, n.duration && vidLen(n.duration)].filter(Boolean).join(" · ")));
  card.replaceChildren(im, d); $("xv-next").hidden = false;
  let left = 8; $("xv-next-go").textContent = `Play now (${left})`;
  clearInterval(xv.nextTimer);
  xv.nextTimer = setInterval(() => { left--; $("xv-next-go").textContent = `Play now (${left})`; if (left <= 0) { clearInterval(xv.nextTimer); openVid(n); } }, 1000);
}
$("xv-next-go").onclick = () => { clearInterval(xv.nextTimer); if (xv.next) openVid(xv.next); };
$("xv-next-card").onclick = () => $("xv-next-go").onclick();
$("xv-next-cancel").onclick = () => { clearInterval(xv.nextTimer); $("xv-next").hidden = true; };
async function showXvideo(it) {
  xvStop(); const gen = xv.gen, v = $("xv-video");
  $("xv-title").textContent = it.title || "xvideos"; v.loop = false;
  $("xv-open").href = it.url ? `https://www.xvideos.com${it.url}` : `https://www.xvideos.com/video.${encodeURIComponent(it.id)}/`;
  $("xv-player").hidden = false;
  if (it.thumb) v.poster = it.thumb;
  let f;
  try { f = it.url ? await api(`api/vids/video?url=${encodeURIComponent(it.url)}`) : await api(`api/xvideos/video?id=${encodeURIComponent(it.id)}`); }
  catch (err) { if (gen === xv.gen) { $("xv-msg").textContent = err.message; $("xv-msg").hidden = false; } return; }
  if (gen !== xv.gen) return;
  if (f.title) $("xv-title").textContent = f.title;
  if (f.poster) v.poster = f.poster;
  if (it.url) {                                     // (one with its page: watched, voted on, followed by another)
    Object.assign(xv, { id: f.id, sent: 0, played: 0, last: null, vote: f.vote || 0, next: (f.related || [])[0] || null });
    $("xv-up").hidden = $("xv-down").hidden = false; xvMarkVote();
    for (const r of f.related || []) nav.xv.set(r.id, r);
    xv.timer = setInterval(() => { if (!v.paused) xvReport(); }, 20000);
  }
  if (f.resume) v.addEventListener("loadedmetadata", () => { if (gen === xv.gen && f.resume < v.duration - 30) v.currentTime = f.resume; }, { once: true });
  const mp4 = f.mp4 || f.mp4_low, play = () => v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
  if (f.hls && v.canPlayType("application/vnd.apple.mpegurl")) { v.src = f.hls; return play(); }
  if (f.hls) {
    try {
      const Hls = await hlsLib();
      if (gen !== xv.gen) return;
      if (Hls.isSupported()) {
        xv.hls = new Hls({ capLevelToPlayerSize: true }); xv.hls.loadSource(f.hls); xv.hls.attachMedia(v);
        xv.hls.on(Hls.Events.MANIFEST_PARSED, play);
        // (a stream that won't play: its MP4 instead; the stream's player is let go after it's done)
        xv.hls.on(Hls.Events.ERROR, (_, e) => {
          if (!e.fatal || gen !== xv.gen || !xv.hls) return;
          const h = xv.hls; xv.hls = null; setTimeout(() => h.destroy(), 0);
          if (mp4) { v.src = mp4; play(); }
        });
        return;
      }
    } catch {}
  }
  if (mp4) { v.src = mp4; play(); }
}
function closeXvideo() { xvStop(); $("xv-player").hidden = true; if (state.view === "vids" && !vs.q) loadVids(); }
