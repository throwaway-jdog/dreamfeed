/* ---------- loading ---------- */
async function reset() {
  state.gen++; state.items = []; state.offset = 0; state.more = true; grid.replaceChildren();
  $("empty").hidden = true; renderProfile(); await loadMore();
}

async function loadMore() {
  if (state.view === "posts") { if (fp.more) loadPosts(false); return; }
  if (["dash", "comics", "follow"].includes(state.view) || state.loading || !state.more) return;
  state.loading = true; $("loading").hidden = false;
  const gen = state.gen;
  try {
    const q = new URLSearchParams({ view: state.view, medium: state.medium, offset: state.offset });
    if (state.view === "liked") q.set("source", state.savedSource);
    if (state.persona && state.view === "feed") q.set("persona", state.persona);
    if (state.single && state.view === "feed") q.set("id", state.single);
    const data = await api(`api/feed?${q}`);
    if (gen !== state.gen) return;
    state.offset += data.items.length; state.more = data.more;
    for (const it of data.items) {
      if (it.post) { const w = el("div", "fposts saved-post"); w.append(postCard(it.post)); grid.append(w); }   // a Feed post you saved
      else addCard(it);
    }
    showEmpty();
    if (state.single && state.openSingle && state.items.length && viewer.hidden) { state.openSingle = false; openViewer(0, true); }
  } catch (e) { if (e.message !== "signed out") toast(e.message); state.more = false; }
  finally { state.loading = false; $("loading").hidden = true; }
}

// Feed videos don't play by themselves: one you start stops when it's scrolled away.
const playObs = new IntersectionObserver(es => {
  for (const e of es) if (!e.isIntersecting || e.intersectionRatio < .2) e.target.pause();
}, { threshold: [0, .2] });

