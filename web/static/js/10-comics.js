/* ---------- comics ---------- */
const comicState = { personas: [], pages: 1, timer: null, medium: "furry" };
async function loadComics() {
  try {
    const d = await api("api/personas/edit");
    comicState.personas = (d.personas || []).filter(p => p.lora && p.lora.enabled !== false);
  } catch { comicState.personas = []; }
  const a = $("c-a"), keep = a.value;
  a.replaceChildren(...comicState.personas.map(p => { const o = el("option", null, `${p.name} (@${p.handle})`); o.value = p.handle; return o; }));
  if (comicState.personas.some(p => p.handle === keep)) a.value = keep;
  renderSecond(); refreshComics();
}
function renderSecond() {
  const a = comicState.personas.find(p => p.handle === $("c-a").value), b = $("c-b"), keep = b.value;
  const others = comicState.personas.filter(p => a && p.handle !== a.handle && p.medium === a.medium && !p.strict && !a.strict);
  const partner = el("option", null, "Her partner (a man)"); partner.value = "partner";
  b.replaceChildren(...others.map(p => { const o = el("option", null, `${p.name} (@${p.handle})`); o.value = p.handle; return o; }), partner);
  if ([...b.options].some(o => o.value === keep)) b.value = keep;
}
$("c-a").onchange = renderSecond;
document.querySelectorAll("#c-pages button").forEach(btn => btn.onclick = () => {
  comicState.pages = +btn.dataset.n;
  document.querySelectorAll("#c-pages button").forEach(x => x.setAttribute("aria-pressed", String(x === btn)));
});
$("c-form").onsubmit = async e => {
  e.preventDefault(); $("c-err").textContent = ""; $("c-go").disabled = true;
  try {
    await api("api/comics/create", { cast: [$("c-a").value, $("c-b").value], story: $("c-story").value.trim(), pages: comicState.pages });
    $("c-story").value = ""; toast("The comic is being made. It shows up here when it's done."); refreshComics();
  } catch (err) { $("c-err").textContent = err.message; }
  $("c-go").disabled = false;
};
document.querySelectorAll("#ci-medium button, #cs-medium button").forEach(btn => btn.onclick = () => {
  comicState.medium = btn.dataset.m;
  document.querySelectorAll("#ci-medium button, #cs-medium button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.m === btn.dataset.m)));
});
const cs = { q: "", page: 0, site: "multporn" };
document.querySelectorAll("#cs-site button").forEach(b => b.onclick = () => {
  cs.site = b.dataset.site;
  document.querySelectorAll("#cs-site button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  if (cs.q) { cs.page = 0; $("cs-list").replaceChildren(); searchComics(); }
});
$("cs-form").onsubmit = e => { e.preventDefault(); cs.q = $("cs-q").value.trim(); cs.page = 0; $("cs-list").replaceChildren(); searchComics(); };
$("cs-more").onclick = () => { cs.page++; searchComics(); };
async function searchComics() {
  $("cs-err").textContent = ""; $("cs-go").disabled = $("cs-more").disabled = true;
  try {
    const d = await api(`api/comics/search?q=${encodeURIComponent(cs.q)}&page=${cs.page}&site=${cs.site}`);
    $("cs-list").append(...d.results.map(r => {
      const it = el("div", "cs-item"), img = el("img"), go = el("button", "secondary", "Import");
      img.alt = ""; img.loading = "lazy"; if (r.thumb) img.src = r.thumb;
      go.type = "button";
      go.onclick = async () => {
        go.disabled = true;
        try { await api("api/comics/import", { url: r.url, title: r.title, medium: comicState.medium });
              go.textContent = "Importing…"; toast("The comic is being imported. It shows up below when it's in."); refreshComics(); }
        catch (err) { go.disabled = false; toast(err.message); }
      };
      it.append(img, el("b", null, r.title));
      if (r.pages) it.append(el("small", "hint", `${r.pages} pages`));
      it.append(go);
      return it;
    }));
    if (!$("cs-list").children.length) $("cs-err").textContent = "Nothing found.";
    $("cs-more").hidden = !d.more;
  } catch (err) { $("cs-err").textContent = err.message; }
  $("cs-go").disabled = $("cs-more").disabled = false;
}
$("ci-form").onsubmit = async e => {
  e.preventDefault(); $("ci-err").textContent = ""; $("ci-go").disabled = true;
  try {
    await api("api/comics/import", { url: $("ci-url").value.trim(), title: $("ci-title").value.trim(),
                                     medium: comicState.medium });
    $("ci-url").value = $("ci-title").value = "";
    toast("The comic is being imported. It shows up here when it's in."); refreshComics();
  } catch (err) { $("ci-err").textContent = err.message; }
  $("ci-go").disabled = false;
};
async function refreshComics() {
  clearTimeout(comicState.timer);
  let d; try { d = await api("api/comics"); } catch { return; }
  const making = $("c-making"); making.replaceChildren();
  for (const m of d.making) {
    const li = el("li"); li.style.padding = "10px 0";
    const pt = m.progress ? progressText(m.progress) : "";
    const pr = m.progress ? ` · ${m.progress.phase}${pt ? " " + pt : ""}` : "";
    const st = m.status === "running" ? "making" : "waiting";
    if (m.imported) li.append(el("b", null, m.title || "Imported comic"), el("div", "hint", `import · ${st}${pr}`), el("div", "hint", m.url));
    else li.append(el("b", null, `${m.cast[0]} + ${m.cast[1] === "partner" ? "her partner" : m.cast[1]}`),
                   el("div", "hint", `${m.pages} page${m.pages > 1 ? "s" : ""} · ${st}${pr}`),
                   el("div", "hint", m.story));
    making.append(li);
  }
  $("c-making-panel").hidden = !d.making.length;
  const failed = $("c-failed"); failed.replaceChildren();
  for (const f of d.failed || []) {
    const li = el("li"); li.style.padding = "10px 0";
    li.append(el("b", null, `${f.what}${f.title ? " · " + f.title : ""}`), el("div", "hint", f.message || "No reason given."),
              el("div", "hint", f.finished ? relTime(f.finished) : ""));
    li.append(retryButton(f.job, () => refreshComics()));
    failed.append(li);
  }
  $("c-failed-panel").hidden = !(d.failed || []).length;
  const list = $("c-list"); list.replaceChildren();
  for (const c of d.comics) {
    const card = el("button", "comic-card"); card.type = "button";
    const img = el("img"); img.loading = "lazy"; img.alt = ""; img.src = `comic/${c.id}/1/thumb`;
    card.append(img, el("b", null, c.title || "Untitled"),
                el("small", null, `${c.imported ? "imported" : c.cast.map(h => h === "partner" ? "her partner" : "@" + h).join(" + ")} · ${c.pages} page${c.pages > 1 ? "s" : ""}`));
    const upd = c.updated && (Date.now() - new Date(c.updated.at.replace(" ", "T") + "Z")) < 3 * 86400e3;
    if (upd) card.append(el("span", "badge", `${c.updated.new} new page${c.updated.new > 1 ? "s" : ""}`));
    card.onclick = () => openComic(c);
    const ren = el("button", "linkish card-del", "Rename"); ren.type = "button";
    ren.onclick = async () => {
      const title = prompt("New title", c.title || ""); if (title === null || !title.trim() || title.trim() === c.title) return;
      try { await api("api/comics/rename", { id: c.id, title }); toast("Renamed."); refreshComics(); } catch (e) { toast(e.message); }
    };
    const del = el("button", "linkish card-del", "Delete"); del.type = "button";
    del.onclick = async () => {
      if (!confirm(`Delete "${c.title || "Untitled"}"? Its pages and animations go too.`)) return;
      try { await api("api/comics/delete", { id: c.id }); toast("Deleted."); refreshComics(); } catch (e) { toast(e.message); }
    };
    const acts = el("div", "card-acts"); acts.append(ren, del);
    const item = el("div", "comic-item"); item.append(card, acts);
    list.append(item);
  }
  $("c-none").hidden = d.comics.length > 0;
  syncReader(d);
  if ((state.view === "comics" || !$("reader").hidden) && d.making.length) comicState.timer = setTimeout(refreshComics, 10000);
}
const rd = { c: null, picking: false, chosen: null, drawing: false, page: 1, grid: false, wraps: [], queued: [] };
function showComic(c) {
  Object.assign(rd, { c, picking: false, chosen: null, drawing: false, page: 1, grid: false });
  $("reader-title").textContent = c.title || "Untitled";
  const anim = $("reader-animate"); anim.hidden = false; anim.setAttribute("aria-pressed", "false"); anim.textContent = "Animate";
  $("reader").hidden = false;
  buildSlides(); showView(); goTo(1, true);
  refreshComics();   // what's queued for it
}
function closeComic() { $("reader").hidden = true; rd.c = null; $("rd-track").replaceChildren(); $("rd-grid").replaceChildren(); }
function pct(box) { const [x0, y0, x1, y1] = box;
  return { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` }; }
function buildSlides() {   // one slide per page; their overlays come from decorate()
  const c = rd.c, track = $("rd-track"); track.replaceChildren(); rd.wraps = [];
  for (let n = 1; n <= c.pages; n++) {
    const slide = el("div", "rd-slide"), wrap = el("div", "rpage"), img = el("img");
    img.alt = `Page ${n}`; img.loading = n <= 2 ? "eager" : "lazy"; img.decoding = "async";
    img.src = `comic/${c.id}/${n}`;
    img.onload = () => fit(wrap, img);
    wrap.append(img); slide.append(wrap); track.append(slide); rd.wraps.push(wrap);
  }
  decorate();
}
function fit(wrap, img) {   // the page as large as fits its slide, so panel boxes (in shares) line up
  const slide = wrap.parentNode, nw = img.naturalWidth, nh = img.naturalHeight;
  if (!nw || !nh || !slide) return;
  const r = Math.min((slide.clientWidth - 16) / nw, (slide.clientHeight - 16) / nh);
  wrap.style.width = `${Math.floor(nw * r)}px`; wrap.style.height = `${Math.floor(nh * r)}px`;
}
function refit() { rd.wraps.forEach(w => fit(w, w.querySelector("img"))); goTo(rd.page, true); }
window.addEventListener("resize", () => { if (!$("reader").hidden) refit(); });
const SVG = "http://www.w3.org/2000/svg";
function loopsSvg(loops) {   // the drawn outlines, in page shares
  const svg = document.createElementNS(SVG, "svg"); svg.setAttribute("class", "outl");
  svg.setAttribute("viewBox", "0 0 1 1"); svg.setAttribute("preserveAspectRatio", "none");
  for (const loop of loops) {
    const p = document.createElementNS(SVG, "polygon");
    p.setAttribute("points", loop.map(q => q.join(",")).join(" ")); p.setAttribute("vector-effect", "non-scaling-stroke");
    svg.append(p);
  }
  return svg;
}
function decorate() {   // the loops over their panels, or the panels to pick while animating
  const c = rd.c;
  $("rd-help").hidden = !rd.picking || !!rd.chosen; $("rd-ask").hidden = !rd.chosen; $("rd-err").textContent = "";
  $("rd-ask").classList.toggle("drawing", rd.drawing);
  $("rd-track").classList.toggle("picking", rd.picking);
  const loops = rd.chosen ? rd.chosen.outline : [];
  $("rd-draw").textContent = rd.drawing ? "Done drawing" : loops.length ? "Draw more" : "Draw around them";
  $("rd-draw").setAttribute("aria-pressed", String(rd.drawing));
  $("rd-undo-loop").hidden = !loops.length;
  $("rd-clear-loops").hidden = loops.length < 2;
  $("rd-found").hidden = !rd.chosen || !rd.chosen.found || loops.length;
  const found = rd.chosen && rd.chosen.found && !rd.chosen.edited;
  $("rd-loops").textContent = loops.length ? `${loops.length} outline${loops.length > 1 ? "s" : ""}${found ? " found round the characters" : ""}: only ${loops.length > 1 ? "those move" : "that moves"}`
    : "No outline: the whole panel moves (bubbles and text stay still)";
  rd.wraps.forEach((wrap, i) => {
    const n = i + 1;
    wrap.querySelectorAll("video, .pbox, .drag, .outl").forEach(x => x.remove());
    const anims = (c.animations || []).map((a, k) => ({ ...a, k })).filter(a => a.page === n);
    if (!rd.picking) for (const a of anims) {
      const v = el("video"); Object.assign(v, { muted: true, loop: true, autoplay: true, playsInline: true, src: `comic/${c.id}/anim/${a.name}` });
      v.setAttribute("muted", ""); v.setAttribute("playsinline", ""); Object.assign(v.style, pct(a.box));
      if (a.mask) {   // only what was outlined shows; the page is seen through the rest
        const m = `url(comic/${c.id}/anim/${a.mask})`;
        Object.assign(v.style, { maskImage: m, webkitMaskImage: m, maskSize: "100% 100%", webkitMaskSize: "100% 100%" });
      }
      wrap.append(v);
    }
    if (!rd.picking) return;
    const here = rd.chosen && rd.chosen.page === n;
    if (here && rd.drawing) {   // outlining what moves: the chosen panel, the loops, and the pen over the whole page
      const b = el("div", "pbox chosen still"); Object.assign(b.style, pct(rd.chosen.box)); wrap.append(b);
      wrap.append(loopsSvg(loops));
      const pen = el("div", "drag pen"); wrap.append(pen); drawLoops(pen); return;
    }
    const drag = el("div", "drag"); wrap.append(drag); dragBox(drag, n);
    const queued = rd.queued.filter(q => q.page === n);
    for (const q of queued) {
      const b = el("div", "pbox queued", q.status === "running" ? "Animating…" : "Queued"); Object.assign(b.style, pct(q.box)); wrap.append(b);
    }
    const near = (a, b) => Math.abs(a[0] - b[0]) < 0.01 && Math.abs(a[1] - b[1]) < 0.01;
    for (const box of (c.panels || {})[n] || []) {
      if (anims.some(a => near(a.box, box)) || queued.some(q => near(q.box, box))) continue;
      const b = el("button", "pbox" + (here && rd.chosen.box === box ? " chosen" : ""), "Animate");
      b.type = "button"; Object.assign(b.style, pct(box)); b.onclick = () => choose(n, box); wrap.append(b);
    }
    for (const a of anims) {
      const b = el("button", "pbox done", "Remove animation"); b.type = "button"; Object.assign(b.style, pct(a.box));
      b.onclick = async () => { if (!confirm("Remove this animation?")) return;
        try { await api("api/comics/animation-delete", { id: c.id, index: a.k }); await reloadComic(); } catch (e) { toast(e.message); } };
      wrap.append(b);
    }
    if (here && !((c.panels || {})[n] || []).includes(rd.chosen.box)) {
      const b = el("div", "pbox chosen"); Object.assign(b.style, pct(rd.chosen.box)); wrap.append(b);
    }
    if (here && loops.length) wrap.append(loopsSvg(loops));
  });
}
function goTo(n, instant) {
  const c = rd.c; n = Math.max(1, Math.min(c.pages, n)); rd.page = n;
  const track = $("rd-track");
  track.scrollTo({ left: (n - 1) * track.clientWidth, behavior: instant ? "instant" : "smooth" });
  showCount();
}
function showCount() {
  for (const k of [rd.page - 1, rd.page, rd.page + 1]) {   // this page and its neighbours load now
    const img = rd.wraps[k - 1]?.querySelector("img"); if (img && img.loading !== "eager") img.loading = "eager";
  }
  $("rd-count").textContent = `${rd.page} / ${rd.c.pages}`;
  $("rd-prev").disabled = rd.page <= 1; $("rd-next").disabled = rd.page >= rd.c.pages;
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
  $("reader-animate").hidden = g;
  if (g) buildGrid();
}
function buildGrid() {
  const c = rd.c, grid = $("rd-grid"); grid.replaceChildren();
  const animated = new Set((c.animations || []).map(a => a.page));
  for (let n = 1; n <= c.pages; n++) {
    const b = el("button"), img = el("img"); b.type = "button";
    img.alt = ""; img.loading = "lazy"; img.src = `comic/${c.id}/${n}/thumb`;
    b.append(img, el("span", null, `${n}${animated.has(n) ? " · animated" : ""}`));
    if (n === rd.page) b.setAttribute("aria-current", "true");
    b.onclick = () => { rd.grid = false; showView(); goTo(n, true); };
    grid.append(b);
  }
  if (c.imported) {
    const look = el("button", "secondary del", "Check for new pages"); look.type = "button";
    look.onclick = async () => {
      look.disabled = true;
      try { await api("api/comics/update", { id: c.id }); toast("Looking for new pages. New ones are added at the end."); refreshComics(); }
      catch (err) { look.disabled = false; toast(err.message); }
    };
    grid.append(look);
  }
  const del = el("button", "secondary del", "Delete this comic"); del.type = "button";
  del.onclick = async () => {
    if (!confirm("Delete this comic?")) return;
    try { await api("api/comics/delete", { id: c.id }); go("comics", true); refreshComics(); } catch (err) { toast(err.message); }
  };
  grid.append(del);
  grid.querySelector('[aria-current="true"]')?.scrollIntoView({ block: "center" });
}
$("reader-view").onclick = () => {
  if (rd.picking) stopPicking();
  rd.grid = !rd.grid; showView(); if (!rd.grid) goTo(rd.page, true);
};
function stopPicking() {
  rd.picking = false; rd.chosen = null; rd.drawing = false;
  $("reader-animate").setAttribute("aria-pressed", "false"); $("reader-animate").textContent = "Animate"; decorate(); refit();
}
$("reader-animate").onclick = () => {
  if (rd.picking) return stopPicking();
  rd.picking = true; rd.chosen = null; rd.drawing = false;
  $("reader-animate").setAttribute("aria-pressed", "true"); $("reader-animate").textContent = "Done"; decorate();
  goTo(rd.page, true);
};
document.addEventListener("keydown", e => {
  if ($("reader").hidden || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  if (e.key === "Escape") return leave();
  if (rd.grid) return;
  if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); goTo(rd.page + 1); }
  if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); goTo(rd.page - 1); }
});
function clipTo(loop, box) {   // a loop cut to the box (Sutherland-Hodgman, one edge at a time)
  const edges = [[0, box[0], 1], [0, box[2], -1], [1, box[1], 1], [1, box[3], -1]];
  for (const [k, v, dir] of edges) {
    const out = [], inside = q => (q[k] - v) * dir >= 0;
    loop.forEach((q, i) => {
      const p = loop[(i + loop.length - 1) % loop.length];
      if (inside(q) !== inside(p)) { const t = (v - p[k]) / (q[k] - p[k]); out.push([p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]); }
      if (inside(q)) out.push(q);
    });
    loop = out; if (loop.length < 3) return [];
  }
  return loop.map(q => q.map(v => Math.round(v * 10000) / 10000));
}
const loopArea = l => Math.abs(l.reduce((a, q, i) => { const p = l[(i + 1) % l.length]; return a + q[0] * p[1] - p[0] * q[1]; }, 0)) / 2;
function suggested(page, box) {   // the characters found in the panel, biggest first
  const area = (box[2] - box[0]) * (box[3] - box[1]);
  return ((rd.c.outlines || {})[page] || []).map(l => clipTo(l, box)).filter(l => l.length >= 3 && loopArea(l) >= 0.01 * area)
    .sort((a, b) => loopArea(b) - loopArea(a)).slice(0, 8);
}
function choose(page, box) {
  const found = suggested(page, box);
  rd.chosen = { page, box, outline: found, found: found.length }; rd.drawing = false; decorate(); refit();
  $("rd-motion").focus({ preventScroll: true });
}
function at(layer, e) { const r = layer.getBoundingClientRect();
  return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; }
function dragBox(layer, page) {   // a box drawn by hand, for panels that weren't found
  let start = null, shape = null;
  layer.addEventListener("pointerdown", e => { if (e.button > 0) return; e.preventDefault(); layer.setPointerCapture(e.pointerId);
    start = at(layer, e); shape = el("div", "pbox chosen"); layer.parentNode.append(shape); });
  layer.addEventListener("pointermove", e => { if (!start) return; const p = at(layer, e);
    Object.assign(shape.style, pct([Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])])); });
  const end = e => { if (!start) return; const p = at(layer, e), box = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])];
    start = null; shape.remove();
    if (box[2] - box[0] >= 0.05 && box[3] - box[1] >= 0.05) choose(page, box.map(v => Math.round(v * 10000) / 10000)); };
  layer.addEventListener("pointerup", end); layer.addEventListener("pointercancel", end);
}
function drawLoops(layer) {   // freehand loops around what moves; each closes itself when the finger lifts
  let pts = null, line = null;
  layer.addEventListener("pointerdown", e => { if (e.button > 0) return; e.preventDefault(); layer.setPointerCapture(e.pointerId);
    pts = [at(layer, e)]; const svg = loopsSvg([]); line = document.createElementNS(SVG, "polyline");
    line.setAttribute("vector-effect", "non-scaling-stroke"); svg.append(line); layer.parentNode.insertBefore(svg, layer); });
  layer.addEventListener("pointermove", e => { if (!pts) return; const p = at(layer, e), q = pts[pts.length - 1];
    if (Math.hypot(p[0] - q[0], p[1] - q[1]) < 0.004 || pts.length >= 2000) return;
    pts.push(p); line.setAttribute("points", pts.map(v => v.join(",")).join(" ")); });
  const end = () => { if (!pts) return; const loop = pts; pts = null;
    if (loop.length >= 3 && rd.chosen.outline.length < 8) { rd.chosen.outline.push(loop.map(q => q.map(v => Math.round(v * 10000) / 10000))); rd.chosen.edited = true; }
    decorate(); };
  layer.addEventListener("pointerup", end); layer.addEventListener("pointercancel", end);
}
$("rd-draw").onclick = () => { rd.drawing = !rd.drawing; decorate(); refit(); };
$("rd-undo-loop").onclick = () => { if (rd.chosen) { rd.chosen.outline.pop(); rd.chosen.edited = true; } decorate(); };
$("rd-clear-loops").onclick = () => { if (rd.chosen) { rd.chosen.outline = []; rd.chosen.edited = true; } decorate(); };
$("rd-found").onclick = () => { if (rd.chosen) { rd.chosen.outline = suggested(rd.chosen.page, rd.chosen.box); rd.chosen.edited = false; } decorate(); };
function syncReader(d) {   // a refresh of the Comics page: the open comic's new clips and queued panels
  if (!rd.c || $("reader").hidden) return;
  const c = d.comics.find(x => x.id === rd.c.id);
  const queued = (d.making || []).filter(m => m.comic === rd.c.id).map(m => ({ page: m.page, box: m.box, status: m.status }));
  const before = JSON.stringify([rd.c.animations, rd.queued]);
  if (c) rd.c = c;
  rd.queued = queued;
  if (JSON.stringify([rd.c.animations, rd.queued]) !== before && !rd.drawing) decorate();
}
async function reloadComic() {
  const d = await api("api/comics"); rd.chosen = null; rd.drawing = false;
  syncReader(d); decorate();
}
$("rd-cancel").onclick = () => { rd.chosen = null; rd.drawing = false; decorate(); refit(); };
$("rd-ask").onsubmit = async e => {
  e.preventDefault(); if (!rd.chosen) return; $("rd-go").disabled = true; $("rd-err").textContent = "";
  try {
    const ch = rd.chosen;
    await api("api/comics/animate", { id: rd.c.id, page: ch.page, box: ch.box, motion: $("rd-motion").value.trim(),
                                      cast: $("rd-cast").value, outline: ch.outline });
    rd.queued.push({ page: ch.page, box: ch.box, status: "queued" });
    $("rd-motion").value = ""; rd.chosen = null; rd.drawing = false; decorate(); refit();
    toast("Queued. Pick another panel, or tap Done. Each plays here when it's done."); refreshComics();
  } catch (err) { $("rd-err").textContent = err.message; }
  $("rd-go").disabled = false;
};
$("reader-close").onclick = leave;

