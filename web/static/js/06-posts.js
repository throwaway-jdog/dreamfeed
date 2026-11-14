/* Browse now: a subreddit as it is now, read live (25 posts a page). */
const br = { sub: "", sort: "hot", after: "", gen: 0, loading: false };
$("br-form").onsubmit = e => { e.preventDefault(); const v = $("br-sub").value.trim(); if (v) openBrowse(v, $("br-sort").value); };
async function loadRecentBrowses() {
  try {
    const d = await api("api/reddit/browses");
    $("br-recent").replaceChildren(...d.browses.map(b => {
      const c = el("button", null, `r/${b.sub} · ${{ hot: "Hot", new: "New", top: "Top" }[b.sort]}`); c.type = "button";
      c.onclick = () => openBrowse(b.sub, b.sort); return c;
    }));
  } catch {}
}
document.querySelectorAll("#br-sorts button").forEach(b => b.onclick = () => openBrowse(br.sub, b.dataset.o));
function showBrowse(sub, sort) {
  sub = sub.replace(/^\/?r\//i, "").replace(/\/$/, "");
  br.gen++; br.sub = sub; br.sort = sort; br.after = ""; br.loading = false;
  document.querySelectorAll("#br-sorts button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.o === sort)));
  $("br-title").textContent = `r/${sub}`; $("br-open").href = `https://www.reddit.com/r/${encodeURIComponent(sub)}/${sort === "top" ? "top/?t=day" : sort + "/"}`;
  $("br-posts").replaceChildren(); $("br-more").hidden = true;
  $("browse").hidden = false; $("browse").scrollTop = 0;
  moreBrowse();
}
async function moreBrowse() {
  if (br.loading) return;
  const gen = br.gen; br.loading = true; $("br-more").hidden = true; $("br-status").textContent = "Asking Reddit…";
  try {
    const d = await api(`api/reddit/browse?sub=${encodeURIComponent(br.sub)}&sort=${br.sort}&after=${encodeURIComponent(br.after)}`);
    if (gen !== br.gen) return;
    $("br-posts").append(...d.posts.map(postCard));
    br.after = d.after || ""; $("br-more").hidden = !d.after;
    $("br-status").textContent = $("br-posts").children.length ? "" : "No pictures or videos here.";
    if (!br.after && br.sub) loadRecentBrowses();
  } catch (err) { if (gen === br.gen) $("br-status").textContent = err.message; }
  finally { if (gen === br.gen) br.loading = false; }
}
$("br-more").onclick = moreBrowse;
// A post, opened: the post and its comments, read live from its site.
const pv = { gen: 0 };
async function showPost(p) {
  const gen = ++pv.gen;
  $("pv-title").textContent = { x: "Post on X", reddit: p.place ? `r/${p.place}` : "Reddit", e621: "e621" }[p.source] || "Post";
  $("pv-post").replaceChildren(postCard(p, true));
  $("pv-h").textContent = { x: "Replies", reddit: "Comments", e621: "Comments" }[p.source] || "Comments";
  $("pv-comments").replaceChildren(el("p", "note", "Reading the comments…"));
  $("post-view").hidden = false; $("post-view").scrollTop = 0;
  const m0 = (p.media || [])[0] || {};
  noteHistory("post", p.id, p.text || `${p.author || ""} on ${({ x: "X", bsky: "Bluesky", reddit: "Reddit", e621: "e621" })[p.source] || p.source}`,
              postPath(p.id), m0.kind === "image" ? m0.url : m0.poster || null, p);
  let d;
  try { d = await api(`api/post/comments?id=${encodeURIComponent(p.id)}`); }
  catch (err) { if (gen === pv.gen) $("pv-comments").replaceChildren(el("p", "note", err.message)); return; }
  if (gen !== pv.gen) return;
  const count = cs => cs.reduce((n, c) => n + 1 + count(c.replies), 0), n = count(d.comments);
  $("pv-h").textContent += n ? ` · ${n.toLocaleString()}` : "";
  $("pv-comments").replaceChildren(...(n ? d.comments.map(c => commentEl(c, p.source)) : [el("p", "note", "No comments yet.")]));
}
function commentEl(c, source) {
  const box = el("div", "cm"), av = el("span", "av", c.avatar ? null : (c.author || "?").slice(0, 1).toUpperCase()), main = el("div");
  if (c.avatar) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = c.avatar; av.append(im); }
  const head = el("div", "cm-head"), who = el("b", null, c.author || "?");
  const person = source === "x" ? { x: c.author } : source === "reddit" && c.author !== "[deleted]" ? { reddit: c.author } : null;
  if (person && c.author) { who.classList.add("who"); who.onclick = av.onclick = () => openPerson(person); }
  const score = c.score == null ? "" : source === "x" ? `${c.score} ♥` : `${c.score} pts`;
  head.append(who, el("small", null, [relTime(c.at), score].filter(Boolean).join(" · ")));
  main.append(head);
  if (c.text) main.append(el("p", "cm-text", c.text));
  if ((c.media || []).length) {
    const m = el("div", "cm-media");
    for (const u of c.media) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = viaUs(u); m.append(im); }
    main.append(m);
  }
  box.append(av, main);
  if ((c.replies || []).length) { const r = el("div", "cm-replies"); r.append(...c.replies.map(x => commentEl(x, source))); box.append(r); }
  return box;
}
function openPicture(src) {
  $("pic-img").src = src; $("pic-view").hidden = false;
  history.pushState({ n: ((history.state || {}).n || 0) + 1, overlay: "picture" }, "", location.href);
}
function closePicture(fromPop) {
  if ($("pic-view").hidden) return;
  $("pic-view").hidden = true; $("pic-img").removeAttribute("src");
  if (!fromPop && history.state?.overlay === "picture") history.back();
}
$("pic-view").onclick = () => closePicture();
function closePost() { pv.gen++; $("post-view").hidden = true; $("pv-post").replaceChildren(); $("pv-comments").replaceChildren(); }
$("pv-close").onclick = leave;
// 🎲: a random subreddit from your list (one with posts now); Another from its page replaces it.
async function randomBrowse(btn, replace) {
  const was = btn.textContent; btn.disabled = true; btn.textContent = "🎲 …";
  try {
    const d = await api(`api/reddit/random?not=${encodeURIComponent(replace && br.sub || "")}`);
    go(`r/${encodeURIComponent(d.sub)}`, replace);
  } catch (err) { toast(err.message); }
  finally { btn.disabled = false; btn.textContent = was; }
}
$("br-random").onclick = e => randomBrowse(e.currentTarget, false);
$("br-another").onclick = e => randomBrowse(e.currentTarget, true);
function closeBrowse() { br.gen++; $("browse").hidden = true; for (const v of $("br-posts").querySelectorAll("video")) v.pause(); }
$("br-close").onclick = leave;
function postCard(p, opened) {
  const a = el("article", "post"), body = el("div"), head = el("div", "head");
  const canOpen = !opened && /^(x|reddit|e621|bsky):/.test(String(p.id || ""));
  const av = el("span", "av sm", p.avatar ? null : (p.author || "?").slice(0, 1).toUpperCase());
  if (p.avatar) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = p.avatar; av.append(im); }
  // whose profile the name opens: X's and Reddit's author, e621's (first) artist
  const person = p.source === "x" && p.author ? { x: p.author } : p.source === "reddit" && p.author ? { reddit: p.author }
    : p.source === "bsky" && p.author ? { bsky: p.author }
    : p.source === "e621" && (p.artists || []).length ? { e621: p.artists[0] } : null;
  if (p.source === "reddit" && p.avatar && p.place) { av.style.cursor = "pointer"; av.onclick = () => openBrowse(p.place, "hot"); }
  else if (person) { av.style.cursor = "pointer"; av.onclick = () => openPerson(person); }
  const who = el("span", "name", p.source === "bsky" ? p.nick || p.author || "?" : p.author || "?");
  if (person) { who.classList.add("who"); who.onclick = () => openPerson(person); }
  head.append(who,
              (() => { const w = el("span", "where", p.source === "reddit" ? `r/${p.place}` : p.source === "e621" ? `e621 · ${p.place || ""}` : p.source === "bsky" ? `Bluesky · ${p.place || "@" + p.author}` : "X");
                       if (p.source === "reddit" && p.place) { w.classList.add("go"); w.onclick = () => openBrowse(p.place, "hot"); }
                       return w; })(),
              el("span", "time", "· " + relTime(p.posted_at)));
  body.append(head);
  if (p.text) {
    const t = el("p", "text", p.text); body.append(t);
    if (canOpen) { t.classList.add("go"); t.onclick = () => openPost(p); }
  }
  // pictures and videos: several swipe sideways (n / N); a video plays when you start it;
  // opened, a post shows its pictures in full quality and a tap shows one full screen
  const boxes = p.media.map(m => {
    const box = el("div", "media");
    if (m.kind === "video" || m.kind === "hls") {
      const v = el("video"); v.controls = v.loop = v.playsInline = true; v.preload = "none";
      if (m.poster) v.poster = viaUs(m.poster);
      if (m.kind === "video") v.src = viaUs(m.url); else feedHls(v, m);
      box.append(v); playObs.observe(v);
    } else {
      const img = el("img"); img.alt = ""; img.loading = "lazy"; img.src = viaUs(opened && m.full ? m.full : m.url); box.append(img);
      if (opened && m.full) img.onerror = () => { if (!img.src.endsWith(viaUs(m.url))) img.src = viaUs(m.url); };
      if (canOpen) { box.classList.add("go"); box.onclick = () => openPost(p); }
      else if (opened) { box.classList.add("go"); box.onclick = () => openPicture(img.src); }
    }
    return box;
  });
  if (boxes.length > 1) {
    const strip = el("div", "gallery"), count = el("span", "g-count", `1 / ${boxes.length}`), wrap = el("div", "g-wrap");
    strip.append(...boxes);
    strip.addEventListener("scroll", () => { count.textContent = `${Math.round(strip.scrollLeft / strip.clientWidth) + 1} / ${boxes.length}`; }, { passive: true });
    wrap.append(strip, count); body.append(wrap);
  } else body.append(...boxes);
  const acts = el("div", "acts");
  if (canOpen) {
    const c = el("button", "comments-btn", p.comments ? `💬 ${Number(p.comments).toLocaleString()}` : "💬 Comments");
    c.type = "button"; c.onclick = () => openPost(p); acts.append(c);
  }
  if (["x", "reddit", "e621", "bsky"].includes(p.source) && p.media.some(m => m.kind === "video" || m.kind === "hls")) {   // a swipe-up feed, from this one
    const mv = el("button", "comments-btn", "▶ More videos"); mv.type = "button"; mv.onclick = () => openVideos(p); acts.append(mv);
  }
  if (p.link) {
    const out = el("a", "out", { reddit: "Open on Reddit", e621: "Open on e621", bsky: "Open on Bluesky" }[p.source] || "Open on X");
    out.href = p.link; out.target = "_blank"; out.rel = "noreferrer noopener"; acts.append(out);
  }
  if (p.id != null) {
    const sv = el("button", "save"), note = el("small"); sv.type = "button";
    const show = () => {
      sv.textContent = p.saved ? "★ Saved" : "☆ Save"; sv.setAttribute("aria-pressed", String(p.saved));
      const y = p.sync || {}, k = p.keep || {};
      const kept = !p.saved ? "" : k.status === "done" ? "kept in full quality" : k.status === "failed" ? `not kept: ${k.error || "?"}`
        : k.status ? "keeping a full-quality copy…" : "";
      const site = p.source === "e621" ? "e621" : "Reddit";
      note.textContent = [y.status === "failed" ? y.error || `${site} didn't take it` : y.status === "done" ? (p.saved ? (p.source === "e621" ? "favorited on e621 too" : "saved on Reddit too") : p.source === "e621" ? "unfavorited on e621" : "") : "",
                          kept].filter(Boolean).join(" · ");
    };
    sv.onclick = async () => {
      sv.disabled = true;
      try { const d = await api("api/following/save", { post: p, save: !p.saved }); p.saved = d.saved; p.sync = d.sync; p.keep = d.keep; }
      catch (err) { toast(err.message); }
      finally { sv.disabled = false; }
      show();
    };
    show(); acts.append(sv, note);
  }
  if (p.source === "e621" && p.votable) {          // signed in to e621: vote on it (the same again takes it back)
    const vote = el("span", "e6-vote"), up = el("button", "secondary", "▲"), down = el("button", "secondary", "▼"), n = el("small", null, String(p.score ?? ""));
    up.type = down.type = "button"; up.title = "Vote up on e621"; down.title = "Vote down on e621";
    const mark = () => { up.setAttribute("aria-pressed", String(p.ours === 1)); down.setAttribute("aria-pressed", String(p.ours === -1)); n.textContent = String(p.score ?? ""); };
    const cast = async s => {
      up.disabled = down.disabled = true;
      try { const r = await api("api/e621/vote", { id: p.id, score: s }); p.score = r.score; p.ours = r.ours; } catch (err) { toast(err.message); }
      up.disabled = down.disabled = false; mark();
    };
    up.onclick = () => cast(1); down.onclick = () => cast(-1);
    mark(); vote.append(up, n, down); acts.append(vote);
  }
  if (canOpen) acts.append(muteButton(p, a));
  body.append(acts);
  a.append(av, body);
  return a;
}
