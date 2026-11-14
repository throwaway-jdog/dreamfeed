/* ---------- search ----------
   The 🔍 page (search/WORDS): one search across dreamfeed, each part asked at once and shown as it
   answers: yours (Saved, rooms and comics you follow, history), live rooms, videos, comics,
   subreddits, and posts on X, Bluesky, Reddit and e621. Your mute list applies. */
const se = { q: "", gen: 0, source: "all", cursor: null, loading: false };
function showSearch() {
  $("se-q").value = se.q;
  for (const s of ["se-yours-sec", "se-rooms-sec", "se-vids-sec", "se-comics-sec", "se-subs-sec", "se-posts-sec"]) $(s).hidden = true;
  $("se-note").hidden = !!se.q;
  if (!se.q) { setTimeout(() => $("se-q").focus(), 0); return; }
  const gen = ++se.gen, q = enc(se.q);
  const ask = async (url, show) => {
    let d;
    try { d = await api(url); } catch (err) { return gen === se.gen && show(null, err); }
    if (gen === se.gen) show(d);
  };
  ask(`api/search?in=yours&q=${q}`, d => {
    if (!d) return;
    const box = $("se-yours"), parts = [];
    if (d.rooms.length) {
      const row = el("div", "se-chips");
      for (const r of d.rooms) { const c = el("button", "chip", (r.live ? "● " : "") + r.name); c.type = "button"; c.onclick = () => openRoomProfile(r); row.append(c); }
      parts.push(el("h3", "lday", "Rooms you follow"), row);
    }
    if (d.comics.length) { const row = el("div", "vrow"); row.append(...d.comics.map(c => comicCard(c))); parts.push(el("h3", "lday", "Comics you follow"), row); }
    if (d.saved.length) {
      const list = el("div");
      for (const p of d.saved) list.append(listRow({ title: p.text || `${p.author} on ${p.source}`, body: [p.author, p.place].filter(Boolean).join(" · "),
        thumb: ((p.media || [])[0] || {}).url, label: "Saved", open: () => openPost(p), remove: () => {} }));
      list.querySelectorAll(".lrow-x").forEach(x => x.remove());
      parts.push(el("h3", "lday", "Saved"), list);
    }
    if (d.history.length) {
      const list = el("div");
      for (const it of d.history) list.append(listRow({ title: it.title, thumb: it.thumb, label: `${HI_KIND[it.kind]} · ${dayLabel(it.at)}`, open: () => openHistory(it), remove: () => {} }));
      list.querySelectorAll(".lrow-x").forEach(x => x.remove());
      parts.push(el("h3", "lday", "In your history"), list);
    }
    box.replaceChildren(...parts); $("se-yours-sec").hidden = !parts.length;
  });
  ask(`api/discover/cb?mode=search&q=${q}&gender=&offset=0`, d => {
    const rooms = d ? d.rooms.slice(0, 12) : [];
    $("se-rooms").replaceChildren(...rooms.map(r => liveCard(r, rooms))); $("se-rooms-sec").hidden = !rooms.length;
  });
  ask(`api/vids/search?q=${q}&page=0&length=`, d => {
    const v = d ? d.videos.slice(0, 12) : [];
    $("se-vids").replaceChildren(...v.map(vidCard)); $("se-vids-sec").hidden = !v.length;
  });
  let tags = [];
  Promise.all(["multporn", "e621"].map(site => api(`api/comics/search?q=${q}&page=0&site=${site}`).then(d => { if (d.tags) tags = d.tags; return d.results || []; }, () => [])))
    .then(([a, b]) => {
      if (gen !== se.gen) return;
      const all = [];
      for (let i = 0; i < Math.max(a.length, b.length) && all.length < 12; i++) { if (a[i]) all.push(a[i]); if (b[i]) all.push(b[i]); }
      $("se-ctags").replaceChildren(...tags.map(t => tagChip(t, "multporn", `Browse the tag ${t.name}`))); $("se-ctags").hidden = !tags.length;
      $("se-comics").replaceChildren(...all.map(c => comicCard(c)));
      $("se-comics-sec").hidden = !all.length && !tags.length;
    });
  ask(`api/search?in=subreddits&q=${q}`, d => {
    const subs = d ? d.subreddits : [];
    $("se-subs").replaceChildren(...subs.map(s => {
      const c = el("button", "se-sub"); c.type = "button";
      if (s.icon) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = s.icon; c.append(im); }
      c.append(el("b", null, `r/${s.name}`), el("small", null, [s.subscribers != null && `${Number(s.subscribers).toLocaleString()} members`, s.nsfw && "18+"].filter(Boolean).join(" · ")));
      c.onclick = () => openBrowse(s.name, "hot"); return c;
    }));
    $("se-subs-sec").hidden = !subs.length;
  });
  searchPosts(true);
}
async function searchPosts(fresh) {
  const gen = se.gen;
  if (se.loading && !fresh) return;
  if (fresh) { se.cursor = null; $("se-posts").replaceChildren(); }
  se.loading = true; $("se-more").hidden = true; $("se-posts-sec").hidden = false;
  $("se-posts-note").textContent = "Searching the sites…";
  let d;
  try { d = await api(`api/search?in=posts&q=${enc(se.q)}&source=${se.source}${se.cursor ? `&cursor=${se.cursor}` : ""}`); }
  catch (err) { if (gen === se.gen) { $("se-posts-note").textContent = err.message; se.loading = false; } return; }
  if (gen !== se.gen) return;
  se.loading = false;
  $("se-posts").append(...d.posts.map(p => postCard(p)));
  se.cursor = d.cursor; $("se-more").hidden = !d.cursor;
  const errs = Object.entries(d.errors || {}).map(([s, e]) => `${({ x: "X", bsky: "Bluesky", reddit: "Reddit", e621: "e621" })[s]}: ${e}`);
  $("se-posts-note").textContent = [!$("se-posts").children.length ? "No posts found." : "", ...errs].filter(Boolean).join(" · ");
}
$("se-form").onsubmit = e => {
  e.preventDefault();
  const q = $("se-q").value.trim(); if (!q) return;
  $("se-q").blur(); go(`search/${enc(q)}`, se.q === q);
};
document.querySelectorAll("#se-source button").forEach(b => b.onclick = () => {
  se.source = b.dataset.s;
  document.querySelectorAll("#se-source button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  if (se.q) searchPosts(true);
});
$("se-more").onclick = () => searchPosts(false);
$("se-vids-all").onclick = () => { vs.q = se.q; $("vs-q").value = se.q; go("vids"); };
$("se-comics-all").onclick = () => { cf.q = se.q; $("cs-q").value = se.q; go("comics"); };
