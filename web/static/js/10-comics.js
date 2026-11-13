/* ---------- comics ----------
   Comics, a feed like the rest: Updated (comics you follow, with new pages), Continue reading,
   For you (from what you read and follow here, and your e621 taste: each says why), Following,
   search (multporn, e621), and Your comics (kept here before). Read in the reader: live ones
   straight from the site, page by page; where you are is remembered, and Follow brings their new
   pages back here. Addresses: comics, comics/e621/POOL, comics/mp/SLUG, comics/N (yours). */
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
async function loadComics(more) {
  const gen = more ? cf.gen : ++cf.gen;
  if (cf.loading && more) return;
  cf.loading = true; $("cg-more").hidden = true;
  const searching = !!cf.q;
  $("cg-title").textContent = searching ? `“${cf.q}” on ${cf.site}` : "For you"; $("cg-back").hidden = !searching;
  for (const s of ["cu-sec", "cc-sec", "cf-sec", "cl-sec"]) if (searching) $(s).hidden = true;
  if (!more) { cf.offset = 0; cf.page = 0; $("cg").replaceChildren(); $("cg-note").textContent = searching ? "Searching…" : "Finding comics for you…"; }
  let d;
  try {
    d = searching ? await api(`api/comics/search?q=${encodeURIComponent(cf.q)}&page=${cf.page}&site=${cf.site}`)
                  : await api(`api/comics/feed?offset=${cf.offset}`);
  } catch (err) { if (gen === cf.gen) { $("cg-note").textContent = err.message; cf.loading = false; } return; }
  if (gen !== cf.gen) return;
  cf.loading = false;
  const list = searching ? d.results : d.comics;
  if (!more && !searching) {
    const row = (sec, id, items, extra) => { $(sec).hidden = !items.length; $(id).replaceChildren(...items.map(c => comicCard(c, extra(c)))); };
    row("cu-sec", "cu-row", d.updated || [], c => `${c.new} new page${c.new === 1 ? "" : "s"}`);
    row("cc-sec", "cc-row", d.continue || [], c => `page ${c.page} of ${c.pages}`);
    row("cf-sec", "cf-row", d.following || [], () => "");
    $("cl-sec").hidden = !(d.library || []).length;
    $("c-list").replaceChildren(...(d.library || []).map(c => comicCard(c, c.imported ? "imported" : "made here")));
  }
  $("cg").append(...list.map(c => comicCard(c)));
  const t = d.taste || {};
  $("cg-note").textContent = searching ? (!$("cg").children.length ? "Nothing found." : "")
    : !$("cg").children.length ? "Nothing yet." : t.n ? `From what you read and follow here${t.tags && t.tags.length ? ": " + t.tags.slice(0, 6).join(", ") : ""}.`
    : "To start, what's new on e621 and multporn (and your e621 taste). It learns from what you read and follow.";
  $("cg-more").hidden = !d.more;
  if (searching) cf.page++; else cf.offset += list.length;
}
$("cs-form").onsubmit = e => { e.preventDefault(); cf.q = $("cs-q").value.trim(); loadComics(); };
$("cs-site").onchange = () => { cf.site = $("cs-site").value; remember("comicSite", cf.site); if (cf.q) loadComics(); };
$("cg-more").onclick = () => loadComics(true);
$("cg-back").onclick = () => { cf.q = ""; $("cs-q").value = ""; loadComics(); };

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
  if (state.view === "comics" && !cf.q) loadComics();
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
