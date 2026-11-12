/* ---------- persona editor ---------- */
const ed = { list: [], styles: [], voices: {}, cur: null, isNew: false, medium: "anime", loraOn: false, paused: false };
const lines = v => v.split("\n").map(x => x.trim()).filter(Boolean);
const words = v => v.split(/\s+/).map(x => x.replace(/^#/, "")).filter(Boolean);

async function loadEditable() {
  try {
    const d = await api("api/personas/edit");
    ed.list = d.personas; ed.styles = d.styles; ed.voices = d.voices || {};
    $("p-note").textContent = d.error ? `The personas file has a problem: ${d.error}` : "The characters comics are made with.";
    renderPersonaList();
  } catch (e) { if (e.message !== "signed out") toast(e.message); }
}
function renderPersonaList() {
  const list = $("p-list"); list.replaceChildren();
  if (!ed.list.length) { list.append(el("li", "note", "No personas yet.")); return; }
  for (const p of ed.list) {
    const li = el("li"), b = el("button", "prow"); b.type = "button";
    const who = { handle: p.handle, name: p.name || p.handle, avatar: p.has_avatar };
    const mid = el("div"); mid.append(el("div", "nm", who.name));
    const sub = el("div", "sub"); sub.append(el("span", null, "@" + p.handle), el("span", "badge", LABEL[p.medium] || p.medium || "?"));
    if (p.lora?.enabled) sub.append(el("span", "badge on", "Style " + p.lora.style));
    if (p.paused) sub.append(el("span", "badge", "Paused"));
    mid.append(sub);
    b.append(avatarEl("sm", who), mid, el("span", "go", "Edit"));
    b.onclick = () => openEditor(p); li.append(b); list.append(li);
  }
}
$("p-new").onclick = () => openEditor(null);

// Build from a description: the worker's text model drafts the persona; it opens in the editor.
const DRAFT_KEY = "dreamfeed.draftJob";
function draftNote(text) { const n = $("p-build-status"); n.hidden = !text; n.textContent = text || ""; }
async function watchDraft(job) {
  $("p-build").disabled = true;
  try {
    for (;;) {
      const d = await api(`api/personas/draft?job=${job}`);
      if (d.status === "done" && d.draft) {
        draftNote(""); try { localStorage.removeItem(DRAFT_KEY); } catch {}
        openEditor(d.draft, true); toast("Draft ready. Check it, change anything, then Save.");
        break;
      }
      if (d.status === "failed" || d.status === "cancelled") {
        draftNote(`Couldn't build it: ${d.message || d.status}`); try { localStorage.removeItem(DRAFT_KEY); } catch {}
        break;
      }
      draftNote(d.status === "running" ? "Writing the persona… (about a minute)"
        : d.night_running ? "Waiting for tonight's run to finish, then writing it."
        : d.ahead ? `Waiting for ${d.ahead} earlier request${d.ahead > 1 ? "s" : ""} (clips, styles) to finish.`
        : "Starting…");
      await new Promise(r => setTimeout(r, 3000));
    }
  } catch (e) { draftNote(e.message); }
  $("p-build").disabled = false;
}
$("p-build").onclick = async () => {
  const description = $("p-desc").value.trim();
  if (description.length < 10) { draftNote("Describe them in a few words: who they are and what they post."); return; }
  try {
    const { job } = await api("api/personas/draft", { description });
    try { localStorage.setItem(DRAFT_KEY, String(job)); } catch {}
    $("p-desc").value = ""; watchDraft(job);
  } catch (e) { draftNote(e.message); }
};
try { const j = localStorage.getItem(DRAFT_KEY); if (j && /^\d+$/.test(j)) watchDraft(j); } catch {}

function setPressed(id, on, yes, no) { const b = $(id); b.setAttribute("aria-pressed", String(on)); b.textContent = on ? yes : no; }
function renderMedium() {
  document.querySelectorAll("#e-medium button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.m === ed.medium)));
  const sel = $("e-style"), keep = sel.value, opts = ed.styles.filter(s => s.medium === ed.medium);
  sel.replaceChildren(...opts.map(s => { const o = el("option", null, s.name); o.value = s.name; return o; }));
  if (opts.some(s => s.name === keep)) sel.value = keep;
  const art = $("e-art"), keepArt = art.value, none = el("option", null, "none"); none.value = "";
  art.replaceChildren(none, ...opts.map(s => { const o = el("option", null, s.name); o.value = s.name; return o; }));
  if (opts.some(s => s.name === keepArt)) art.value = keepArt;
  $("e-lora-on").disabled = !opts.length && !ed.loraOn;
  $("e-lora-note").textContent = opts.length ? "Draws their posts in an artist style you trained."
    : `No ${LABEL[ed.medium].toLowerCase()} styles trained yet (Trained styles, on the dashboard).`;
  renderLora();
}
function renderLora() {
  setPressed("e-lora-on", ed.loraOn, "On", "Off");
  $("e-lora-box").hidden = !ed.loraOn;
  $("e-strength-v").textContent = (+$("e-strength").value).toFixed(2);
  $("e-art-box").hidden = !$("e-art").value;
  $("e-art-strength-v").textContent = (+$("e-art-strength").value).toFixed(2);
}
function renderRanges() {
  $("e-weight-v").textContent = `${+$("e-weight").value}×`;
  $("e-video-v").textContent = `${Math.round(100 * $("e-video").value)}%`;
}
document.querySelectorAll("#e-medium button").forEach(b => b.onclick = () => { ed.medium = b.dataset.m; renderMedium(); });
$("e-lora-on").onclick = () => { ed.loraOn = !ed.loraOn; renderMedium(); };
$("e-strength").oninput = renderLora; $("e-art").onchange = renderLora; $("e-art-strength").oninput = renderLora;
$("e-weight").oninput = renderRanges; $("e-video").oninput = renderRanges;
$("e-paused").onclick = () => { ed.paused = !ed.paused; setPressed("e-paused", ed.paused, "Yes", "No"); };

function addKind(k) {
  const n = $("kind-tpl").content.firstElementChild.cloneNode(true);
  n.querySelector(".k-name").value = k.kind || "";
  n.querySelector(".k-rating").value = k.rating || "explicit";
  n.querySelector(".k-weight").value = k.weight ?? 1;
  n.querySelector(".k-prompt").value = k.prompt || "";
  n.querySelector(".k-caps").value = (k.captions || []).join("\n");
  n.querySelector(".rm").onclick = () => { n.remove(); };
  $("e-kinds").append(n);
}
$("e-add-kind").onclick = () => { addKind({ kind: "", rating: "explicit", weight: 1 }); $("e-kinds").lastElementChild.querySelector(".k-name").focus(); };

const NEW_PERSONA = { medium: "anime", weight: 1, video_share: 0.2, avatar: "portrait, upper body, looking at viewer, smile",
  posts: [{ kind: "pinup", rating: "questionable", weight: 1, prompt: "solo, {outfit}, looking at viewer, {setting}", captions: ["new post"] }] };

function openEditor(p, asNew = false) {
  ed.isNew = !p || asNew; ed.cur = p || NEW_PERSONA;
  const c = ed.cur;
  $("e-title").textContent = ed.isNew ? "New persona" : (c.name || c.handle);
  $("e-err").textContent = "";
  $("e-name").value = c.name || ""; $("e-handle").value = c.handle || ""; $("e-handle").disabled = !ed.isNew;
  $("e-handle-note").hidden = !ed.isNew;
  $("e-bio").value = c.bio || ""; $("e-note").value = c.based_on || "";
  $("e-look").value = c.look || ""; $("e-chars").value = (c.characters || []).join("\n"); $("e-avatar").value = c.avatar || "";
  $("e-outfits").value = (c.outfits || []).join("\n"); $("e-partners").value = (c.partners || []).join("\n"); $("e-girlfriends").value = (c.girlfriends || []).join("\n"); $("e-friends").value = (c.friends || []).join("\n"); $("e-must").value = (c.must_show || []).map(g => g.join(", ")).join("\n"); $("e-mustnot").value = (c.must_not_show || []).join(", "); $("e-settings").value = (c.settings || []).join("\n");
  $("e-emoji").value = (c.emoji || []).join(" "); $("e-tags").value = (c.hashtags || []).join(" "); $("e-neg").value = c.negative || "";
  $("e-more").open = !!(c.outfits?.length || c.partners?.length || c.girlfriends?.length || c.friends?.length || c.must_show?.length || c.settings?.length || c.negative);
  $("e-weight").value = c.weight ?? 1; $("e-video").value = c.video_share ?? 0.2; renderRanges();
  ed.paused = !!c.paused; setPressed("e-paused", ed.paused, "Yes", "No");
  ed.medium = c.medium || "anime"; ed.loraOn = !!c.lora?.enabled;
  $("e-strength").value = c.lora?.strength ?? 0.8; $("e-female").checked = !!c.lora?.female_only;
  $("e-art-strength").value = c.art?.strength ?? 0.5; $("e-art").value = "";
  renderMedium();
  if (c.art?.style) {
    if (![...$("e-art").options].some(o => o.value === c.art.style)) {
      const o = el("option", null, c.art.style + " (file missing)"); o.value = c.art.style; $("e-art").append(o);
    }
    $("e-art").value = c.art.style;
  }
  renderLora();
  if (c.lora?.style) {
    if (![...$("e-style").options].some(o => o.value === c.lora.style)) {   // trained file missing right now
      const o = el("option", null, c.lora.style + " (file missing)"); o.value = c.lora.style; $("e-style").append(o);
    }
    $("e-style").value = c.lora.style;
  }
  const vs = $("e-voice"), own = el("option", null, "their example captions"); own.value = "";
  vs.replaceChildren(own, ...Object.entries(ed.voices).map(([n, count]) => {
    const o = el("option", null, `${n} (${count} posts)`); o.value = n; return o; }));
  if (c.voice && !(c.voice in ed.voices)) { const o = el("option", null, `${c.voice} (no saved posts)`); o.value = c.voice; vs.append(o); }
  vs.value = c.voice || "";
  $("e-voice-note").textContent = "every post gets a new caption, written like these. Artist posts come from training a style.";
  $("e-kinds").replaceChildren(); for (const k of c.posts || []) addKind(k);
  $("e-strict").textContent = ed.isNew ? "" : c.strict ? "🛡 Stricter adult checks are on for this persona (set automatically from their look)." : "";
  $("e-pic-row").hidden = ed.isNew;
  fillAvatar($("e-av"), { handle: c.handle, name: c.name, avatar: c.has_avatar });
  $("e-pic-note").textContent = c.has_avatar ? "Made from their look." : "Made the next time they post.";
  $("e-pic").disabled = !c.has_avatar;
  $("e-danger").hidden = ed.isNew; $("e-del-confirm").hidden = true; $("e-del").hidden = false;
  $("e-del-name").textContent = c.name || c.handle || "";
  $("editor").hidden = false; $("editor").scrollTop = 0; document.body.style.overflow = "hidden";
  (ed.isNew ? $("e-name") : $("e-close")).focus();
}
function closeEditor() { $("editor").hidden = true; document.body.style.overflow = ""; }
$("e-close").onclick = closeEditor;
addEventListener("keydown", e => { if (!$("editor").hidden && e.key === "Escape") closeEditor(); });

function collect() {
  const posts = [...$("e-kinds").children].map(n => ({
    kind: n.querySelector(".k-name").value.trim() || "post", rating: n.querySelector(".k-rating").value,
    weight: +n.querySelector(".k-weight").value || 1, prompt: n.querySelector(".k-prompt").value.trim(),
    captions: lines(n.querySelector(".k-caps").value) }));
  return {
    handle: $("e-handle").value.trim().toLowerCase(), name: $("e-name").value.trim(), medium: ed.medium,
    bio: $("e-bio").value.trim(), based_on: $("e-note").value.trim(), look: $("e-look").value.trim(),
    characters: lines($("e-chars").value), avatar: $("e-avatar").value.trim(),
    outfits: lines($("e-outfits").value), partners: lines($("e-partners").value), girlfriends: lines($("e-girlfriends").value), friends: lines($("e-friends").value).map(h => h.replace(/^@/, "").toLowerCase()),
    must_not_show: $("e-mustnot").value.split(",").map(t => t.trim()).filter(Boolean),
    must_show: lines($("e-must").value).map(l => l.split(",").map(t => t.trim()).filter(Boolean)).filter(g => g.length), settings: lines($("e-settings").value),
    emoji: words($("e-emoji").value), hashtags: words($("e-tags").value), negative: $("e-neg").value.trim(),
    weight: +$("e-weight").value, video_share: +$("e-video").value, paused: ed.paused, posts, voice: $("e-voice").value,
    lora: (ed.loraOn || ed.cur.lora) && $("e-style").value ? { style: $("e-style").value, strength: +$("e-strength").value,
                                 female_only: $("e-female").checked, enabled: ed.loraOn } : null,
    art: ed.loraOn && $("e-art").value ? { style: $("e-art").value, strength: +$("e-art-strength").value } : null,
  };
}
$("e-form").onsubmit = e => { e.preventDefault(); $("e-save").click(); };
$("e-save").onclick = async () => {
  const body = collect();
  if (!body.name) { $("e-err").textContent = "Give them a name."; $("editor").scrollTop = 0; return; }
  $("e-save").disabled = true;
  try {
    await api("api/personas/save", { persona: body, original: ed.isNew ? null : ed.cur.handle });
    closeEditor(); toast(ed.isNew ? `Added ${body.name}. Tap Post now on their profile for a first post.` : "Saved. Applies from their next post.");
    await loadEditable(); loadPeople();
  } catch (err) { $("e-err").textContent = err.message; $("editor").scrollTop = 0; }
  $("e-save").disabled = false;
};
$("e-del").onclick = () => { $("e-del").hidden = true; $("e-del-confirm").hidden = false; };
$("e-del-no").onclick = () => { $("e-del").hidden = false; $("e-del-confirm").hidden = true; };
$("e-del-yes").onclick = async () => {
  try { await api("api/personas/delete", { handle: ed.cur.handle }); closeEditor(); toast("Removed."); await loadEditable(); loadPeople(); refreshSummary(); }
  catch (err) { $("e-err").textContent = err.message; $("editor").scrollTop = 0; }
};
$("e-pic").onclick = async () => {
  try {
    await api("api/personas/avatar", { handle: ed.cur.handle });
    ed.cur.has_avatar = false; fillAvatar($("e-av"), { name: ed.cur.name });
    $("e-pic-note").textContent = "A new one is made the next time they post."; $("e-pic").disabled = true;
    loadPeople(); loadEditable();
  } catch (err) { toast(err.message); }
};

new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) loadMore(); }, { rootMargin: "800px" }).observe($("sentinel"));
refreshSummary();
loadPeople().then(() => { for (const it of state.items) if (it.persona) fillAvatar(it.el.querySelector(".av"), personaOf(it.persona.handle) || it.persona); });
// The page opens what its address names (old #live-style links too).
{
  const old = { dashboard: "dashboard", comics: "comics", following: "live", live: "live" }[location.hash.slice(1)];
  history.replaceState({ n: 0 }, "", old ? BASE + old : location.pathname);
}
state.view = "";   // so setView runs for the first view
route();
