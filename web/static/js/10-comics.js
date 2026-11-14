/* ---------- comics ----------
   Comics, a feed like the rest: Updated (comics you follow, with new pages), Continue reading,
   multporn's New and Updated comics, Browse by tag (multporn's or e621's), For you (from what you read and follow here, and your e621 taste: each says why), Following,
   search (multporn, e621), and Your comics (kept here before). Read in the reader: live ones
   straight from the site, page by page; where you are is remembered, and Follow brings their new
   pages back here. Addresses: comics, comics/new, comics/updated, comics/tag/TAG[/e621], comics/e621/POOL, comics/mp/SLUG, comics/N (yours). */
const cf = { offset: 0, more: false, q: "", page: 0, site: "multporn", loading: false, gen: 0 };
try { const s = localStorage.getItem("comicSite"); if (["multporn", "e621"].includes(s)) cf.site = s; } catch {}
$("cs-site").value = cf.site;
const comicPath = c => typeof c.id === "number" || /^\d+$/.test(String(c.id)) ? `comics/${c.id}` : `comics/${String(c.id).replace(":", "/")}`;
function comicCard(c, extra) {
  const b = el("button", "comic-card"); b.type = "button";
  const img = el("img"); img.alt = ""; img.loading = "lazy"; img.referrerPolicy = "no-referrer";
  if (c.thumb || c.cover) img.src = viaUs(c.thumb || c.cover); else if (typeof c.id === "number") img.src = `comic/${c.id}/1/thumb`;
  b.append(img, el("b", null, c.title || "Untitled"));
  const about = [c.source === "e621" ? "e621" : c.source === "multporn" ? "multporn" : "", c.pages && `${c.pages} pages`, extra].filter(Boolean).join(" · ");
  if (about) b.append(el("small", null, about));
  if (c.why) b.append(el("small", "why", c.why));
  b.onclick = () => openComic(c);
  return b;
}
function openComic(c) { nav.comics = nav.comics || new Map(); nav.comics.set(String(c.id), c); go(comicPath(c)); }
// What the grid shows: For you, a search, or a list (multporn's New or Updated, a tag's comics).
const C_LIST = { new: "New on multporn", updated: "Updated on multporn" };
const C_SORT = { multporn: ["Newest", "Most viewed", "Top rated"], e621: ["Newest", "Top score", "Most favorited"] };
const gridMode = () => cf.list ? "list" : cf.q ? "search" : "foryou";
async function loadComics(more) {
  const gen = more ? cf.gen : ++cf.gen;
  if (cf.loading && more) return;
  cf.loading = true; $("cg-more").hidden = true;
  const mode = gridMode(), l = cf.list, home = mode === "foryou";
  $("cg-title").textContent = mode === "search" ? `“${cf.q}” on ${cf.site}` : !l ? "For you"
    : l.list === "tag" ? `${l.name || l.tag.replace(/_/g, " ")}${l.site === "e621" ? " on e621" : ""}` : C_LIST[l.list];
  $("cg-back").hidden = home; $("cg-back").textContent = mode === "search" ? "Back to For you" : "Back to comics";
  $("cg-bar").hidden = !(l && l.list === "tag");
  if (l && l.list === "tag") { $("cg-sort").value = l.sort; [...$("cg-sort").options].forEach((o, i) => o.textContent = C_SORT[l.site][i]); }
  for (const s of ["cu-sec", "cc-sec", "cf-sec", "cl-sec", "cn-sec", "cw-sec"]) if (!home) $(s).hidden = true;
  $("ct-sec").hidden = !home;
  if (!more) {
    cf.offset = 0; cf.page = 0; $("cg").replaceChildren(); $("cg-tags").hidden = true;
    $("cg-note").textContent = mode === "search" ? "Searching…" : mode === "list" ? "Looking…" : "Finding comics for you…";
    if (home) { loadComicRows(gen); loadTags(); }
  }
  let d;
  try {
    d = mode === "search" ? await api(`api/comics/search?q=${encodeURIComponent(cf.q)}&page=${cf.page}&site=${cf.site}`)
      : mode === "list" ? await api(`api/comics/browse?list=${l.list}&tag=${encodeURIComponent(l.tag || "")}&sort=${l.sort}&site=${l.site}&page=${cf.page}`)
      : await api(`api/comics/feed?offset=${cf.offset}`);
  } catch (err) { if (gen === cf.gen) { $("cg-note").textContent = err.message; cf.loading = false; } return; }
  if (gen !== cf.gen) return;
  cf.loading = false;
  const list = (home ? d.comics : d.results) || [];
  if (!more && home) {
    const row = (sec, id, items, extra) => { $(sec).hidden = !items.length; $(id).replaceChildren(...items.map(c => comicCard(c, extra(c)))); };
    row("cu-sec", "cu-row", d.updated || [], c => `${c.new} new page${c.new === 1 ? "" : "s"}`);
    row("cc-sec", "cc-row", d.continue || [], c => `page ${c.page} of ${c.pages}`);
    row("cf-sec", "cf-row", d.following || [], () => "");
    $("cl-sec").hidden = !(d.library || []).length;
    $("c-list").replaceChildren(...(d.library || []).map(c => comicCard(c, c.imported ? "imported" : "made here")));
    cf.taste = (d.taste || {}).tags || []; showTagChips();
  }
  if (!more && mode === "search" && (d.tags || []).length) {   // the search names a tag: browse it
    $("cg-tags").replaceChildren(...d.tags.map(t => tagChip(t, "multporn", `Browse the tag ${t.name}`))); $("cg-tags").hidden = false;
  }
  if (!more && mode === "list" && d.tag && d.tag.name) { l.name = d.tag.name; $("cg-title").textContent = `${d.tag.name}${l.site === "e621" ? " on e621" : ""}`; }
  $("cg").append(...list.map(c => comicCard(c, c.posted && l && l.list === "new" ? ago(c.posted) : "")));
  const t = d.taste || {};
  $("cg-note").textContent = mode !== "foryou" ? (!$("cg").children.length ? "Nothing found." : "")
    : !$("cg").children.length ? "Nothing yet." : t.n ? `From what you read and follow here${t.tags && t.tags.length ? ": " + t.tags.slice(0, 6).join(", ") : ""}.`
    : "To start, what's new on e621 and multporn (and your e621 taste). It learns from what you read and follow.";
  $("cg-more").hidden = !d.more;
  if (home) cf.offset += list.length; else cf.page++;
}
function ago(t) {
  const s = (Date.now() - Date.parse(t.replace(" ", "T") + "Z")) / 1000;
  return !(s >= 0) ? "" : s < 3600 ? "new" : s < 86400 ? `${Math.floor(s / 3600)} h ago` : s < 30 * 86400 ? `${Math.floor(s / 86400)} d ago` : "";
}
// New and Updated on multporn, as rows over For you (See all: the whole list, page by page)
function loadComicRows(gen) {
  for (const [which, sec, row] of [["new", "cn-sec", "cn-row"], ["updated", "cw-sec", "cw-row"]]) {
    api(`api/comics/browse?list=${which}&page=0`).then(d => {
      if (gen !== cf.gen) return;
      const items = (d.results || []).slice(0, 16);
      $(row).replaceChildren(...items.map(c => comicCard(c, which === "new" && c.posted ? ago(c.posted) : "")));
      $(sec).hidden = !items.length;
    }, () => { if (gen === cf.gen) $(sec).hidden = true; });
  }
}
const tagPath = (tag, site) => `comics/tag/${encodeURIComponent(tag)}${site === "e621" ? "/e621" : ""}`;
function tagChip(t, site, label) {
  const c = el("button", "chip", label || t.name); c.type = "button"; c.onclick = () => go(tagPath(t.tag, site)); return c;
}
// multporn's tags: yours first (the tags of what you read), then A to Z
async function loadTags() {
  if (!cf.tags) {
    try { cf.tags = (await api("api/comics/tags")).tags || []; } catch { cf.tags = null; return; }
    $("ct-list").replaceChildren(...cf.tags.map(t => { const o = el("option"); o.value = t.name; return o; }));
  }
  showTagChips();
}
function showTagChips() {
  if (!cf.tags) return;
  const mine = new Set((cf.taste || []).map(g => g.toLowerCase()));
  const yours = cf.tags.filter(t => mine.has(t.name.toLowerCase()));
  $("ct-chips").replaceChildren(...[...yours, ...cf.tags.filter(t => !yours.includes(t))].map(t => tagChip(t, "multporn")));
  $("ct-more").hidden = false; $("ct-more").textContent = $("ct-chips").classList.contains("short") ? "All tags" : "Fewer";
}
$("ct-more").onclick = () => { $("ct-chips").classList.toggle("short"); showTagChips(); };
$("ct-form").onsubmit = e => {
  e.preventDefault();
  const q = $("ct-q").value.trim().toLowerCase(), site = $("ct-site").value; if (!q) return;
  const known = (cf.tags || []).find(t => t.name.toLowerCase() === q);
  $("ct-q").blur(); go(tagPath(known ? known.tag : q.replace(/[^a-z0-9()\-.'!]+/g, "_").replace(/^_+|_+$/g, ""), site));
};
// comics, comics/new, comics/updated, comics/tag/TAG[/e621]; or one comic (comics/e621/POOL, comics/mp/SLUG, comics/N)
function showComicsAt(b, c, rest) {
  const list = b === "new" || b === "updated" ? { list: b, tag: "", site: "multporn" }
    : b === "tag" && c ? { list: "tag", tag: c, site: rest[0] === "e621" ? "e621" : "multporn" } : null;
  if (b && !list) { setView("comics"); return showComicId(b, c); }
  const key = l => l ? `${l.list}:${l.tag}:${l.site}` : "";
  const same = key(list) === key(cf.list);
  if (!same) {
    cf.list = list && { ...list, sort: (cf.sorts || {})[key(list)] || "new" };
    if (list) cf.q = "";
  }
  if (state.view !== "comics") setView("comics");
  else if (!same) loadComics();
}
$("cn-all").onclick = () => go("comics/new");
$("cw-all").onclick = () => go("comics/updated");
$("cg-sort").onchange = () => {
  const l = cf.list; if (!l) return;
  l.sort = $("cg-sort").value; cf.sorts = { ...cf.sorts, [`${l.list}:${l.tag}:${l.site}`]: l.sort }; loadComics();
};
$("cs-form").onsubmit = e => {
  e.preventDefault(); cf.q = $("cs-q").value.trim();
  if (cf.list) { cf.list = null; go("comics"); if (!cf.q) return; }
  loadComics();
};
$("cs-site").onchange = () => { cf.site = $("cs-site").value; remember("comicSite", cf.site); if (cf.q && !cf.list) loadComics(); };
$("cg-more").onclick = () => loadComics(true);
$("cg-back").onclick = () => { if (cf.list) return go("comics"); cf.q = ""; $("cs-q").value = ""; loadComics(); };

// The reader: one page a screen (swipe, arrows), or a grid of every page.
const rd = { c: null, page: 1, grid: false, wraps: [], timer: null };
const pageSrc = (c, n, thumb) => c.images ? viaUs((c.images[n - 1] || {}).url) : `comic/${c.id}/${n}${thumb ? "/thumb" : ""}`;
function showComic(c) {
  Object.assign(rd, { c, page: Math.max(1, Math.min(c.page || 1, c.images ? c.images.length : c.pages)), grid: false });
  $("reader-title").textContent = c.title || "Untitled";
  const live = !!c.images;
  $("reader-follow").hidden = !live; $("reader-open").hidden = !live || !c.link;
  if (live) { $("reader-open").href = c.link; markFollow(); }
  $("rd-msg").hidden = !(c.new_from); $("rd-msg").textContent = c.new_from ? `New since you last read: from page ${c.new_from}.` : "";
  $("reader").hidden = false;
  buildSlides(); showView(); goTo(rd.page, true);
}
function markFollow() { const f = !!rd.c.followed; $("reader-follow").textContent = f ? "Following ✓" : "Follow"; $("reader-follow").setAttribute("aria-pressed", String(f)); }
$("reader-follow").onclick = async () => {
  const c = rd.c; if (!c) return;
  $("reader-follow").disabled = true;
  try { c.followed = (await api("api/comics/follow", { id: c.id, follow: !c.followed })).followed; markFollow();
        toast(c.followed ? "Following: its new pages come in Comics, under Updated." : "Not following it."); }
  catch (err) { toast(err.message); }
  $("reader-follow").disabled = false;
};
function closeComic() {
  if (rd.c && rd.c.images) sendProgress();
  clearTimeout(rd.timer); $("reader").hidden = true; rd.c = null; $("rd-track").replaceChildren(); $("rd-grid").replaceChildren();
  if (state.view === "comics" && gridMode() === "foryou") loadComics();
}
const pageCount = () => rd.c.images ? rd.c.images.length : rd.c.pages;
function buildSlides() {
  const c = rd.c, track = $("rd-track"); track.replaceChildren(); rd.wraps = [];
  for (let n = 1; n <= pageCount(); n++) {
    const slide = el("div", "rd-slide"), wrap = el("div", "rpage"), img = el("img");
    img.alt = `Page ${n}`; img.loading = Math.abs(n - rd.page) <= 1 ? "eager" : "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    img.src = pageSrc(c, n);
    img.onload = () => fit(wrap, img);
    if (c.images && c.images[n - 1] && c.images[n - 1].full !== c.images[n - 1].url) {
      img.onerror = () => { const full = viaUs(c.images[n - 1].full); if (!img.src.endsWith(full)) img.src = full; };   // (the full size if the smaller isn't there)
    }
    wrap.append(img); slide.append(wrap); track.append(slide); rd.wraps.push(wrap);
  }
}
function fit(wrap, img) {   // the page as large as fits its slide
  const slide = wrap.parentNode, nw = img.naturalWidth, nh = img.naturalHeight;
  if (!nw || !nh || !slide) return;
  const r = Math.min((slide.clientWidth - 16) / nw, (slide.clientHeight - 16) / nh);
  wrap.style.width = `${Math.floor(nw * r)}px`; wrap.style.height = `${Math.floor(nh * r)}px`;
}
function refit() { rd.wraps.forEach(w => fit(w, w.querySelector("img"))); goTo(rd.page, true); }
addEventListener("resize", () => { if (rd.c) refit(); });
function goTo(n, instant) {
  n = Math.max(1, Math.min(pageCount(), n)); rd.page = n;
  const track = $("rd-track");
  track.scrollTo({ left: (n - 1) * track.clientWidth, behavior: instant ? "instant" : "smooth" });
  showCount();
}
function sendProgress() {
  const c = rd.c; if (!c || !c.images) return;
  api("api/comics/progress", { id: c.id, page: rd.page }).catch(() => {});
}
function showCount() {
  for (const k of [rd.page - 1, rd.page, rd.page + 1]) {   // this page and its neighbours load now
    const img = rd.wraps[k - 1]?.querySelector("img"); if (img && img.loading !== "eager") img.loading = "eager";
  }
  $("rd-count").textContent = `${rd.page} / ${pageCount()}`;
  $("rd-prev").disabled = rd.page <= 1; $("rd-next").disabled = rd.page >= pageCount();
  clearTimeout(rd.timer); rd.timer = setTimeout(sendProgress, 1500);   // (where you are: told once you've settled on a page)
}
$("rd-track").addEventListener("scroll", () => {   // a swipe moved the page: keep the counter up to date
  const t = $("rd-track"), n = Math.round(t.scrollLeft / Math.max(1, t.clientWidth)) + 1;
  if (n !== rd.page && rd.c) { rd.page = n; showCount(); }
}, { passive: true });
$("rd-prev").onclick = () => goTo(rd.page - 1);
$("rd-next").onclick = () => goTo(rd.page + 1);
function showView() {
  const g = rd.grid;
  $("rd-track").hidden = g; $("rd-grid").hidden = !g; $("rd-foot").hidden = g;
  $("reader-view").textContent = g ? "Pages" : "Grid"; $("reader-view").setAttribute("aria-pressed", String(g));
  if (g) buildGrid();
}
function buildGrid() {
  const c = rd.c, grid = $("rd-grid"); grid.replaceChildren();
  for (let n = 1; n <= pageCount(); n++) {
    const b = el("button"), img = el("img"); b.type = "button";
    img.alt = ""; img.loading = "lazy"; img.referrerPolicy = "no-referrer"; img.src = pageSrc(c, n, true);
    b.append(img, el("span", null, String(n)));
    if (n === rd.page) b.setAttribute("aria-current", "true");
    b.onclick = () => { rd.grid = false; showView(); goTo(n, true); };
    grid.append(b);
  }
  if (!c.images) {         // one of yours: rename it, delete it
    const ren = el("button", "secondary del", "Rename"); ren.type = "button";
    ren.onclick = async () => {
      const t = prompt("Title", c.title || ""); if (!t) return;
      try { c.title = (await api("api/comics/rename", { id: c.id, title: t })).title; $("reader-title").textContent = c.title; } catch (err) { toast(err.message); }
    };
    const del = el("button", "secondary del", "Delete this comic"); del.type = "button";
    del.onclick = async () => {
      if (!confirm("Delete this comic?")) return;
      try { await api("api/comics/delete", { id: c.id }); go("comics", true); } catch (err) { toast(err.message); }
    };
    grid.append(ren, del);
  }
  grid.querySelector('[aria-current="true"]')?.scrollIntoView({ block: "center" });
}
$("reader-view").onclick = () => { rd.grid = !rd.grid; showView(); if (!rd.grid) goTo(rd.page, true); };
$("reader-close").onclick = leave;
document.addEventListener("keydown", e => {
  if ($("reader").hidden || rd.grid) return;
  if (e.key === "ArrowLeft") goTo(rd.page - 1); else if (e.key === "ArrowRight") goTo(rd.page + 1); else if (e.key === "Escape") leave();
});
// a comic by its address: one of yours (comics/N), or live (comics/e621/POOL, comics/mp/SLUG)
async function showComicId(a, b) {
  const want = here();
  try {
    if (/^\d+$/.test(a)) {
      const d = await api("api/comics");
      const c = d.comics.find(x => String(x.id) === a);
      if (!c) return go("comics", true);
      if (here() === want) showComic(c);
      return;
    }
    if (!["e621", "mp"].includes(a) || !b) return go("comics", true);
    const known = (nav.comics || new Map()).get(`${a}:${b}`);
    if (known) { $("reader-title").textContent = known.title || ""; }
    const c = await api(`api/comics/read?id=${encodeURIComponent(`${a}:${b}`)}`);
    if (here() === want) showComic(c);
  } catch (err) { toast(err.message); if (here() === want) go("comics", true); }
}
