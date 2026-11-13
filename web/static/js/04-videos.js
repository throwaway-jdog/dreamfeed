/* More videos: X's own swipe-up feed (what its full-screen player shows next), from one video.
   One video a screen; the one on screen plays, with sound once you've asked for it. */
const vf = { gen: 0, posts: [], cursor: null, loading: false, muted: true, seed: null, cur: -1, obs: null };
// X: X's own feed. Reddit and e621: more from where it came from (its subreddit or search, then yours).
function vfPath(p) { return p.source === "x" ? `videos/${p.id.split(":")[1]}/${enc(p.author)}` : `videos/${p.source}/${enc(p.id.split(":")[1])}`; }
function openVideos(p) { nav.posts.set(p.id, p); go(vfPath(p)); }
async function showVideos(tid, handle, site = "x") {
  const gen = ++vf.gen, pid = `${site}:${tid}`;
  Object.assign(vf, { posts: [], cursor: null, loading: false, seed: { tid, handle: handle || "", site, pid }, cur: -1 });
  $("vf-track").replaceChildren(); $("vfeed").hidden = false;
  vfSoundLabel();
  vf.obs = vf.obs || new IntersectionObserver(es => {
    for (const e of es) {
      const v = e.target.querySelector("video");
      if (e.isIntersecting && e.intersectionRatio > .6) {
        vf.cur = vf.posts.findIndex(x => x.el === e.target);
        v.muted = vf.muted; v.play().catch(() => { v.muted = true; vf.muted = true; vfSoundLabel(); v.play().catch(() => {}); });
        const p = vf.posts[vf.cur];
        if (p && vf.seed.site === "x") setUrl(vfPath(p));
        // the next two start buffering now, so swiping up plays at once
        for (const x of vf.posts.slice(vf.cur + 1, vf.cur + 3)) {
          const nv = x.el.querySelector("video");
          if (!nv.dataset.warm) { nv.dataset.warm = "1"; nv.preload = "auto"; nv.load(); }
        }
        if (vf.cur >= vf.posts.length - 4) vfMore();
      } else { v.pause(); }
    }
  }, { root: $("vf-track"), threshold: [0, .6, 1] });
  // back from a video's comments (or its author): the same list, at that video
  const last = vf.last;
  const back = last && (last.seed.pid === pid ? last.curId : last.posts.some(x => x.id === pid) && pid);
  if (back) {
    vf.seed = last.seed; vf.cursor = last.cursor; vfAdd(last.posts);
    const at = vf.posts.find(x => x.id === back) || vf.posts[0];
    requestAnimationFrame(() => { $("vf-track").scrollTop = at.el.offsetTop; });
    return;
  }
  let seed = nav.posts.get(pid);
  if (!seed) { try { seed = (await api(`api/post?id=${enc(pid)}`)).post; } catch {} }
  if (gen !== vf.gen) return;
  if (seed && seed.media.some(m => m.kind === "video" || m.kind === "hls")) vfAdd([seed]);
  vfMore();
}
function vfAdd(posts) {
  for (const p of posts) {
    if (vf.posts.some(x => x.id === p.id)) continue;
    const m = p.media.find(x => x.kind === "video" || x.kind === "hls");
    if (!m) continue;
    const slide = el("section", "vf-slide"), v = el("video");
    v.playsInline = v.loop = true; v.muted = vf.muted; v.preload = vf.posts.length < 2 ? "auto" : "metadata";
    if (vf.posts.length < 2) v.dataset.warm = "1";
    if (m.poster) v.poster = viaUs(m.poster);
    if (m.kind === "hls") feedHls(v, m); else v.src = viaUs(m.url);
    v.onclick = () => { if (v.paused) v.play().catch(() => {}); else v.pause(); };
    const info = el("div", "vf-info"), who = el("span", "vf-who"), av = el("span", "av", p.avatar ? null : (p.author || "?").slice(0, 1).toUpperCase());
    if (p.avatar) { const im = el("img"); im.alt = ""; im.src = p.avatar; av.append(im); }
    const person = p.source === "x" ? { x: p.author } : p.source === "reddit" ? { reddit: p.author } : p.source === "bsky" ? { bsky: p.author }
      : (p.artists || []).length ? { e621: p.artists[0] } : null;
    who.append(av, el("span", null, p.source === "x" ? "@" + p.author : p.source === "reddit" ? `u/${p.author} · r/${p.place}` : p.author || "e621"));
    if (person) who.onclick = () => openPerson(person);
    info.append(who);
    if (p.text) { const t = el("p", "vf-text", p.text); t.onclick = () => t.classList.toggle("open"); info.append(t); }
    const nums = [p.likes != null && `♥ ${Number(p.likes).toLocaleString()}`, p.views != null && `${Number(p.views).toLocaleString()} views`,
                  relTime(p.posted_at)].filter(Boolean).join(" · ");
    if (nums) info.append(el("small", "vf-nums", nums));
    const acts = el("div", "vf-acts");
    const cm = el("button"); cm.type = "button"; cm.append("💬", el("small", null, p.comments ? Number(p.comments).toLocaleString() : ""));
    cm.onclick = () => openPost(p);
    const sv = el("button"); sv.type = "button";
    const showSave = () => { sv.replaceChildren(p.saved ? "★" : "☆", el("small", null, p.saved ? "Saved" : "Save")); sv.setAttribute("aria-pressed", String(!!p.saved)); };
    sv.onclick = async () => {
      sv.disabled = true;
      try { const d = await api("api/following/save", { post: p, save: !p.saved }); p.saved = d.saved; } catch (err) { toast(err.message); }
      sv.disabled = false; showSave();
    };
    showSave();
    const out = el("a"); out.href = p.link; out.target = "_blank"; out.rel = "noreferrer noopener";
    out.append("↗", el("small", null, { x: "X", reddit: "Reddit", e621: "e621", bsky: "Bluesky" }[p.source]));
    acts.append(cm, sv, out);
    slide.append(v, info, acts);
    p.el = slide; vf.posts.push(p);
    $("vf-track").append(slide); vf.obs.observe(slide);
  }
}
async function vfMore() {
  if (vf.loading || (vf.cursor === null && vf.posts.length > 1)) return;
  const gen = vf.gen, s = vf.seed; vf.loading = true;
  const msg = el("p", "vf-msg", vf.posts.length ? "" : "Reading X's videos…");
  if (!vf.posts.length) $("vf-track").append(msg);
  try {
    const d = await api(s.site === "x" ? `api/x/related?id=${s.tid}&handle=${enc(s.handle)}&cursor=${enc(vf.cursor || "")}`
                                       : `api/videos/more?id=${enc(s.pid)}&cursor=${enc(vf.cursor || "")}`);
    if (gen !== vf.gen) return;
    msg.remove(); vf.cursor = d.cursor || null;
    vfAdd(d.posts);
    if (!vf.posts.length) $("vf-track").append(el("p", "vf-msg", `${{ reddit: "Reddit", e621: "e621", bsky: "Bluesky" }[s.site] || "X"} has no more videos for this one.`));
  } catch (err) { if (gen === vf.gen) { msg.textContent = err.message; if (!msg.isConnected) toast(err.message); } }
  finally { if (gen === vf.gen) vf.loading = false; }
}
function vfStep(d) {
  const t = $("vf-track"), i = Math.max(0, Math.min(vf.posts.length - 1, (vf.cur < 0 ? 0 : vf.cur) + d));
  if (vf.posts[i]) t.scrollTo({ top: vf.posts[i].el.offsetTop, behavior: "smooth" });
}
function vfSoundLabel() { $("vf-sound").textContent = vf.muted ? "🔇 Tap for sound" : "🔊 Sound on"; }
function vfSound(on) {
  vf.muted = !on; vfSoundLabel();
  const p = vf.posts[vf.cur]; if (p) { const v = p.el.querySelector("video"); v.muted = vf.muted; v.play().catch(() => {}); }
}
$("vf-sound").onclick = () => vfSound(vf.muted);
$("vf-close").onclick = () => leave();
function closeVideos() {
  vf.gen++;
  if (vf.posts.length) vf.last = { posts: vf.posts.map(({ el, ...p }) => p), cursor: vf.cursor, seed: vf.seed,
                                   curId: (vf.posts[vf.cur] || vf.posts[0]).id };
  for (const p of vf.posts) { const v = p.el && p.el.querySelector("video"); if (v) { v.pause(); v.removeAttribute("src"); v.load(); } if (vf.obs && p.el) vf.obs.unobserve(p.el); }
  vf.posts = []; $("vf-track").replaceChildren(); $("vfeed").hidden = true;
}

