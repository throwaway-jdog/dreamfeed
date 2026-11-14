/* ---------- history ----------
   What you've opened here, newest first (⋮ History): posts, videos, comics, live rooms, your
   recordings. Videos and comics are noted by the server as they load; the rest the page tells it. */
const hi = { kind: "", offset: 0, gen: 0 };
const HI_KIND = { post: "Post", video: "Video", comic: "Comic", room: "Live", recording: "Recording" };
function noteHistory(kind, key, title, link, thumb, data) {
  api("api/history", { kind, key: String(key), title: String(title || "").slice(0, 300), link, thumb: thumb || null, data: data || null }).catch(() => {});
}
$("sheet-history").onclick = () => { $("sheet").hidden = true; $("menu-btn").setAttribute("aria-expanded", "false"); go("history"); };
function openHistory(it) {
  const d = it.data;
  if (it.kind === "post" && d && d.id) return openPost(d);
  if (it.kind === "video" && d && d.id) return openVid(d);
  if (it.kind === "comic" && d && d.id) return openComic(d);
  if (it.kind === "room") return openRoom(roomFor(it.key), null);
  go(it.link);
}
async function loadHistory(more) {
  const gen = more ? hi.gen : ++hi.gen;
  if (!more) { hi.offset = 0; $("hi-list").replaceChildren(); }
  $("hi-more").hidden = true;
  let d;
  try { d = await api(`api/history?kind=${hi.kind}&offset=${hi.offset}`); } catch (err) { if (gen === hi.gen) toast(err.message); return; }
  if (gen !== hi.gen) return;
  appendByDay($("hi-list"), d.items, it => listRow({
    title: it.title, thumb: it.thumb, at: it.at, label: hi.kind ? "" : HI_KIND[it.kind],
    icon: { post: "▤", video: "▶", comic: "📖", room: "●", recording: "▶" }[it.kind], open: () => openHistory(it),
    remove: () => api("api/history/remove", { kind: it.kind, key: it.key }).catch(err => toast(err.message)),
  }));
  hi.offset += d.items.length;
  $("hi-more").hidden = !d.more;
  if (!$("hi-list").children.length) $("hi-list").append(el("p", "note", hi.kind ? "Nothing of these yet." : "Nothing yet: what you open shows up here."));
}
document.querySelectorAll("#hi-kind button").forEach(b => b.onclick = () => {
  hi.kind = b.dataset.k;
  document.querySelectorAll("#hi-kind button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  loadHistory();
});
$("hi-more").onclick = () => loadHistory(true);
$("hi-clear").onclick = async () => {
  if (!confirm(hi.kind ? `Clear your ${HI_KIND[hi.kind].toLowerCase()} history?` : "Clear all your history? (For you keeps what it learned.)")) return;
  try { await api("api/history/remove", { all: true, kind: hi.kind }); } catch (err) { return toast(err.message); }
  loadHistory();
};
