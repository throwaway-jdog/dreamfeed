/* ---------- following ---------- */
// The Live tab's two pages: Following (who you follow, live and not) and Discover.
const livePage = { page: "following" };
try { if (localStorage.getItem("livePage") === "discover") livePage.page = "discover"; } catch {}
function showLivePage(page, load = true) {
  livePage.page = page;
  try { localStorage.setItem("livePage", page); } catch {}
  document.querySelectorAll("#live-page button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.p === page)));
  $("f-live-panel").hidden = page !== "following";
  $("f-off-panel").hidden = page !== "following" || !$("f-off").children.length;
  $("d-panel").hidden = page !== "discover";
  if (load && page === "discover" && !dc.loaded) loadDiscover(true);
}
document.querySelectorAll("#live-page button").forEach(b => b.onclick = () => { showLivePage(b.dataset.p); setUrl(tabPath("follow")); });
const follow = { timer: null };
async function refreshFollowing() {
  clearTimeout(follow.timer);
  let d;
  try { d = await api("api/following"); } catch (err) { $("f-status").textContent = err.message; return; }
  const live = d.rooms.filter(r => r.live), off = d.rooms.filter(r => !r.live), st = d.status || {};
  follow.dvr = d.dvr || {}; follow.names = new Set(d.rooms.map(r => r.name));
  $("live-n").textContent = live.length || "";
  $("f-status").textContent = st.error ? st.error
    : !st.at ? "Waiting for the first look at Chaturbate (the follow service)."
    : live.length ? "" : d.rooms.length ? "No one you follow is live right now." : "You don't follow anyone on Chaturbate yet.";
  follow.live = live;
  $("f-live").replaceChildren(...live.map(r => liveCard(r, live)));
  $("f-off").replaceChildren(...off.map(offRow));
  $("f-off-panel").hidden = !off.length || livePage.page !== "following";
  if (livePage.page === "discover" && !dc.loaded) loadDiscover(true);

  if (state.view === "follow") follow.timer = setTimeout(refreshFollowing, 60000);
}
function liveCard(r, list) {
  const i = r.info || {}, b = el("button", "live-card"), shot = el("span", "shot"), img = el("img");
  b.type = "button"; img.alt = ""; img.loading = "lazy"; if (r.thumb) img.src = r.thumb;
  shot.append(img, el("span", "on", "LIVE"));
  if (r.dvr && r.dvr.state === "recording") shot.append(el("span", "rec", "● REC"));
  const row = el("span", "who-row"); row.append(el("b", null, r.name), el("small", null, [
    i.age ? String(i.age) : "", `${(i.viewers || 0).toLocaleString()} watching`, i.since ? `live ${relTime(i.since)}` : "",
    i.show && i.show !== "public" ? i.show : ""].filter(Boolean).join(" · ")));
  b.append(shot, row, el("span", "title", i.title || ""));
  const usual = usualHours(r.times); if (usual) b.append(el("small", null, usual));
  const sync = () => {
    const n = mv.picked.findIndex(x => x.name === r.name);
    b.classList.toggle("picked", n >= 0); shot.querySelector(".pick")?.remove();
    if (mv.picking && n >= 0) shot.append(el("span", "pick", String(n + 1)));
  };
  b.onclick = () => {
    if (!mv.picking) return openRoom(r, list);
    const n = mv.picked.findIndex(x => x.name === r.name);
    if (n >= 0) mv.picked.splice(n, 1); else if (mv.picked.length < 4) mv.picked.push(r); else return toast("Up to 4 at once.");
    mvSync();
  };
  b._sync = sync; sync();
  const item = el("div", "live-item"), acts = el("div", "acts"), pfb = el("button", "secondary vids",
    r.videos ? `Profile · ${r.videos} video${r.videos === 1 ? "" : "s"}` : "Profile");
  pfb.type = "button"; pfb.onclick = () => openRoomProfile(r); acts.append(pfb);
  if ((follow.dvr || {}).on && r.dvr !== undefined) {      // (rooms you follow: your recorder's say on each)
    // Record asks which: this stream only, or all of them; recording, a tap stops it
    const on = !!(r.dvr && r.dvr.running), once = on && r.dvr.once;
    const rb = el("button", "secondary vids", on ? (once ? "● This stream" : "● Recording") : "Record");
    rb.type = "button"; rb.setAttribute("aria-pressed", String(on));
    rb.title = r.dvr ? r.dvr.status : "Not on your recorder's list";
    const send = async (b, action) => {
      b.disabled = true;
      try { r.dvr = (await api("api/dvr", { name: r.name, action })).dvr; refreshFollowing(); }
      catch (err) { toast(err.message); b.disabled = false; }
    };
    rb.onclick = () => {
      if (on) return send(rb, "stop");
      const one = el("button", "secondary vids", "This stream"), all = el("button", "secondary vids", "All streams");
      one.type = all.type = "button";
      one.onclick = () => send(one, "once"); all.onclick = () => send(all, "record");
      rb.replaceWith(one, all);
    };
    acts.append(rb);
  }
  if (r.discovered && !r.followed) {
    const fb = el("button", "secondary vids", "Follow"); fb.type = "button";
    fb.onclick = async () => {
      fb.disabled = true; fb.textContent = "Following…";
      try { await api("api/live/follow", { name: r.name, follow: true }); r.followed = true; setTimeout(refreshFollowing, 8000); fb.textContent = "Followed"; }
      catch (err) { toast(err.message); fb.disabled = false; fb.textContent = "Follow"; }
    };
    acts.append(fb);
  }
  item.append(b, acts);
  return item;
}
// Your recorder (streamonitor) on a room, in words.
function dvrWords(st, live) {
  if (!st) return "Not recorded";
  if (st.once && st.state === "recording") return "● Recording this stream only";
  if (st.once && st.state === "waiting") return live ? "Records this stream only (starting)" : "Records their next stream only";
  return { recording: "● Recording now", waiting: "Records when they go live", paused: "Recording paused" }[st.state]
    || `Recorder: ${st.status || "a problem"}`;
}
function offRow(r) {
  const li = el("li"), row = el("button", "off-row"), d = el("div");
  row.type = "button"; row.onclick = () => openRoomProfile(r); li.append(row);
  if (r.thumb) { const img = el("img"); img.alt = ""; img.loading = "lazy"; img.src = r.thumb; row.append(img); }
  else row.append(el("span", "ph"));
  const last = r.last_live ? `last live ${relTime(new Date(r.last_live * 1000).toISOString())} ago` : "not seen live yet";
  d.append(el("b", null, r.name), el("small", null, [last, usualHours(r.times)].filter(Boolean).join(" · ")));
  if (r.videos) d.append(el("small", "has", `${r.videos} video${r.videos === 1 ? "" : "s"}`));
  if (r.dvr) d.append(el("small", r.dvr.running ? "has" : null, dvrWords(r.dvr)));
  row.append(d);
  return li;
}

/* Watch several: pick up to 4 live rooms (yours or from Discover), each in its own tile, all
   muted but the one you tapped. Lower quality per tile (hls.js caps it to the tile's size). */
const mv = { picking: false, picked: [], tiles: [], timer: null };
function mvSync() {
  document.querySelectorAll(".live-card").forEach(b => b._sync && b._sync());
  $("mv-bar").hidden = !mv.picking;
  $("mv-count").textContent = mv.picked.length ? `${mv.picked.length} picked` : "Pick up to 4 rooms";
  $("mv-go").disabled = mv.picked.length < 1;
  $("mv-pick").textContent = mv.picking ? "Picking…" : "Watch several";
}
$("mv-pick").onclick = () => { mv.picking = !mv.picking; if (!mv.picking) mv.picked = []; mvSync(); };
$("mv-cancel").onclick = () => { mv.picking = false; mv.picked = []; mvSync(); };
$("mv-go").onclick = () => { const rooms = mv.picked.slice(); mv.picking = false; mv.picked = []; mvSync(); openMulti(rooms); };
function mvLayout() {
  const n = mv.tiles.length, wide = innerWidth > innerHeight;
  $("mv-grid").style.setProperty("--cols", n <= 1 ? 1 : wide ? 2 : n <= 2 ? 1 : 2);
}
addEventListener("resize", () => { if (!$("multi").hidden) mvLayout(); });
// Each tile plays on its own: adding or closing one leaves the others playing. Every minute
// each tile's title and viewers are asked again.
const MV_MAX = 4;
async function showMulti(rooms) {
  closeMulti();
  $("multi").hidden = false;
  for (const r of rooms.slice(0, MV_MAX)) mvAdd(r);
  mvWatch();
}
function mvAdd(r) {
  if (mv.tiles.length >= MV_MAX || mv.tiles.some(t => t.r.name === r.name)) return;
  const t = { r, hls: null, gen: 0 };
  const box = el("div", "mv-tile"), v = el("video"), msg = el("p", "msg", "Loading…"), tb = el("div", "tb");
  const lbl = el("span", "lbl"), name = el("b", null, r.name), title = el("small");
  lbl.append(name, title);
  v.playsInline = v.autoplay = v.muted = true;
  const big = el("button", null, "Full"), rm = el("button", null, "✕"); big.type = rm.type = "button";
  big.onclick = e => { e.stopPropagation(); openRoom(t.r, mv.tiles.map(x => x.r)); };
  rm.onclick = e => { e.stopPropagation(); mvRemove(t); };
  tb.append(big, rm);
  box.append(v, lbl, msg, tb);
  box.onclick = () => mvLoud(t);
  Object.assign(t, { v, box, msg, title });
  mv.tiles.push(t);
  $("mv-grid").append(box);
  mvTitle(t, (r.info || {}).title, (r.info || {}).viewers);
  mvPlay(t);
  mvLayout(); mvBar(); if (!$("multi").hidden) setUrl(watchPath());
}
function mvTitle(t, title, viewers) {
  t.title.textContent = [viewers != null ? `${Number(viewers).toLocaleString()} watching` : "", title || ""].filter(Boolean).join(" · ");
}
async function mvPlay(t) {
  const gen = ++t.gen, { v, msg } = t;
  if (t.hls) { t.hls.destroy(); t.hls = null; }
  msg.textContent = "Loading…";
  let d;
  try { d = await api(`api/live/stream?name=${encodeURIComponent(t.r.name)}`); } catch (err) { msg.textContent = err.message; return; }
  if (!mv.tiles.includes(t) || gen !== t.gen) return;
  mvTitle(t, d.title, d.viewers);
  if (!d.hls) { msg.textContent = { private: "In a private show", hidden: "Hidden show", away: "Away" }[d.status] || "Not live right now"; return; }
  const Hls = await hlsLib().catch(() => null);
  if (!mv.tiles.includes(t) || gen !== t.gen) return;
  if (Hls && Hls.isSupported()) {
    t.hls = new Hls({ capLevelToPlayerSize: true, liveSyncDurationCount: 3 });
    t.hls.on(Hls.Events.ERROR, (_, e) => {          // stopped: tried again once, 10 s later
      if (!e.fatal || gen !== t.gen) return;
      msg.textContent = "The stream stopped. Trying again…";
      setTimeout(() => { if (mv.tiles.includes(t) && gen === t.gen) mvPlay(t); }, 10000);
    });
    t.hls.loadSource(d.hls); t.hls.attachMedia(v);
  } else if (v.canPlayType("application/vnd.apple.mpegurl")) v.src = d.hls;
  else { msg.textContent = "This browser can't play live video"; return; }
  v.onplaying = () => { msg.textContent = ""; };
  v.play().catch(() => {});
}
function mvRemove(t) {
  t.gen++; if (t.hls) t.hls.destroy(); t.v.pause(); t.v.removeAttribute("src"); t.v.load(); t.box.remove();
  mv.tiles = mv.tiles.filter(x => x !== t);
  if (!mv.tiles.length) return leave();
  mvLayout(); mvBar(); setUrl(watchPath());
}
function mvWatch() {
  clearTimeout(mv.timer);
  mv.timer = setTimeout(async () => {
    if ($("multi").hidden) return;
    await Promise.all(mv.tiles.map(async t => {
      try {
        const d = await api(`api/live/stream?name=${encodeURIComponent(t.r.name)}`);
        mvTitle(t, d.title, d.viewers);
        if (!d.hls && d.status !== "unreachable") t.msg.textContent = { private: "In a private show", hidden: "Hidden show", away: "Away" }[d.status] || "The show ended";
        else if (d.hls && t.msg.textContent && !t.msg.textContent.startsWith("Loading")) mvPlay(t);   // back on
      } catch {}
    }));
    mvWatch();
  }, 60000);
}
function mvLoud(t) {
  mv.tiles.forEach(x => { x.v.muted = x !== t; x.box.classList.toggle("loud", x === t); if (x === t) x.v.play().catch(() => {}); });
  mvBar();
}
function mvMuteAll() { mv.tiles.forEach(x => { x.v.muted = true; x.box.classList.remove("loud"); }); mvBar(); }
function mvBar() {
  $("mv-add").hidden = mv.tiles.length >= MV_MAX;
  $("mv-mute").disabled = mv.tiles.every(x => x.v.muted);
  $("mv-hint").textContent = mv.tiles.some(x => !x.v.muted) ? "" : "Tap one for its sound";
}
// Add a room: who you follow that's live, then Discover's rooms (those already shown left out).
// Add a room: one of yours that's live, or one from Discover (for you, or a search).
const mvp = { tab: "following", q: "", offset: 0, rooms: [], more: false, gen: 0 };
function mvRow(r) {
  const b = el("button", "mv-pick-row"); b.type = "button";
  const img = el("img"); img.alt = ""; img.loading = "lazy"; if (r.thumb) img.src = r.thumb;
  const i = r.info || {}, d = el("div");
  d.append(el("b", null, r.name), el("small", null, [`${(i.viewers || 0).toLocaleString()} watching`, i.title].filter(Boolean).join(" · ")));
  b.append(img, d);
  b.onclick = () => { $("mv-picker").hidden = true; mvAdd(r); };
  return b;
}
function mvPickList() {
  const shown = new Set(mv.tiles.map(t => t.r.name)), list = $("mv-list");
  const following = mvp.tab === "following";
  document.querySelectorAll("#mv-tabs button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.t === mvp.tab)));
  $("mv-search").hidden = following;
  $("mv-more").hidden = following || !mvp.more;
  const rooms = (following ? follow.live || [] : mvp.rooms)
    .filter((r, k, all) => !shown.has(r.name) && all.findIndex(x => x.name === r.name) === k);
  if (rooms.length) return list.replaceChildren(...rooms.map(mvRow));
  list.replaceChildren(el("p", "note", following ? "None of yours are live. Try Discover." : mvp.gen && !mvp.loading ? "No one here right now." : "Looking…"));
}
async function mvDiscover(reset) {
  if (reset) { mvp.offset = 0; mvp.rooms = []; mvp.more = false; }
  const gen = ++mvp.gen, mode = mvp.q ? "search" : "foryou"; mvp.loading = true; mvPickList();
  let d;
  try { d = await api(`api/discover/cb?mode=${mode}&gender=${dc.gender}&offset=${mvp.offset}&q=${encodeURIComponent(mvp.q)}`); }
  catch (err) { if (gen === mvp.gen) { mvp.loading = false; $("mv-list").replaceChildren(el("p", "note", err.message)); } return; }
  if (gen !== mvp.gen) return;
  mvp.loading = false;
  const have = new Set(mvp.rooms.map(r => r.name));
  mvp.rooms.push(...d.rooms.filter(r => !have.has(r.name)));
  mvp.offset += mode === "foryou" ? d.rooms.length : 60; mvp.more = !!d.more;
  for (const r of d.rooms) nav.rooms.set(r.name, r);
  mvPickList();
}
function mvPicker() {
  if (!(follow.live || []).some(r => !mv.tiles.some(t => t.r.name === r.name))) mvp.tab = "discover";
  if (mvp.tab === "discover" && !mvp.rooms.length) mvDiscover(true);
  mvPickList();
  $("mv-picker").hidden = false;
}
document.querySelectorAll("#mv-tabs button").forEach(b => b.onclick = () => {
  mvp.tab = b.dataset.t;
  if (mvp.tab === "discover" && !mvp.rooms.length && !mvp.loading) mvDiscover(true); else mvPickList();
});
$("mv-search").onsubmit = e => { e.preventDefault(); mvp.q = $("mv-q").value.trim(); mvDiscover(true); };
$("mv-more").onclick = () => mvDiscover(false);
function closeMulti() {
  clearTimeout(mv.timer);
  for (const t of mv.tiles) { t.gen++; if (t.hls) t.hls.destroy(); if (t.v) { t.v.pause(); t.v.removeAttribute("src"); t.v.load(); } }
  mv.tiles = []; $("mv-grid").replaceChildren(); $("multi").hidden = true; $("mv-picker").hidden = true;
}
$("mv-close").onclick = leave;
$("mv-add").onclick = mvPicker;
$("mv-mute").onclick = mvMuteAll;
$("mv-picker-close").onclick = () => { $("mv-picker").hidden = true; };

/* Discover (Live): rooms you don't follow, through the same age and word checks. */
const dc = { mode: "foryou", gender: "", q: "", offset: 0, rooms: [], gen: 0, loaded: false };
showLivePage(livePage.page, false);      // (Discover loads when the Live tab opens on it)
document.querySelectorAll("#d-mode button").forEach(b => b.onclick = () => {
  dc.mode = b.dataset.m;
  document.querySelectorAll("#d-mode button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  $("d-search").hidden = dc.mode !== "search";
  if (dc.mode === "search") { $("d-q").focus(); if (!dc.q) { $("d-list").replaceChildren(); $("d-note").textContent = ""; $("d-more").hidden = true; return; } }
  loadDiscover(true);
});
document.querySelectorAll("#d-gender button").forEach(b => b.onclick = () => {
  dc.gender = b.dataset.g;
  document.querySelectorAll("#d-gender button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  if (dc.mode !== "search" || dc.q) loadDiscover(true);
});
$("d-search").onsubmit = e => { e.preventDefault(); dc.q = $("d-q").value.trim(); if (dc.q) loadDiscover(true); };
$("d-more").onclick = () => loadDiscover(false);
async function loadDiscover(reset) {
  if (reset) { dc.offset = 0; dc.rooms = []; $("d-list").replaceChildren(); }
  const gen = ++dc.gen; dc.loaded = true;
  $("d-note").textContent = "Looking…"; $("d-more").hidden = true;
  let d;
  try {
    d = await api(`api/discover/cb?mode=${dc.mode}&gender=${dc.gender}&offset=${dc.offset}&q=${encodeURIComponent(dc.q)}`);
  } catch (err) { if (gen === dc.gen) $("d-note").textContent = err.message; return; }
  if (gen !== dc.gen) return;
  const have = new Set(dc.rooms.map(r => r.name)), fresh = d.rooms.filter(r => !have.has(r.name));
  dc.rooms.push(...fresh); dc.offset += dc.mode === "foryou" ? d.rooms.length : 60;
  $("d-list").append(...fresh.map(r => liveCard(r, dc.rooms)));
  $("d-note").textContent = d.note || (dc.mode === "foryou" && d.tags && d.tags.length ? `Live now with tags like yours: ${d.tags.map(t => "#" + t).join(" ")}` : "")
    || (!dc.rooms.length ? "No one here right now." : "");
  $("d-more").hidden = !d.more;
}

// The hours of the day (your time) they're usually live: those they were live in on at least
// 40% of the days they streamed, the longest run of them. Needs 3 days of streams to say.
function usualHours(times) {
  if (!times || !times.length) return "";
  const days = new Set(), hits = Array.from({ length: 24 }, () => new Set());
  for (const [s, e] of times) {
    const day = new Date(s * 1000).toDateString(); days.add(day);
    for (let t = Math.floor(s / 3600) * 3600; t <= e; t += 3600) hits[new Date(t * 1000).getHours()].add(day);
  }
  if (days.size < 3) return "";
  const hot = hits.map(h => h.size >= Math.max(2, Math.ceil(days.size * 0.4)));
  if (hot.every(Boolean)) return "live at all hours";
  let best = null;
  for (let h = 0; h < 24; h++) {
    if (!hot[h] || hot[(h + 23) % 24]) continue;     // a run starts here
    let n = 0; while (n < 24 && hot[(h + n) % 24]) n++;
    if (!best || n > best.n) best = { h, n };
  }
  if (!best) return "live at different times";
  const at = h => new Date(2000, 0, 1, h % 24).toLocaleTimeString([], { hour: "numeric" });
  return `usually live ${at(best.h)}–${at(best.h + best.n)}`;
}
const fp = { source: "all", mode: "following", tags: "", cursor: "", more: false, loading: false, gen: 0, shown: 0 };
document.querySelectorAll("#f-mode button").forEach(b => b.onclick = () => {
  fp.mode = b.dataset.m; remember("feedMode", fp.mode); setUrl(tabPath("posts"));
  document.querySelectorAll("#f-mode button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  loadPosts(true);
});
// From: All, or the sites you tap (several at once: X and Reddit, say); tap one again to drop it.
const FEED_SITES = ["x", "bsky", "reddit", "e621"];
function showSources() {
  const on = fp.source === "all" ? ["all"] : fp.source.split(",");
  document.querySelectorAll("#f-source button").forEach(x => x.setAttribute("aria-pressed", String(on.includes(x.dataset.s))));
  $("br-form").hidden = fp.source !== "reddit"; $("e6-tags-form").hidden = fp.source !== "e621";
}
document.querySelectorAll("#f-source button").forEach(b => b.onclick = () => {
  const s = b.dataset.s, now = fp.source === "all" ? [] : fp.source.split(",");
  const next = s === "all" ? [] : now.includes(s) ? now.filter(x => x !== s) : [...now, s];
  fp.source = next.length && next.length < FEED_SITES.length ? FEED_SITES.filter(x => next.includes(x)).join(",") : "all";
  remember("feedSource", fp.source); showSources();
  if (fp.source === "reddit") loadRecentBrowses();
  loadPosts(true);
});
$("f-more").onclick = () => loadPosts(false);
// The Feed and Saved as you left them (mode, site, Saved's filter), in this browser.
function remember(k, v) { try { localStorage.setItem(k, v); } catch {} }
function recalled(k, ok) { try { const v = localStorage.getItem(k); return ok.includes(v) ? v : null; } catch { return null; } }
{
  const m = recalled("feedMode", ["following", "foryou"]);
  let src = null; try { src = localStorage.getItem("feedSource"); } catch {}
  if (src !== "all" && !(src && src.split(",").every(x => FEED_SITES.includes(x)))) src = null;
  if (m) { fp.mode = m; document.querySelectorAll("#f-mode button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.m === m))); }
  if (src) { fp.source = src; showSources(); }
}
// e621's tag filter: only posts with these tags (Following: newest; For you: top today)
$("e6-tags-form").onsubmit = e => { e.preventDefault(); fp.tags = $("e6-tags").value.trim().split(/\s+/).join(" "); loadPosts(true); };
function retryBtn() {
  const b = el("button", "retry", "Try again"); b.type = "button";
  b.onclick = () => loadPosts(true);
  return b;
}
async function loadPosts(reset) {
  if (reset) {
    fp.cursor = ""; fp.shown = 0; fp.gen++; $("f-posts").replaceChildren();
    if (fp.mode === "foryou" && (fp.source === "all" || fp.source.split(",").includes("x"))) { const strip = el("div", "dx-wrap"); $("f-posts").append(strip); loadPeople(strip, fp.gen); }
  }
  else if (fp.loading) return;
  const gen = fp.gen; fp.loading = true; $("f-more").hidden = true;
  $("f-feeds").textContent = "Reading the sites…";
  try {
    const d = await api(`api/following/posts?mode=${fp.mode}&source=${encodeURIComponent(fp.source)}&cursor=${encodeURIComponent(fp.cursor)}`
      + (fp.source === "e621" && fp.tags ? `&tags=${encodeURIComponent(fp.tags)}` : ""));
    if (gen !== fp.gen) return;
    const names = { x: "X", reddit: "Reddit", e621: "e621" };
    $("f-feeds").textContent = Object.entries(d.errors || {}).map(([k, v]) => `${names[k] || k}: ${v}`).join(" · ");
    $("f-posts").append(...d.posts.map(postCard));
    fp.shown += d.posts.length; fp.cursor = d.cursor || ""; fp.more = d.more; $("f-more").hidden = !d.more;
    if (!fp.shown && !d.more) $("f-posts").append(el("p", "note", "No posts."));
    if (Object.keys(d.errors || {}).length) $("f-feeds").append(" ", retryBtn());
  } catch (err) { if (gen === fp.gen) { $("f-feeds").textContent = err.message + " "; $("f-feeds").append(retryBtn()); } }
  finally { if (gen === fp.gen) fp.loading = false; }
}
// For you (Feed): X accounts you don't follow, from your rooms' bios, your follows' mentions
// and X's For you, above X's For you posts.
async function loadPeople(box, gen) {
  let d;
  try { d = await api("api/discover/x"); } catch { return box.remove(); }
  if (gen !== fp.gen) return;
  if (!d.people.length) return box.remove();
  const strip = el("div", "dx-strip");
  strip.append(...d.people.map(p => {
    const b = el("button", "dx"); b.type = "button";
    if (p.thumb) { const img = el("img"); img.alt = ""; img.loading = "lazy"; img.src = p.thumb; b.append(img); } else b.append(el("span", "ph"));
    const why = p.rooms.length ? `on ${p.rooms[0]}'s Chaturbate` : p.foryou >= p.mentions ? `${p.foryou} in your For you`
      : `mentioned by ${p.by.join(", ")}`;
    b.append(el("b", null, "@" + p.handle), el("small", null, why));
    b.onclick = () => openPerson(p.rooms.length ? { room: p.rooms[0] } : { x: p.handle });
    return b;
  }));
  box.replaceChildren(el("h3", null, "People you might like"), strip);
}
