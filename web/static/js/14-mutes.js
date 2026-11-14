/* ---------- mute list ----------
   The Dashboard's Mute: words, accounts (on a site, or any) and subreddits left out of the Feed,
   Videos, Comics, Discover and Search (webapp/mutes.py). A post's 🔇 mutes its author, or its
   subreddit, from where you are. */
const MU_SITE = { "": "any site", x: "X", bsky: "Bluesky", reddit: "Reddit", e621: "e621", xvideos: "xvideos", chaturbate: "Chaturbate", comics: "comics" };
const MU_HINT = { word: "a word, e.g. feet", account: "a name, e.g. someone", subreddit: "a subreddit, e.g. r/pics" };
async function loadMutes() {
  try { renderMutes((await api("api/mutes")).mutes); } catch (err) { $("mu-err").textContent = err.message; }
}
function renderMutes(list) {
  $("mu-list").replaceChildren(...list.map(m => {
    const li = el("li"), body = el("div"), x = el("button", "secondary", "Unmute"); x.type = "button";
    body.append(el("b", null, m.kind === "subreddit" ? `r/${m.value}` : m.value),
                el("small", null, m.kind === "word" ? "word" : m.kind === "subreddit" ? "subreddit" : `account on ${MU_SITE[m.site] || m.site}`));
    x.onclick = () => changeMute({ kind: m.kind, value: m.value, site: m.site, remove: true });
    li.append(body, x); return li;
  }));
  if (!list.length) $("mu-list").append(el("li", "note", "Nothing muted."));
}
async function changeMute(m, quiet) {
  $("mu-err").textContent = "";
  try {
    const d = await api("api/mutes", m);
    if (state.view === "dash") renderMutes(d.mutes);
    if (quiet) toast(m.remove ? "Unmuted." : `Muted ${quiet}.`, m.remove ? null : "Undo", () => changeMute({ ...m, remove: true }, quiet));
    return true;
  } catch (err) { if (quiet) toast(err.message); else $("mu-err").textContent = err.message; return false; }
}
$("mu-kind").onchange = () => {
  const k = $("mu-kind").value; $("mu-site").hidden = k !== "account"; $("mu-value").placeholder = MU_HINT[k];
};
$("mu-form").onsubmit = async e => {
  e.preventDefault();
  const value = $("mu-value").value.trim(); if (!value) return;
  if (await changeMute({ kind: $("mu-kind").value, value, site: $("mu-site").value })) $("mu-value").value = "";
};
// a post's 🔇: who posted it (and where), out of your Feed from now on
function muteButton(p, card) {
  const b = el("button", "comments-btn mute-btn", "🔇"); b.type = "button"; b.title = "Mute…";
  b.onclick = () => {
    const opts = [];
    if (p.author && p.source !== "e621") opts.push([`Mute ${p.source === "reddit" ? "u/" : "@"}${p.author}`, { kind: "account", value: p.author, site: p.source }]);
    for (const a of p.source === "e621" ? (p.artists || []).slice(0, 2) : []) opts.push([`Mute artist ${a}`, { kind: "account", value: a, site: "e621" }]);
    if (p.source === "reddit" && p.place) opts.push([`Mute r/${p.place}`, { kind: "subreddit", value: p.place }]);
    if (!opts.length) return toast("Nothing to mute here: add a word on the Dashboard.");
    const row = el("div", "mute-pick");
    for (const [label, m] of opts) {
      const o = el("button", "secondary", label); o.type = "button";
      o.onclick = async () => { if (await changeMute(m, label.replace(/^Mute /, ""))) card.remove(); };
      row.append(o);
    }
    const no = el("button", "secondary", "Cancel"); no.type = "button"; no.onclick = () => row.remove();
    row.append(no);
    b.closest(".acts").after(row);
  };
  return b;
}
