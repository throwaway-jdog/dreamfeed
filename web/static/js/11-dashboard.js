/* ---------- dashboard ---------- */
const SEC_PER_IMAGE = 10.5;
const gen = { n: 12, keep: 6, styles: new Set(["anime", "furry"]), who: "" };
const defaultKeep = n => Math.max(1, Math.round(n <= 12 ? n / 2 : n * 0.2));
function renderGenForm() {
  document.querySelectorAll("#g-count button").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.n === gen.n)));
  document.querySelectorAll("#g-styles button").forEach(b => b.setAttribute("aria-pressed", String(gen.styles.has(b.dataset.m))));
  const who = $("g-who"), names = (state.people || []).map(p => p.handle).join();
  if (who.dataset.names !== names) {   // the personas, once they've loaded
    who.dataset.names = names;
    who.replaceChildren(el("option", null, "Everyone"), ...(state.people || []).map(p => {
      const o = el("option", null, `${p.name} (@${p.handle})`); o.value = p.handle; return o; }));
    who.firstChild.value = "";
    if (!(state.people || []).some(p => p.handle === gen.who)) gen.who = "";
    who.value = gen.who;
  }
  $("g-styles-field").hidden = !!gen.who;   // a persona draws in her own style
  $("g-keep").textContent = gen.keep;
  $("g-keep-note").textContent = gen.keep === gen.n ? "keeps all of them" : `of ${gen.n}; the rest are deleted`;
  const mins = Math.max(1, Math.round(gen.n * SEC_PER_IMAGE / 60));
  $("g-est").textContent = `Takes about ${mins} minute${mins > 1 ? "s" : ""}. You can leave this page; new images show up in the feed when it's done.`;
  $("g-go").disabled = (!gen.who && !gen.styles.size) || dashState.busy;
  $("g-go").textContent = gen.who ? `Post as @${gen.who}` : "Generate";
}
document.querySelectorAll("#g-count button").forEach(b => b.onclick = () => { gen.n = +b.dataset.n; gen.keep = defaultKeep(gen.n); renderGenForm(); });
document.querySelectorAll("#g-styles button").forEach(b => b.onclick = () => {
  gen.styles.has(b.dataset.m) ? gen.styles.delete(b.dataset.m) : gen.styles.add(b.dataset.m); renderGenForm();
});
$("g-who").onchange = () => { gen.who = $("g-who").value; renderGenForm(); };
$("g-less").onclick = () => { gen.keep = Math.max(1, gen.keep - (gen.n > 50 ? 5 : 1)); renderGenForm(); };
$("g-more").onclick = () => { gen.keep = Math.min(gen.n, gen.keep + (gen.n > 50 ? 5 : 1)); renderGenForm(); };
$("g-go").onclick = async () => {
  $("g-go").disabled = true;
  try {
    await api("api/generate", gen.who ? { images: gen.n, keep: gen.keep, personas: [gen.who] }
                                      : { images: gen.n, keep: gen.keep, mediums: [...gen.styles] });
    toast("Queued. It starts within a few seconds.");
  } catch (e) { toast(e.message); }
  refreshDash();
};

const dashState = { busy: false, timer: 0 };
function clock(iso) {
  if (!iso) return "–";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (isNaN(d)) return iso;
  const today = new Date().toDateString() === d.toDateString();
  return d.toLocaleString(undefined, today ? { hour: "numeric", minute: "2-digit" } : { weekday: "short", hour: "numeric", minute: "2-digit" });
}
const PHASE = { generating: "Generating", animating: "Animating", checking: "Checking ages", ranking: "Picking the best",
  captioning: "Writing captions", planning: "Planning motion", drawing: "Drawing shots", downloading: "Downloading",
  "checking the pages": "Checking the pages", "reading the panel": "Reading the panel", "checking the clip": "Checking the clip" };