function captionNodes(text) {
  const out = [];
  for (const part of text.split(/(#[\p{L}\p{N}_]+)/u)) {
    if (!part) continue;
    if (part.startsWith("#")) { const t = document.createElement("span"); t.className = "tag"; t.textContent = part; out.push(t); }
    else out.push(document.createTextNode(part));
  }
  return out;
}

function addCard(it) {
  state.items.push(it);
  const card = tpl.content.firstElementChild.cloneNode(true);
  card.dataset.id = it.id; it.el = card;
  const who = it.persona ? (personaOf(it.persona.handle) || it.persona) : { name: "dreamfeed v1" };
  fillAvatar(card.querySelector(".av"), who);
  card.querySelector(".name").textContent = who.name;
  card.querySelector(".handle").textContent = it.persona ? "@" + it.persona.handle : LABEL[it.medium] || "";
  card.querySelector(".time").textContent = "· " + relTime(it.posted);
  const text = card.querySelector(".text");
  if (it.caption) text.append(...captionNodes(it.caption)); else text.hidden = true;
  const wb = card.querySelector(".who-btn");
  if (it.persona) wb.onclick = () => openProfile(it.persona.handle); else wb.disabled = true;
  const media = card.querySelector(".media");
  if (it.kind === "video") {
    const v = document.createElement("video");
    v.muted = true; v.loop = true; v.playsInline = true; v.preload = "none"; v.poster = `thumb/${it.id}`; v.src = `img/${it.id}`;
    media.append(v); playObs.observe(v);
    const b = document.createElement("span"); b.className = "play";
    b.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>' + fmtLen(it.seconds || 5);
    media.append(b);
  } else {
    const img = new Image(); img.alt = it.caption || ""; img.loading = "lazy"; img.decoding = "async"; img.src = `img/${it.id}`;
    media.append(img);
  }
  media.onclick = () => openViewer(state.items.indexOf(it));
  const anim = card.querySelector(".act.anim");
  anim.hidden = it.kind === "video" || !it.persona;
  anim.querySelector("span").textContent = it.animated ? "Again" : "Animate";
  anim.onclick = () => { openViewer(state.items.indexOf(it)); openMotion(); };
  card.querySelector(".act.skip").hidden = state.view === "liked";
  card.querySelector(".act.skip").onclick = () => skip(it);
  card.querySelector(".act.like").onclick = () => toggleLike(it);
  setLiked(it, it.liked);
  grid.append(card);
}

function showEmpty() {
  const e = $("empty");
  if (state.items.length || grid.querySelector(".saved-post")) { e.hidden = true; return; }
  e.hidden = false;
  e.innerHTML = state.view === "liked"
    ? "<strong>Nothing saved yet</strong>Tap the heart on persona posts and Save on Feed posts: they're kept here."
    : state.persona ? "<strong>No posts yet</strong>Their first posts arrive with the next run, or tap Post now."
    : "<strong>Nothing new</strong>New posts arrive after each night's run. You can also start one from the Dashboard.";
}

/* ---------- personas ---------- */
async function loadPeople() {
  try { state.people = (await api("api/personas")).personas; } catch { state.people = []; }
  renderPeople(); renderProfile();
}
function renderPeople() {
  const row = $("people"); row.replaceChildren();
  const all = document.createElement("button"); all.type = "button"; all.className = "who";
  all.setAttribute("aria-pressed", String(!state.persona));
  const dot = document.createElement("span"); dot.className = "av"; dot.textContent = "✦";
  const l = document.createElement("span"); l.textContent = "Everyone";
  all.append(dot, l); all.onclick = () => openProfile(""); row.append(all);
  for (const p of state.people) {
    const b = document.createElement("button"); b.type = "button"; b.className = "who";
    b.setAttribute("aria-pressed", String(state.persona === p.handle));
    const n = document.createElement("span"); n.textContent = p.name;
    b.append(avatarEl("", p), n); b.onclick = () => openProfile(p.handle); row.append(b);
  }
  row.hidden = state.view !== "feed" || !state.people.length;   // a persona's generated posts (Saved has none to pick)
}
function showPersona(handle) {
  if (state.view !== "feed") { state.persona = handle; setView("feed"); return; }
  if (state.persona === handle) return;
  state.persona = handle; renderPeople(); scrollTo({ top: 0 }); reset();
}
function renderProfile() {
  const box = $("profile"), p = state.persona && personaOf(state.persona);
  box.hidden = !(state.view === "feed" && p); if (box.hidden) return;
  box.replaceChildren();
  const back = document.createElement("button"); back.type = "button"; back.className = "back";
  back.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M15 6l-6 6 6 6"/></svg>Everyone';
  back.onclick = () => openProfile("");
  const top = document.createElement("div"); top.className = "top-line";
  const post = document.createElement("button"); post.type = "button"; post.className = "pill-btn solid"; post.textContent = "Post now";
  post.onclick = async () => {
    post.disabled = true;
    try { await api("api/generate", { images: 8, keep: 3, personas: [p.handle] }); toast(`${p.name} is posting. About 2 minutes.`); }
    catch (e) { toast(e.message); }
    post.disabled = false;
  };
  top.append(avatarEl("lg", p), post);
  const name = document.createElement("div");
  const h = document.createElement("h2"); h.textContent = p.name;
  const hd = document.createElement("div"); hd.className = "handle"; hd.textContent = "@" + p.handle;
  name.append(h, hd);
  const bio = document.createElement("p"); bio.className = "bio"; bio.textContent = p.bio;
  const nums = document.createElement("div"); nums.className = "nums";
  nums.innerHTML = `<span><b>${p.posts}</b> posts</span><span><b>${p.likes}</b> liked</span><span>${LABEL[p.medium] || p.medium}</span>`;
  box.append(back, top, name, bio, nums);
}

/* ---------- like / skip ---------- */
function setLiked(it, liked) {
  it.liked = liked;
  const lb = it.el?.querySelector(".act.like");
  if (lb) { lb.setAttribute("aria-pressed", String(liked)); lb.querySelector("span").textContent = liked ? "Liked" : "Like"; }
  if (state.idx >= 0 && state.items[state.idx] === it) $("v-like").setAttribute("aria-pressed", String(liked));
}

async function toggleLike(it) {
  const want = !it.liked; setLiked(it, want);
  try { await api("api/feedback", { id: it.id, action: want ? "like" : "clear" }); refreshSummary(); }
  catch (e) { setLiked(it, !want); toast(e.message); return; }
  if (!want && state.view === "liked") removeItem(it);
}

async function skip(it) {
  const at = state.items.indexOf(it);
  removeItem(it);
  try { await api("api/feedback", { id: it.id, action: "skip" }); refreshSummary(); }
  catch (e) { toast(e.message); reset(); return; }
  toast("Skipped", "Undo", () => unskip(it, at));
  if (state.idx >= 0) { if (!state.items.length) closeViewer(); else showAt(Math.min(at, state.items.length - 1)); }
}

async function unskip(it, at) {
  try { await api("api/feedback", { id: it.id, action: "clear" }); refreshSummary(); }
  catch (e) { toast(e.message); return; }
  if (state.idx >= 0) closeViewer();
  reset();
}

function removeItem(it) {
  const i = state.items.indexOf(it); if (i < 0) return;
  state.items.splice(i, 1); state.offset = Math.max(0, state.offset - 1);
  const el = it.el; el.classList.add("gone");
  setTimeout(() => el.remove(), 200);
  showEmpty();
  if (state.items.length < 8) loadMore();
}

/* ---------- viewer ---------- */
const viewer = $("viewer"), vimg = $("v-img"), vvid = $("v-vid");
function openViewer(i, replace) {
  viewer.hidden = false; document.body.style.overflow = "hidden";
  const it = state.items[i], st = history.state || {};
  if (replace) history.replaceState({ n: st.n || 0, overlay: "viewer" }, "", BASE + `item/${it.id}`);
  else history.pushState({ n: (st.n || 0) + 1, overlay: "viewer" }, "", BASE + `item/${it.id}`);
  showAt(i);
}
function closeViewer(fromPop) {
  if (viewer.hidden) return;
  viewer.hidden = true; document.body.style.overflow = ""; vvid.pause(); const it = state.items[state.idx]; state.idx = -1;
  it?.el.scrollIntoView({ block: "nearest" });
  if (fromPop || history.state?.overlay !== "viewer") return;
  if (history.state.n > 0 && !state.single) history.back(); else go(tabPath("feed"), true);   // (opened from its own address)
}
function showAt(i) {
  if (i < 0 || i >= state.items.length) return;
  state.idx = i; const it = state.items[i];
  if (history.state?.overlay === "viewer") history.replaceState(history.state, "", BASE + `item/${it.id}`);
  closeMotion();
  const isVid = it.kind === "video";
  vimg.hidden = isVid; vvid.hidden = !isVid; $("v-scrub").hidden = !isVid; $("v-seek").value = 0;
  if (isVid) { vimg.removeAttribute("src"); vvid.poster = `thumb/${it.id}`; vvid.src = `img/${it.id}`; vvid.play().catch(() => {}); }
  else { vvid.pause(); vvid.removeAttribute("src"); vvid.load(); vimg.src = `img/${it.id}`; }
  const shown = isVid ? vvid : vimg; shown.style.transform = ""; shown.style.opacity = "";
  const ab = $("v-animate");
  ab.hidden = isVid || !it.persona; ab.disabled = false;
  ab.querySelector("span").textContent = it.animated ? "Animate again" : "Animate";
  $("v-count").textContent = `${it.persona ? it.persona.name : LABEL[it.medium] || ""} · ${i + 1} of ${state.items.length}${state.more ? "+" : ""}`;
  $("v-like").setAttribute("aria-pressed", String(it.liked));
  $("v-skip").hidden = state.view === "liked";
  for (const j of [i + 1, i - 1]) if (state.items[j] && state.items[j].kind !== "video") new Image().src = `img/${state.items[j].id}`;
  if (i >= state.items.length - 4) loadMore();
}
const step = d => showAt(Math.min(Math.max(state.idx + d, 0), state.items.length - 1));
$("v-close").onclick = () => closeViewer();
$("v-prev").onclick = () => step(-1);
$("v-next").onclick = () => step(1);
$("v-like").onclick = () => { const it = state.items[state.idx]; if (it) toggleLike(it); };
$("v-skip").onclick = () => { const it = state.items[state.idx]; if (it) skip(it); };

function flashHeart() { const h = $("v-heart"); h.classList.add("show"); setTimeout(() => h.classList.remove("show"), 450); }
let lastTap = 0;
const onTap = () => {
  const now = Date.now();
  if (now - lastTap < 300) { const it = state.items[state.idx]; if (it && !it.liked) { toggleLike(it); } flashHeart(); }
  lastTap = now;
};
vimg.addEventListener("click", onTap); vvid.addEventListener("click", onTap);

// Scrubber for clips in the viewer: drag to seek, button to pause.
function fmtLen(sec) {
  sec = Math.max(0, Math.round(sec));
  return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const PLAY_ICON = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
const PAUSE_ICON = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>';
let seeking = false;
function showClock() {
  const d = vvid.duration || 0;
  if (!seeking && d) $("v-seek").value = Math.round(vvid.currentTime / d * 1000);
  $("v-time").textContent = d ? `${mmss(vvid.currentTime)} / ${mmss(d)}` : "0:00";
}
function showPP() {
  $("v-pp").innerHTML = vvid.paused ? PLAY_ICON : PAUSE_ICON;
  $("v-pp").setAttribute("aria-label", vvid.paused ? "Play" : "Pause");
}
vvid.addEventListener("timeupdate", showClock); vvid.addEventListener("loadedmetadata", showClock);
vvid.addEventListener("play", showPP); vvid.addEventListener("pause", showPP);
$("v-seek").addEventListener("input", () => {
  seeking = true;
  if (vvid.duration) { vvid.currentTime = $("v-seek").value / 1000 * vvid.duration; showClock(); }
});
$("v-seek").addEventListener("change", () => { seeking = false; });
$("v-pp").onclick = () => { if (vvid.paused) vvid.play().catch(() => {}); else vvid.pause(); };
// Dragging the bar mustn't count as a swipe to the next image or a tap to like.
for (const ev of ["touchstart", "touchmove", "touchend", "click"]) $("v-scrub").addEventListener(ev, e => e.stopPropagation());
showPP();
function closeMotion() { $("motion").hidden = true; }
function openMotion() {
  const it = state.items[state.idx]; if (!it) return;
  $("motion").hidden = false; $("motion-text").value = "";
  $("motion").querySelector('input[name="len"][value="clip"]').checked = true; showMotionTime();
  setTimeout(() => $("motion-text").focus(), 50);
}
const wantScene = () => $("motion").querySelector('input[name="len"]:checked').value === "scene";
async function showSceneActs() {
  const box = $("scene-acts"), it = state.items[state.idx];
  box.replaceChildren(); box.hidden = !wantScene() || !it;
  if (box.hidden) return;
  let info; try { info = await api("api/scene-acts", { id: it.id }); } catch { box.hidden = true; return; }
  for (const s of info.slots) {
    const sel = el("select", "in"); sel.dataset.slot = s.slot;
    const any = el("option", null, "Random"); any.value = ""; sel.append(any);
    for (const o of s.options) { const opt = el("option", null, o); opt.value = o; sel.append(opt); }
    const lab = el("label", "field"); lab.append(el("span", null, s.label), sel); box.append(lab);
  }
}
const scenePicks = () => Object.fromEntries([...$("scene-acts").querySelectorAll("select")].map(s => [s.dataset.slot, s.value]).filter(([, v]) => v));
function showMotionTime() {
  const scene = wantScene();
  showSceneActs();
  $("motion-text").disabled = scene;
  $("motion-time").textContent = scene
    ? "A scene of about 40 seconds: 6 new drawings of these characters, each a looping shot, building to a climax. Needs a post with two characters. About 30 minutes."
    : "Takes about 5 minutes.";
}
$("motion-len").onchange = showMotionTime;
$("v-animate").onclick = openMotion;
$("motion-no").onclick = closeMotion;
$("motion").onsubmit = async e => {
  e.preventDefault();
  const it = state.items[state.idx]; if (!it) return;
  const go = $("motion").querySelector(".go"); go.disabled = true;
  try {
    const scene = wantScene();
    await api("api/animate", scene ? { id: it.id, scene: true, picks: scenePicks() } : { id: it.id, prompt: $("motion-text").value.trim() });
    it.animated = true;
    closeMotion();
    $("v-animate").querySelector("span").textContent = "Animate again";
    const ab = it.el?.querySelector(".act.anim span"); if (ab) ab.textContent = "Again";
    toast(scene ? "Making a scene. It takes about 30 minutes and shows up in the feed when it's done."
      : "Animating. The clip shows up in the feed in a few minutes.");
  } catch (err) { toast(err.message); }
  go.disabled = false;
};

let touch = null;
$("stage").addEventListener("touchstart", e => {
  if (e.touches.length !== 1 || !$("motion").hidden) { touch = null; return; }
  touch = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
}, { passive: true });
$("stage").addEventListener("touchmove", e => {
  if (!touch || e.touches.length !== 1) return;
  const dx = e.touches[0].clientX - touch.x, dy = e.touches[0].clientY - touch.y;
  const el = vvid.hidden ? vimg : vvid;
  if (Math.abs(dy) > Math.abs(dx) && dy > 0) { el.style.transform = `translateY(${dy}px)`; el.style.opacity = String(1 - Math.min(dy / 400, .6)); }
  else el.style.transform = `translateX(${dx * .6}px)`;
}, { passive: true });
$("stage").addEventListener("touchend", e => {
  if (!touch) return;
  const dx = e.changedTouches[0].clientX - touch.x, dy = e.changedTouches[0].clientY - touch.y; touch = null;
  if (dy > 90 && Math.abs(dy) > Math.abs(dx)) return closeViewer();
  for (const el of [vimg, vvid]) { el.style.transform = ""; el.style.opacity = ""; }
  if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) step(dx < 0 ? 1 : -1);
});
addEventListener("keydown", e => {
  if (viewer.hidden) return;
  if (!$("motion").hidden) { if (e.key === "Escape") closeMotion(); return; }
  const it = state.items[state.idx];
  if (e.target === $("v-seek") && e.key !== "Escape") return;   // arrows move the scrubber
  if (e.key === "Escape") closeViewer();
  else if (e.key === "ArrowRight") step(1);
  else if (e.key === "ArrowLeft") step(-1);
  else if (e.key.toLowerCase() === "l" && it) toggleLike(it);
  else if (e.key.toLowerCase() === "s" && it && state.view === "feed") skip(it);
});

