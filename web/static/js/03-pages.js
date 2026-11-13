/* ---------- header ---------- */
for (const b of document.querySelectorAll("[data-view]")) b.onclick = () => go(tabPath(b.dataset.view));
function setView(v) {
  if (state.view === v) return;
  state.view = v;
  document.querySelectorAll("[data-view]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.view === v)));
  const dash = v === "dash", com = v === "comics", fol = v === "follow", posts = v === "posts", vids = v === "vids", page = dash || com || fol || posts || vids;
  $("dash").hidden = !dash; $("comics").hidden = !com; $("follow").hidden = !fol; $("posts").hidden = !posts; $("vids").hidden = !vids;
  $("grid").hidden = page; $("sentinel").hidden = page && !posts;
  $("saved-bar").hidden = v !== "liked"; if (v === "liked") importStatus();
  if (v !== "feed") state.persona = "";
  renderPeople();
  try { localStorage.setItem("dreamfeed-view", v); } catch {}
  if (dash) { grid.replaceChildren(); $("empty").hidden = true; $("profile").hidden = true; state.gen++; refreshDash(); loadEditable(); loadReddit(); loadSignins(); loadHealth(); }
  else if (com) { grid.replaceChildren(); $("empty").hidden = true; $("profile").hidden = true; state.gen++; loadComics(); }
  else if (fol) { grid.replaceChildren(); $("empty").hidden = true; $("profile").hidden = true; state.gen++; refreshFollowing(); }
  else if (posts) { grid.replaceChildren(); $("empty").hidden = true; $("profile").hidden = true; state.gen++; loadPosts(true); }
  else if (vids) { grid.replaceChildren(); $("empty").hidden = true; $("profile").hidden = true; state.gen++; loadVids(); }
  else reset();
}
// Saved: bring in what you saved on the sites you pick (X's and Bluesky's bookmarks, Reddit's saved
// posts, e621's favorites); their files are then kept in full quality. The pick is remembered.
let importTimer = null;
async function importStatus(started) {
  clearTimeout(importTimer);
  let d;
  try { d = started ? await api("api/saved/import", { sites: started }) : await api("api/saved/import"); } catch (err) { $("saved-note").textContent = err.message; return; }
  const one = (name, r) => !r ? "" : r.error ? `${name}: ${r.error}` : `${name}: ${r.added} new of ${r.found}`;
  const f = d.files || {}, waiting = (f.queued || 0) + (f.running || 0);
  $("saved-import").disabled = d.running;
  $("saved-note").textContent = [d.running ? "Reading what you saved…" : "", one("X", d.x), one("Bluesky", d.bsky), one("Reddit", d.reddit), one("e621", d.e621),
    waiting ? `keeping ${waiting} post${waiting === 1 ? "" : "s"} in full quality…` : "", f.failed ? `${f.failed} couldn't be kept` : ""]
    .filter(Boolean).join(" · ");
  if (state.view === "liked" && (d.running || waiting)) importTimer = setTimeout(() => importStatus(), 5000);
  if (started === undefined && d.running === false && importStatus.was) { importStatus.was = false; reset(); }
  if (d.running) importStatus.was = true;
}
const pickSites = () => [...document.querySelectorAll("#saved-pick-sites button")].filter(b => b.getAttribute("aria-pressed") === "true").map(b => b.dataset.s);
{
  let was = null; try { was = JSON.parse(localStorage.getItem("importSites") || "null"); } catch {}
  if (Array.isArray(was)) document.querySelectorAll("#saved-pick-sites button").forEach(b => b.setAttribute("aria-pressed", String(was.includes(b.dataset.s))));
}
document.querySelectorAll("#saved-pick-sites button").forEach(b => b.onclick = () => {
  b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
  $("saved-pick-go").disabled = !pickSites().length;
});
$("saved-import").onclick = () => { $("saved-pick").hidden = !$("saved-pick").hidden; $("saved-pick-go").disabled = !pickSites().length; };
$("saved-pick-cancel").onclick = () => { $("saved-pick").hidden = true; };
$("saved-pick-go").onclick = () => {
  const sites = pickSites(); if (!sites.length) return;
  remember("importSites", JSON.stringify(sites)); $("saved-pick").hidden = true; importStatus(sites);
};
{
  const v = recalled("savedSource", [...document.querySelectorAll("#saved-src button")].map(b => b.dataset.s));
  if (v) { state.savedSource = v; document.querySelectorAll("#saved-src button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.s === v))); }
}
document.querySelectorAll("#saved-src button").forEach(b => b.onclick = () => {
  state.savedSource = b.dataset.s; remember("savedSource", state.savedSource); setUrl(tabPath("liked"));
  document.querySelectorAll("#saved-src button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  reset();
});
$("menu-btn").onclick = e => {
  e.stopPropagation(); const s = $("sheet"); s.hidden = !s.hidden;
  $("menu-btn").setAttribute("aria-expanded", String(!s.hidden));
};
document.addEventListener("click", e => { if (!$("sheet").hidden && !$("sheet").contains(e.target)) { $("sheet").hidden = true; $("menu-btn").setAttribute("aria-expanded", "false"); } });

async function refreshSummary() {
  try {
    const s = await api("api/summary");
    $("live-n").textContent = s.live || "";
    const r = s.last_run;
    const run = r ? `Last run: ${nightLabel(r.night)}, ${r.status === "done" ? "finished" : r.status}` : "No nightly run yet";
    $("sheet-info").innerHTML = "";
    for (const line of [run, `${s.liked} liked`]) {
      if (!line) continue; const d = document.createElement("div"); d.textContent = line; $("sheet-info").append(d);
    }
  } catch {}
}

/* ---------- pages: each part has its own address ----------
   /feed, /feed/foryou, /saved[/x], /live[/discover], /comics[/ID], /dashboard, /personas, /p/HANDLE,
   /item/ID (a persona post), /room/NAME[/watch | /video/PATH], /watch/A+B, /x/HANDLE, /u/NAME,
   /r/SUB[/new|top], /e621/ARTIST, /post/SITE/ID, /xvideos/ID. Opening one replaces what's shown
   (no stacking): Close and Back go to the page before, or home when the page was opened by link. */
const BASE = new URL(document.baseURI).pathname;        // where the page is served (the proxy says), e.g. /dreamfeed/
const nav = { routed: null, posts: new Map(), rooms: new Map(), lists: new Map(), xv: new Map(), clips: new Map() };
const enc = encodeURIComponent;
const ROOM_NAME = /^[a-z0-9_]{1,64}$/;
function here() { const p = location.pathname; return p.startsWith(BASE) ? p.slice(BASE.length) : ""; }
function segs(rel) { return rel.split("/").filter(Boolean).map(x => { try { return decodeURIComponent(x); } catch { return x; } }); }
function go(rel, replace) {
  const n = (history.state || {}).n || 0;
  if (replace) history.replaceState({ n }, "", BASE + rel); else history.pushState({ n: n + 1 }, "", BASE + rel);
  route();
}
function setUrl(rel) {
  if (here() === rel) return;
  history.replaceState({ ...(history.state || {}), n: (history.state || {}).n || 0 }, "", BASE + rel);
  nav.routed = rel;
}
function leave() { if (((history.state || {}).n || 0) > 0) history.back(); else go("", true); }
function tabPath(v) {
  return { posts: fp.mode === "foryou" ? "feed/foryou" : "feed",
           liked: state.savedSource !== "all" ? `saved/${state.savedSource}` : "saved",
           comics: "comics", follow: livePage.page === "discover" ? "live/discover" : "live", dash: "dashboard", vids: "vids",
           feed: state.persona ? `p/${enc(state.persona)}` : "personas" }[v] || "feed";
}
function lastTab() {
  let v = "posts"; try { v = localStorage.getItem("dreamfeed-view") || "posts"; } catch {}
  return ["dash", "liked", "comics", "follow", "posts", "vids"].includes(v) ? v : "posts";
}
function playerPath() {
  const f = pl.rooms[pl.i];
  return pl.mode === "file" ? `room/${enc(pf.room.name)}/video/${enc(f.path)}` : `room/${enc(f.name)}/watch`;
}
function watchPath() { return "watch/" + mv.tiles.map(t => enc(t.r.name)).join("+"); }
function roomFor(name) {
  return nav.rooms.get(name) || (follow.live || []).find(r => r.name === name) || (dc.rooms || []).find(r => r.name === name)
    || { name, info: {} };
}
// the public ways to open a page
function openPerson(k) {
  go(k.room ? `room/${enc(k.room)}` : k.x ? `x/${enc(k.x)}` : k.e621 ? `e621/${enc(k.e621)}` : k.bsky ? `bsky/${enc(k.bsky)}` : `u/${enc(k.reddit)}`);
}
function openProfile(handle) { go(handle ? `p/${enc(handle)}` : "personas"); }      // a persona's posts
function openBrowse(sub, sort) {
  const name = String(sub || "").trim().replace(/^\/?r\//i, "").replace(/\/+$/, "");
  const same = !$("browse").hidden && br.sub && br.sub.toLowerCase() === name.toLowerCase();
  go(`r/${enc(name)}` + (sort && sort !== "hot" ? `/${sort}` : ""), same);
}
function postPath(id) { const k = String(id).indexOf(":"); return `post/${String(id).slice(0, k)}/${enc(String(id).slice(k + 1))}`; }
function openPost(p) { nav.posts.set(p.id, p); go(postPath(p.id)); }
function openRoom(r, list) { nav.rooms.set(r.name, r); if (list) nav.lists.set(r.name, list); go(`room/${enc(r.name)}/watch`); }
function openMulti(rooms) { for (const r of rooms) nav.rooms.set(r.name, r); go("watch/" + rooms.map(r => enc(r.name)).join("+")); }
function openXvideo(v) { nav.xv.set(v.id, v); go(`xvideos/${enc(v.id)}`); }
function openComic(c) { go(`comics/${enc(c.id)}`); }
// what each address shows
function closePages() {
  if (!viewer.hidden) closeViewer(true);
  closePicture(true);
  if (!$("pf-view").hidden) closeProfile();
  if (!$("browse").hidden) closeBrowse();
  if (!$("post-view").hidden) closePost();
  if (!$("player").hidden) closeRoom();
  if (!$("multi").hidden) closeMulti();
  if (!$("xv-player").hidden) closeXvideo();
  if (!$("reader").hidden) closeComic();
  if (!$("vfeed").hidden) closeVideos();
}
function route() {
  const rel = here(), [a = "", b = "", c = "", ...rest] = segs(rel);
  nav.routed = rel;
  closePages();
  const wasSingle = state.single;
  state.single = a === "item" && /^\d+$/.test(b) ? b : null;
  if (wasSingle && !state.single && state.view === "feed") state.view = "";     // (the whole feed again)
  switch (a) {
    case "": case "home": return go(tabPath(lastTab()), true);
    case "feed": {
      const m = b === "foryou" ? "foryou" : "following";
      if (fp.mode !== m) {
        fp.mode = m; remember("feedMode", m);
        document.querySelectorAll("#f-mode button[data-m]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.m === m)));
        if (state.view === "posts") loadPosts(true);
      }
      return setView("posts");
    }
    case "saved": {
      const src = [...document.querySelectorAll("#saved-src button")].map(x => x.dataset.s).includes(b) ? b : "all";
      if (state.savedSource !== src) {
        state.savedSource = src; remember("savedSource", src);
        document.querySelectorAll("#saved-src button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.s === src)));
        if (state.view === "liked") reset();
      }
      return setView("liked");
    }
    case "live": showLivePage(b === "discover" ? "discover" : "following", state.view === "follow"); return setView("follow");
    case "comics": setView("comics"); if (b) showComicId(b, c); return;
    case "dashboard": return setView("dash");
    case "vids": return setView("vids");
    case "personas": return showPersona("");
    case "p": return showPersona(b);
    case "item":
      if (!state.single) return go("personas", true);
      state.openSingle = true; state.persona = "";
      if (state.view === "feed") reset(); else setView("feed");
      return;
    case "room":
      if (!ROOM_NAME.test(b)) break;
      if (c === "watch") return showRoom(roomFor(b), nav.lists.get(b) || null);
      if (c === "video") return showRoomVideo(b, rest.length ? rest.join("/") : "");
      return showPerson({ room: b });
    case "watch": {
      const rooms = b.split("+").filter(n => ROOM_NAME.test(n)).slice(0, MV_MAX).map(roomFor);
      return rooms.length ? showMulti(rooms) : go("live", true);
    }
    case "x": if (b) return showPerson({ x: b }); break;
    case "u": if (b) return showPerson({ reddit: b }); break;
    case "e621": if (b) return showPerson({ e621: b }); break;
    case "bsky": if (b) return showPerson({ bsky: b }); break;
    case "r": if (b) return showBrowse(b, ["new", "top"].includes(c) ? c : "hot"); break;
    case "post": if (b && c) return showPostId(`${b}:${c}`); break;
    case "xvideos": if (b) return showXvideo(nav.xv.get(b) || { id: b, title: "xvideos" }); break;
    case "redgifs": if (/^[a-z]{3,80}$/.test(b)) return showClip(b); break;
    case "videos":
      if (/^\d{5,25}$/.test(b)) return showVideos(b, c);
      if (["reddit", "e621", "bsky"].includes(b) && /^[A-Za-z0-9_]{1,60}$/.test(c)) return showVideos(c, "", b);
      break;
  }
  go("", true);
}
addEventListener("popstate", () => {
  const st = history.state || {};
  if (!viewer.hidden && st.overlay !== "viewer") closeViewer(true);
  if (!$("pic-view").hidden && st.overlay !== "picture") closePicture(true);
  if (st.overlay || here() === nav.routed) return;
  route();
});
// a post's own address, opened by link: your kept copy, or read again from its site
async function showPostId(id) {
  const p = nav.posts.get(id);
  if (p) return showPost(p);
  const gen = ++pv.gen;
  $("pv-title").textContent = "Post"; $("pv-post").replaceChildren(el("p", "note", "Reading the post…"));
  $("pv-h").textContent = ""; $("pv-comments").replaceChildren(); $("post-view").hidden = false;
  try {
    const d = await api(`api/post?id=${enc(id)}`);
    if (gen !== pv.gen) return;
    nav.posts.set(id, d.post); showPost(d.post);
  } catch (err) { if (gen === pv.gen) $("pv-post").replaceChildren(el("p", "note", err.message)); }
}
// one of your videos of a room, by its address
async function showRoomVideo(room, path) {
  let vids = pf.room && pf.room.name === room && pf.videos.length ? pf.videos : null;
  if (!vids) {
    try { vids = (await api(`api/live/videos?name=${enc(room)}`)).videos; } catch (err) { toast(err.message); return go(`room/${enc(room)}`, true); }
  }
  const i = vids.findIndex(v => v.path === path);
  if (i < 0) return go(`room/${enc(room)}`, true);
  pf.room = pf.room && pf.room.name === room ? pf.room : { name: room }; pf.videos = vids;
  pl.mode = "file"; pl.rooms = vids.slice(); pl.i = i; $("player").hidden = false; playFile();
}