function progressText(p) {   // "3 of 5", "45%", or both: share is finer than done of total when known (a clip's steps)
  const pc = p.share != null ? `${Math.round(100 * p.share)}%` : "";
  const of = p.total > 1 ? `${p.done} of ${p.total}` : "";
  return [of, pc].filter(Boolean).join(" · ");
}
let animN = 3;
document.querySelectorAll("#a-count button").forEach(b => b.onclick = () => {
  animN = +b.dataset.n;
  document.querySelectorAll("#a-count button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
});
$("a-go").onclick = async () => {
  $("a-go").disabled = true;
  try { await api("api/animate", { count: animN }); toast(`Queued ${animN} clip${animN > 1 ? "s" : ""}.`); }
  catch (e) { toast(e.message); }
  $("a-go").disabled = false; refreshDash();
};
function retryButton(job, after) {   // a failed request queued again exactly as asked
  const b = el("button", "linkish retry", "Try again"); b.type = "button";
  b.onclick = async () => {
    b.disabled = true;
    try { await api("api/retry", { job }); toast("Queued again."); after(); } catch (e) { toast(e.message); b.disabled = false; }
  };
  return b;
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

function renderLive(d) {
  const live = $("live"); live.replaceChildren();
  const running = d.runs.find(r => r.status === "running");
  const queued = d.jobs.filter(j => j.status === "queued");
  dashState.busy = !!running || queued.length > 0;
  if (running) {
    const p = running.progress || { phase: "generating", done: 0, total: 0 };
    const box = el("div", "live"), head = el("div", "head");
    const t = progressText(p);
    head.append(el("span", null, `${PHASE[p.phase] || "Working"}${t ? ` ${t}` : "…"}`));
    const stop = el("button", "linkish", "Cancel"); stop.type = "button";
    stop.onclick = async () => { stop.disabled = true; try { await api("api/cancel", { night: running.night }); toast("Stopping after the current image"); } catch (e) { toast(e.message); } refreshDash(); };
    head.append(stop);
    const meter = el("div", "meter"), bar = el("i"); bar.style.width = `${p.share != null ? Math.max(4, Math.round(100 * p.share)) : p.total ? Math.round(100 * p.done / p.total) : 4}%`; meter.append(bar);
    const label = /^\d/.test(running.night) ? "Tonight's run" : nightLabel(running.night);
    box.append(head, meter, el("div", "sub", `${label}${p.medium ? " · " + (LABEL[p.medium] || p.medium) : ""}`));
    live.append(box);
  }
  for (const j of queued) {
    const box = el("div", "live"), head = el("div", "head");
    const what = j.params.kind === "style" ? `train the ${j.params.name} style`
      : j.params.kind === "animate"
      ? (j.params.ids ? "animate 1 image" : `animate the best ${j.params.count}`)
      : j.params.kind === "scene" ? "make a scene"
      : j.params.kind === "comic" ? `make a ${j.params.pages}-page comic`
      : j.params.kind === "comic_import" ? "import a comic"
      : j.params.kind === "comic_animate" ? "animate a comic panel"
      : `${j.params.images} images, keep ${j.params.keep}${j.params.personas ? " · " + j.params.personas.map(h => personaOf(h)?.name || h).join(", ") : ""}`;
    head.append(el("span", null, `Waiting: ${what}`));
    const stop = el("button", "linkish", "Remove"); stop.type = "button";
    stop.onclick = async () => { try { await api("api/cancel", { job: j.id }); } catch (e) { toast(e.message); } refreshDash(); };
    head.append(stop); box.append(head); live.append(box);
  }
}

function renderRuns(d) {
  const [a, b] = d.window.split("-");
  const t = hm => { const [h, m] = hm.split(":").map(Number); return new Date(2000, 0, 1, h, m).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }); };
  $("r-window").textContent = `Nightly run every night ${t(a)}–${t(b)}.`;
  const list = $("r-list"); list.replaceChildren();
  if (!d.runs.length) { list.append(el("li", null, "No runs yet.")); return; }
  for (const r of d.runs) {
    const li = el("li"), name = /^\d/.test(r.night) ? "Night of " + nightLabel(r.night) : nightLabel(r.night);
    const cls = { done: "ok", running: "run", failed: "bad", cancelled: "" }[r.status] ?? "";
    li.append(el("span", null, name), el("span", "pill " + cls, r.status === "done" ? "done" : r.status));
    const st = r.stats || {};
    const parts = [];
    if (st.feed != null) parts.push(`${st.feed} kept`);
    if (st.videos?.feed) parts.push(`${st.videos.feed} clips`);
    if (st.dropped) parts.push(`${st.dropped} dropped by the checks`);
    if (st.note) parts.push(st.note);
    if (r.finished_at) parts.push("finished " + clock(r.finished_at));
    if (r.message && r.status !== "running") parts.push(r.message);   // a job's own message: why it failed, what it made
    li.append(el("span", "what", parts.join(" · ") || (r.status === "running" ? "in progress" : "")));
    if (r.retry) li.append(retryButton(r.retry, () => refreshDash()));
    list.append(li);
  }
}

