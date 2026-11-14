/* ---------- updates ----------
   The 🔔 page: what happened, newest first, by topic (Live, Recordings, Comics, Health); opening
   it marks them read. Nothing is pushed: the count in the header is all that tells you. */
const up = { topic: "", offset: 0, gen: 0, counts: {} };
const UP_TOPIC = { live: "Live", recordings: "Recordings", comics: "Comics", health: "Health" };
$("upd-btn").onclick = () => go("updates");
$("search-btn").onclick = () => go("search");
function dayLabel(t) {
  const d = new Date(t * 1000), today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  return days === 0 ? "Today" : days === 1 ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}
// one row of a list (Updates, History): its picture, what it is, when; a tap opens it, ✕ takes it away
function listRow(o) {
  const row = el("div", "lrow" + (o.unread ? " unread" : "")), open = el("button", "lrow-open"); open.type = "button";
  const pic = el("span", "lrow-pic");
  if (o.thumb) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.referrerPolicy = "no-referrer"; im.src = viaUs(o.thumb);
                 im.onerror = () => im.remove(); pic.append(im); }
  else pic.append(el("span", "lrow-ico", o.icon || "•"));
  const words = el("span", "lrow-words");
  words.append(el("b", null, o.title));
  if (o.body) words.append(el("small", null, o.body));
  const meta = el("small", "lrow-meta", [o.label, o.at && new Date(o.at * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })].filter(Boolean).join(" · "));
  if (o.badge) meta.prepend(el("span", "lrow-badge", o.badge), " ");
  words.append(meta);
  open.append(pic, words); open.onclick = o.open;
  const x = el("button", "lrow-x", "✕"); x.type = "button"; x.setAttribute("aria-label", "Remove"); x.onclick = () => { o.remove(); row.remove(); };
  row.append(open, x);
  return row;
}
function appendByDay(box, items, toRow) {
  for (const it of items) {
    const label = dayLabel(it.at), last = box.lastElementChild;
    if (!last || last.dataset.day !== label) { const h = el("h3", "lday", label); h.dataset.day = label; box.append(h); }
    const row = toRow(it); row.dataset.day = label; box.append(row);
  }
}
async function loadUpdates(more) {
  const gen = more ? up.gen : ++up.gen;
  if (!more) { up.offset = 0; $("up-list").replaceChildren(); $("up-note").textContent = "Looking…"; }
  $("up-more").hidden = true;
  let d;
  try { d = await api(`api/notices?topic=${up.topic}&offset=${up.offset}`); } catch (err) { if (gen === up.gen) $("up-note").textContent = err.message; return; }
  if (gen !== up.gen) return;
  up.counts = d.counts || {};
  document.querySelectorAll("#up-topic button").forEach(b => {
    const n = b.dataset.t ? up.counts[b.dataset.t] : Object.values(up.counts).reduce((a, x) => a + x, 0);
    b.textContent = (b.dataset.t ? UP_TOPIC[b.dataset.t] : "All") + (n ? ` ${n}` : "");
  });
  appendByDay($("up-list"), d.notices, n => listRow({
    title: n.title, body: n.body, thumb: n.thumb, at: n.at, unread: !n.read, label: up.topic ? "" : UP_TOPIC[n.topic],
    icon: { live: "●", recordings: "▶", comics: "📖", health: "⚠" }[n.topic], badge: n.live_now ? "● live now" : "",
    open: () => { if (n.link) go(n.link); },
    remove: () => api("api/notices/clear", { id: n.id }).catch(err => toast(err.message)),
  }));
  up.offset += d.notices.length;
  $("up-more").hidden = !d.more;
  $("up-note").textContent = $("up-list").children.length ? ""
    : up.topic ? `Nothing about ${UP_TOPIC[up.topic].toLowerCase()} yet.`
    : "Nothing yet. Rooms you follow going live, your recordings and their highlights, comics you follow getting new pages and anything that stops working show up here.";
  if (!more && d.notices.some(n => !n.read)) {
    try { await api("api/notices/read", { topic: up.topic }); } catch {}
    refreshSummary();
  }
}
document.querySelectorAll("#up-topic button").forEach(b => b.onclick = () => {
  up.topic = b.dataset.t;
  document.querySelectorAll("#up-topic button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  loadUpdates();
});
$("up-more").onclick = () => loadUpdates(true);
$("up-clear").onclick = async () => {
  if (!confirm(up.topic ? `Clear the ${UP_TOPIC[up.topic].toLowerCase()} updates?` : "Clear all updates?")) return;
  try { await api("api/notices/clear", { topic: up.topic }); } catch (err) { return toast(err.message); }
  loadUpdates(); refreshSummary();
};