async function refreshDash() {
  clearTimeout(dashState.timer);
  if (state.view !== "dash") return;
  try {
    const d = await api("api/dashboard");
    renderLive(d); renderRuns(d); renderGenForm();
    await loadStyles();
    dashState.timer = setTimeout(refreshDash, dashState.busy || styleState.busy ? 3000 : 15000);
  } catch (e) { if (e.message !== "signed out") toast(e.message); dashState.timer = setTimeout(refreshDash, 15000); }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshDash(); });


/* ---------- trained styles ---------- */
const styleState = { list: [], busy: false, medium: "anime", limit: 300, steps: 2000,
  video: null, vLimit: 300, vSteps: 1500 };   // video: the style whose "Train video" form is open
const VIDEO_PHASE = { downloading: "Downloading clips", checking: "Checking clips", describing: "Describing the motion",
  prepared: "Clips ready", waiting: "Waiting for the video trainer", "training-high": "Training motion (half 1 of 2)",
  "training-low": "Training detail (half 2 of 2)", trained: "Finishing", done: "Done", failed: "Failed",
  "train-failed": "Failed", cancelled: "Cancelled" };
const VIDEO_SIZES = { limits: [[100, "100"], [300, "300"], [600, "600"]], steps: [[1000, "Quick"], [1500, "Normal"], [2000, "Long"]] };
const STYLE_PHASE = { downloading: "Downloading", checking: "Checking images", waiting: "Waiting for the trainer",
  training: "Training", trained: "Finishing", done: "Done", failed: "Failed", "train-failed": "Failed", cancelled: "Cancelled" };
async function loadStyles() {
  try { styleState.list = (await api("api/styles")).styles; } catch { return; }
  styleState.busy = styleState.list.some(s => s.job || s.video?.job);
  renderStyles();
}
function renderStyles() {
  const list = $("s-list"); list.replaceChildren();
  if (!styleState.list.length) list.append(el("li", "note", "No styles yet."));
  for (const s of styleState.list) {
    const li = el("li"), row = el("div", "srow"), mid = el("div");
    mid.append(el("div", "nm", s.name));
    const sub = el("div", "sub");
    if (s.medium) sub.append(el("span", "badge", LABEL[s.medium] || s.medium));
    if (s.trained) sub.append(el("span", null, `trained ${clock(new Date(s.trained * 1000).toISOString())}`));
    else if (!s.job) sub.append(el("span", null, "not trained"));
    if (s.kept != null) sub.append(el("span", null, `${s.kept} images`));
    if (s.voice) sub.append(el("span", null, `${s.voice} posts for captions`));
    if (s.used_by.length) sub.append(el("span", "badge on", "used by " + s.used_by.join(", ")));
    mid.append(sub); row.append(mid);
    if (s.job) {
      const stop = el("button", "linkish", "Stop"); stop.type = "button";
      stop.onclick = async () => { stop.disabled = true; try { await api("api/styles/cancel", { name: s.name }); toast("Stopping…"); } catch (e) { toast(e.message); } refreshDash(); };
      row.append(stop);
    } else if (s.source) {
      const again = el("button", "linkish", "Retrain"); again.type = "button";
      again.onclick = () => openStyleForm(s); row.append(again);
    } else row.append(el("span"));
    const st = s.job && s.job.status === "queued" ? { phase: "queued" } : s.status;
    if (st) {
      const prog = el("div", "prog" + (/failed/.test(st.phase) ? " bad" : ""));
      let text = st.phase === "queued" ? "Waiting to start" : STYLE_PHASE[st.phase] || st.phase;
      if (st.phase === "downloading") text += ` · ${st.done || 0} new images`;
      if (st.phase === "checking" || st.phase === "training") text += ` · ${st.done || 0} of ${st.total || "?"}` + (st.phase === "training" ? " steps" : "");
      if (st.message && !s.job) text += `: ${st.message}`;
      prog.append(el("span", null, text));
      if (s.job && (st.phase === "checking" || st.phase === "training")) {
        const meter = el("div", "meter"), bar = el("i"); bar.style.width = `${st.total ? Math.round(100 * st.done / st.total) : 3}%`;
        meter.append(bar); prog.append(meter);
      }
      row.append(prog);
    }
    li.append(row);
    if (s.trained) li.append(videoRow(s));
    list.append(li);
  }
  $("s-new").disabled = styleState.list.some(s => s.job);
}
function videoRow(s) {
  const v = s.video || {}, row = el("div", "srow vid"), mid = el("div");
  mid.append(el("div", "nm", "Video LoRA"));
  const sub = el("div", "sub");
  if (v.trained) sub.append(el("span", null, `trained ${clock(new Date(v.trained * 1000).toISOString())}`));
  else if (!v.job) sub.append(el("span", null, "not trained: clips use the image style only"));
  if (v.clips != null) sub.append(el("span", null, `${v.clips} clips`));
  mid.append(sub); row.append(mid);
  const otherVideo = styleState.list.some(o => o.video?.job && o.name !== s.name);
  if (v.job) {
    const stop = el("button", "linkish", "Stop"); stop.type = "button";
    stop.onclick = async () => { stop.disabled = true; try { await api("api/styles/video-cancel", { name: s.name }); toast("Stopping…"); } catch (e) { toast(e.message); } refreshDash(); };
    row.append(stop);
  } else if (styleState.video !== s.name) {
    const go = el("button", "linkish", v.trained ? "Retrain video" : "Train video"); go.type = "button";
    go.disabled = !!s.job || otherVideo;
    if (otherVideo) go.title = "Another video LoRA is training";
    go.onclick = () => { styleState.video = s.name; styleState.vLimit = v.limit || 300; styleState.vSteps = v.steps || 1500; renderStyles(); };
    row.append(go);
  } else row.append(el("span"));
  const st = v.job && v.job.status === "queued" ? { phase: "queued" } : v.status;
  if (st) {
    const prog = el("div", "prog" + (/failed/.test(st.phase) ? " bad" : ""));
    let text = st.phase === "queued" ? "Waiting to start" : VIDEO_PHASE[st.phase] || st.phase;
    const counted = ["checking", "describing", "training-high", "training-low"].includes(st.phase);
    if (counted && st.total) text += ` · ${st.done || 0} of ${st.total}` + (st.phase.startsWith("training") ? " steps" : "");
    if (st.message && !v.job) text += `: ${st.message}`;
    prog.append(el("span", null, text));
    if (v.job && counted) {
      const meter = el("div", "meter"), bar = el("i"); bar.style.width = `${st.total ? Math.round(100 * (st.done || 0) / st.total) : 3}%`;
      meter.append(bar); prog.append(meter);
    }
    row.append(prog);
  }
  if (styleState.video === s.name && !v.job) row.append(videoForm(s));
  return row;
}
function videoForm(s) {
  const box = el("div", "vform");
  box.append(el("p", "note", "Downloads the artist's animations from the style's page, drops any clip with a frame the " +
    "adult checks flag, describes the motion, then trains both halves of the video model. Nightly posts and scenes wait while it trains."));
  const seg = (label, key, opts) => {
    const f = el("div", "field"); f.append(el("span", null, label));
    const g = el("div", "seg"); g.setAttribute("role", "group"); g.setAttribute("aria-label", label);
    for (const [n, text] of opts) {
      const b = el("button", null, text); b.type = "button"; b.setAttribute("aria-pressed", String(styleState[key] === n));
      b.onclick = () => { styleState[key] = n; renderStyles(); };
      g.append(b);
    }
    f.append(g); return f;
  };
  box.append(seg("Videos to download (at most)", "vLimit", VIDEO_SIZES.limits), seg("Training length", "vSteps", VIDEO_SIZES.steps));
  // About 8 s a step per half on a 12 GB GPU, plus loading; downloading and checking ~5 s a clip.
  const hours = (2 * styleState.vSteps * 8 + styleState.vLimit * 5 + 1800) / 3600;
  box.append(el("p", "note", `About ${Math.round(hours)} hours. You can leave this page.`));
  const err = el("div", "ed-err"); err.setAttribute("role", "alert");
  const acts = el("div", "form-actions"), no = el("button", "secondary", "Cancel"), go = el("button", "primary", "Download and train");
  no.type = go.type = "button";
  no.onclick = () => { styleState.video = null; renderStyles(); };
  go.onclick = async () => {
    go.disabled = true;
    try {
      await api("api/styles/video", { name: s.name, limit: styleState.vLimit, steps: styleState.vSteps });
      styleState.video = null; toast("Queued. Progress shows here."); refreshDash();
    } catch (e) { err.textContent = e.message; go.disabled = false; }
  };
  acts.append(no, go); box.append(err, acts);
  return box;
}
function renderStyleForm() {
  document.querySelectorAll("#s-medium button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.m === styleState.medium)));
  document.querySelectorAll("#s-limit button").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.n === styleState.limit)));
  document.querySelectorAll("#s-steps button").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.n === styleState.steps)));
  const mins = Math.round(3 + styleState.limit * 1.2 / 60 + styleState.steps * 0.66 / 60);
  $("s-est").textContent = `About ${mins} minutes. You can leave this page.`;
}
function openStyleForm(s) {
  $("s-form").hidden = false; $("s-new").hidden = true; $("s-err").textContent = "";
  $("s-name").value = s?.name || ""; $("s-name").disabled = !!s; $("s-source").value = s?.source || "";
  styleState.medium = s?.medium || "anime"; styleState.limit = s?.limit || 300; styleState.steps = s?.steps || 2000;
  document.querySelectorAll("#s-medium button").forEach(b => b.disabled = !!s);
  $("s-go").textContent = s ? "Download new images and retrain" : "Download and train";
  renderStyleForm(); (s ? $("s-go") : $("s-name")).focus();
}
function closeStyleForm() { $("s-form").hidden = true; $("s-new").hidden = false; }
$("s-new").onclick = () => openStyleForm(null);
$("s-no").onclick = closeStyleForm;
document.querySelectorAll("#s-medium button").forEach(b => b.onclick = () => { styleState.medium = b.dataset.m; renderStyleForm(); });
document.querySelectorAll("#s-limit button").forEach(b => b.onclick = () => { styleState.limit = +b.dataset.n; renderStyleForm(); });
document.querySelectorAll("#s-steps button").forEach(b => b.onclick = () => { styleState.steps = +b.dataset.n; renderStyleForm(); });
$("s-form").onsubmit = async e => {
  e.preventDefault(); $("s-go").disabled = true;
  try {
    await api("api/styles/train", { name: $("s-name").value.trim().toLowerCase(), medium: styleState.medium,
      source: $("s-source").value.trim(), limit: styleState.limit, steps: styleState.steps,
      videos: $("s-videos").checked });
    closeStyleForm(); toast("Queued. Progress shows here."); refreshDash();
  } catch (err) { $("s-err").textContent = err.message; }
  $("s-go").disabled = false;
};
// Health: whether each part is working (sign-ins, the Feed's sites, the recorder, the server's
// browser, jobs, disk), worst first.
async function loadHealth() {
  $("hl-note").textContent = "Looking…";
  let d;
  try { d = await api("api/health"); } catch (err) { $("hl-note").textContent = err.message; return; }
  const order = { bad: 0, warn: 1, ok: 2, off: 3 }, mark = { bad: "✗", warn: "⚠", ok: "✓", off: "–" };
  d.parts = d.parts || [];
  const rows = d.parts.slice().sort((a, b) => order[a.state] - order[b.state]);
  $("hl-list").replaceChildren(...rows.map(r => {
    const li = el("li", r.state), body = el("div");
    body.append(el("b", null, r.part), el("small", null, r.says));
    li.append(el("span", "dot", mark[r.state]), body); return li;
  }));
  const n = s => d.parts.filter(r => r.state === s).length;
  $("hl-note").textContent = n("bad") ? `${n("bad")} not working${n("warn") ? `, ${n("warn")} to look at` : ""}.` : n("warn") ? `${n("warn")} to look at.` : "Everything's working.";
}
$("hl-again").onclick = loadHealth;
