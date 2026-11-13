/* One profile across sites: a Chaturbate room (followed or from Discover) with the X and
   Reddit accounts linked to it (from its bio, or by you), their posts and your videos of it;
   or an X or Reddit account on its own (from the Feed or Discover), with a preview to fetch. */
const pf = { room: null, key: null, data: null, videos: [], gen: 0, timer: null, ptimer: null, card: null };
function openRoomProfile(r) { nav.rooms.set(r.name, r); openPerson({ room: r.name }); }
async function showPerson(key) {
  if (key.room && nav.rooms.has(key.room)) pf.card = nav.rooms.get(key.room);
  const gen = ++pf.gen;
  clearTimeout(pf.timer); clearTimeout(pf.ptimer); clearTimeout(pf.ftimer); pf.toldFail = false;
  pf.key = key; pf.videos = []; pf.data = null; pf.posts = null; pf.room = key.room ? { name: key.room } : null;
  if (!key.room) pf.card = null;
  $("pf-title").textContent = key.room || (key.x ? "@" + key.x : key.e621 ? key.e621.replace(/_/g, " ") : key.bsky ? "@" + key.bsky : "u/" + key.reddit);
  $("pf-info").textContent = "Loading…"; $("pf-about").hidden = true; $("pf-head").hidden = true;
  for (const id of ["pf-links", "pf-grid", "pf-posts", "pf-xv-grid", "pf-rg-grid"]) $(id).replaceChildren();
  pf.xv = pf.rg = null; $("pf-tabs").hidden = true; clearTimeout(pf.ltimer);
  for (const id of ["pf-prev-sec", "pf-vid-sec", "pf-post-sec"]) $(id).hidden = true;
  $("pf-live").hidden = true; $("pf-open").hidden = true;
  $("pf-view").hidden = false; $("pf-view").scrollTop = 0;
  await loadPerson(gen);
}
async function loadPerson(gen) {
  const k = pf.key, q = k.room ? `room=${encodeURIComponent(k.room)}` : k.x ? `x=${encodeURIComponent(k.x)}`
    : k.e621 ? `e621=${encodeURIComponent(k.e621)}` : k.bsky ? `bsky=${encodeURIComponent(k.bsky)}` : `reddit=${encodeURIComponent(k.reddit)}`;
  let d;
  try { d = await api(`api/profile?${q}`); } catch (err) { if (gen === pf.gen) $("pf-info").textContent = err.message; return; }
  if (gen !== pf.gen) return;
  pf.data = d;
  if (d.room && !pf.room) { pf.room = { name: d.room }; pf.key = { room: d.room }; }
  const room = d.room, card = pf.card || {}, live = d.followed ? d.live : !!card.live;
  $("pf-title").textContent = room || $("pf-title").textContent;
  $("pf-open").hidden = !room;
  if (room) { $("pf-open").href = `https://chaturbate.com/${encodeURIComponent(room)}/`; $("pf-open").textContent = "Chaturbate"; }
  $("pf-live").hidden = !(room && live);
  const act = d.action, pending = act && act.status === "queued", fb = $("pf-follow");
  fb.hidden = !room;
  fb.disabled = !!pending;
  fb.textContent = pending ? (act.action === "follow" ? "Following…" : "Unfollowing…") : d.followed ? "Following ✓" : "Follow";
  fb.classList.toggle("following", !!d.followed);
  if (act && act.status === "failed" && !pf.toldFail) { pf.toldFail = true; toast(`Chaturbate didn't take it: ${act.error || "?"}`); }
  if (pending) pf.ftimer = setTimeout(() => { if (gen === pf.gen && !$("pf-view").hidden) loadPerson(gen); }, 3000);
  else if (act && act.status === "done" && pf.waitingFollow) { pf.waitingFollow = false; refreshFollowing(); }
  const b = d.bio || {}, times = d.times || card.times || [];
  const when = !room ? "" : live ? "Live now" : d.last_live ? `Last live ${relTime(new Date(d.last_live * 1000).toISOString())} ago`
    : b.last_broadcast ? `Last live ${b.last_broadcast}` : "";
  $("pf-info").textContent = [when, usualHours(times), b.age ? `${b.age}` : "", b.location,
    b.followers ? `${Number(b.followers).toLocaleString()} followers` : "", room && !d.followed ? "not followed" : ""].filter(Boolean).join(" · ");
  $("pf-about").textContent = b.about || ""; $("pf-about").hidden = !b.about;
  renderDvr(d, gen);
  renderLinks(d);
  renderXHead(d);
  const who = [...(d.e621 || []).map(h => "e621:" + h), ...d.x, ...(d.bsky || []).map(h => "bsky:" + h), ...d.reddit.map(h => "u/" + h), ...(d.redgifs || []).map(h => "rg:" + h),
               ...(d.xvideos || []).map(h => "xv:" + h)].join(" ");
  if (!pf.posts || pf.posts.gen !== gen || pf.posts.who !== who) startPersonPosts(d, gen, who);
  if (room && d.followed && d.videos) {
    try { const v = await api(`api/live/videos?name=${encodeURIComponent(room)}`); if (gen !== pf.gen) return; pf.videos = v.videos; } catch {}
  } else pf.videos = [];
  renderProfile(gen);
}
$("pf-about").onclick = () => $("pf-about").classList.toggle("open");
// The room on your recorder: what it's doing, Record / Pause, Remove (from its list).
function renderDvr(d, gen) {
  const rec = d.dvr || {}, sec = $("pf-dvr-sec");
  sec.hidden = !(d.room && rec.on);
  if (sec.hidden) return;
  const st = rec.room, row = $("pf-dvr"), out = [];
  const act = (label, action, ask) => {
    const b = el("button", "secondary", label); b.type = "button";
    b.onclick = async () => {
      if (ask && !confirm(ask)) return;
      b.disabled = true;
      try { rec.room = (await api("api/dvr", { name: d.room, action })).dvr; if (gen === pf.gen) renderDvr(d, gen); refreshFollowing(); }
      catch (err) { toast(err.message); b.disabled = false; }
    };
    return b;
  };
  if (rec.error) out.push(el("small", null, rec.error));
  else {
    out.push(el("b", null, dvrWords(st, d.live)));
    const next = d.live ? "this stream" : "next stream";
    if (st && st.running && st.once) out.push(act("Record all streams", "record"), act("Stop", "stop"));
    else if (st && st.running) out.push(act("Pause", "pause"), act(d.live ? "Only this stream" : "Only the next stream", "once"));
    else out.push(act(`Record ${next}`, "once"), act("Record all streams", "record"));
    if (st) out.push(act("Remove", "remove", `Take ${d.room} off your recorder's list? Recordings you have stay.`));
    out.push(el("small", null, [st && st.status && st.state === "waiting" ? st.status : "", rec.free ? `${rec.free} free` : ""]
      .filter(Boolean).join(" · ")));
  }
  row.replaceChildren(...out);
}
$("pf-follow").onclick = async () => {
  const d = pf.data; if (!d || !d.room) return;
  if (d.followed && !confirm(`Unfollow ${d.room} on Chaturbate?`)) return;
  try { await api("api/live/follow", { name: d.room, follow: !d.followed }); } catch (err) { return toast(err.message); }
  pf.toldFail = false; pf.waitingFollow = true; loadPerson(pf.gen);
};
function linkLabel(src, h) {
  if (src === "linkpage") { let u; try { u = new URL(h); } catch { return [h, h]; } return [u.hostname.replace(/^www\./, "") + u.pathname, h]; }
  return {
    x: ["@" + h, `https://x.com/${h}`], reddit: ["u/" + h, `https://www.reddit.com/user/${h}`],
    xvideos: [`xvideos: ${h}`, `https://www.xvideos.com/profiles/${h}`], redgifs: [`RedGifs: ${h}`, `https://www.redgifs.com/users/${h}`],
    onlyfans: [`OnlyFans: ${h}`, `https://onlyfans.com/${h}`], fansly: [`Fansly: ${h}`, `https://fansly.com/${h}`],
  }[src] || [h, "#"];
}
// While the room's accounts are being looked for: the profile again in a bit.
function pfLinkWait(gen) {
  clearTimeout(pf.ltimer);
  pf.ltimer = setTimeout(() => { if (gen === pf.gen && !$("pf-view").hidden) loadPerson(gen); }, 6000);
}
function renderLinks(d) {
  const chips = [];
  const chip = (label, href, note, onRemove) => {
    const c = el("span", "pf-chip"), a = el("a", null, label); a.href = href; a.target = "_blank"; a.rel = "noreferrer noopener";
    c.append(a); if (note) c.append(el("small", null, note));
    if (onRemove) { const x = el("button", null, "×"); x.type = "button"; x.title = "Unlink"; x.onclick = onRemove; c.append(x); }
    return c;
  };
  // each link with where it was found; a suggestion (the same name, not linked back) to confirm or not
  for (const l of d.links) {
    const [label, href] = linkLabel(l.source, l.handle);
    if (l.state === "suggested") {
      const c = chip(label, href, "same name: theirs?");
      c.classList.add("maybe");
      const yes = el("button", null, "✓"), no = el("button", null, "×"); yes.type = no.type = "button";
      yes.title = "Yes, theirs"; no.title = "Not theirs";
      yes.onclick = () => linkAccount(d.room, l.source, l.handle, false);
      no.onclick = () => linkAccount(d.room, l.source, l.handle, true);
      c.append(yes, no); chips.push(c);
    } else chips.push(chip(label, href, l.state === "yours" ? "linked by you" : l.via || "", () => linkAccount(d.room, l.source, l.handle, true)));
  }
  if (d.room) {
    const lk = d.linking || {}, more = el("button", "secondary pf-relink", lk.running ? "Looking across sites…" : "Look again");
    more.type = "button"; more.disabled = !!lk.running;
    more.title = lk.at ? `Last looked ${relTime(lk.at)} ago: their link pages, profiles, and their names elsewhere` : "";
    more.onclick = async () => { more.disabled = true; more.textContent = "Looking across sites…";
      try { await api("api/profile/relink", { room: d.room }); } catch (err) { toast(err.message); } pfLinkWait(pf.gen); };
    chips.push(more);
    if (lk.running) pfLinkWait(pf.gen);
  }
  if (!d.room) {
    for (const a of d.e621 || []) chips.push(chip("e621", `https://e621.net/artists/show_or_new?name=${encodeURIComponent(a)}`));
    for (const h of d.x) chips.push(chip("@" + h, `https://x.com/${h}`));
    for (const h of d.reddit) chips.push(chip("u/" + h, `https://www.reddit.com/user/${h}`));
    for (const u of (d.artist || {}).links || []) {     // an e621 artist's pages elsewhere, as e621 lists them
      let host = ""; try { host = new URL(u).hostname.replace(/^www\./, ""); } catch { continue; }
      if (!/^(x|twitter)\.com$/.test(host)) chips.push(chip(host, u));
    }
  }
  if (!chips.length) chips.push(el("small", "note", "None linked yet."));
  $("pf-links").replaceChildren(...chips);
  $("pf-link-form").hidden = !!pf.key.e621;            // (rooms are linked to X and Reddit accounts)
  // With a room: link its accounts. Without: link this account to a room.
  const src = $("pf-link-src"), was = src.value;
  const SITES = [["x", "X"], ["reddit", "Reddit"], ["redgifs", "RedGifs"], ["xvideos", "xvideos"], ["onlyfans", "OnlyFans"], ["fansly", "Fansly"]];
  src.replaceChildren(...(d.room ? SITES : [["room", "Chaturbate"]]).map(([v, t]) => {
    const o = el("option", null, t); o.value = v; return o;
  }));
  if (d.room && SITES.some(([v]) => v === was)) src.value = was;
  $("pf-link-in").placeholder = d.room ? "their handle there" : "their Chaturbate room";
}
$("pf-link-form").onsubmit = async e => {
  e.preventDefault();
  const d = pf.data, v = $("pf-link-in").value.trim(); if (!d || !v) return;
  if ($("pf-link-src").value === "room") {
    const [source, handle] = pf.key.x ? ["x", pf.key.x] : ["reddit", pf.key.reddit];
    if (await linkAccount(v.toLowerCase(), source, handle, false, true)) { $("pf-link-in").value = ""; openPerson({ room: v.toLowerCase() }); }
  } else if (await linkAccount(d.room, $("pf-link-src").value, v, false)) $("pf-link-in").value = "";
};
async function linkAccount(room, source, handle, remove, quiet) {
  try { await api("api/profile/link", { room, source, handle, remove }); }
  catch (err) { toast(err.message); return false; }
  if (!quiet) loadPerson(pf.gen);
  return true;
}
// Who an X account is: picture, name, bio and counts (from its posts, as X gave them).
function renderXHead(d) {
  const users = d.xusers || {}, h = (pf.key.x || "").toLowerCase(), u = users[h] || Object.values(users)[0];
  const head = $("pf-head");
  if (!u) return renderOtherHead(d);
  const av = el("span", "av lg", u.avatar ? null : (u.handle || "?").slice(0, 1).toUpperCase()), info = el("div");
  if (u.avatar) { const im = el("img"); im.alt = ""; im.src = u.avatar; av.append(im); }
  const n = x => x == null ? null : Number(x).toLocaleString();
  info.append(el("b", null, u.nick || u.handle), el("small", null, "@" + u.handle + (u.location ? " · " + u.location : "")),
    el("small", null, [n(u.followers) && `${n(u.followers)} followers`, n(u.following) && `${n(u.following)} following`,
                       n(u.posts) && `${n(u.posts)} posts`].filter(Boolean).join(" · ")));
  if (u.bio) info.append(el("p", null, u.bio));
  head.replaceChildren(av, info); head.hidden = false;
  if (!d.room) $("pf-title").textContent = u.nick || "@" + u.handle;
}
// Without an X account: a Bluesky account's picture and bio, a Reddit user's picture and karma, or an e621 artist's names and post count.
function renderOtherHead(d) {
  const head = $("pf-head"), r = d.reddituser, a = d.artist, b = d.bskyuser;
  if (b) {
    const av = el("span", "av lg", b.avatar ? null : (b.handle || "?").slice(0, 1).toUpperCase()), info = el("div");
    if (b.avatar) { const im = el("img"); im.alt = ""; im.src = b.avatar; av.append(im); }
    const n = x => x == null ? null : Number(x).toLocaleString();
    info.append(el("b", null, b.nick || "@" + b.handle), el("small", null, ["Bluesky @" + b.handle, b.you_follow ? "you follow them" : ""].filter(Boolean).join(" · ")),
      el("small", null, [n(b.followers) && `${n(b.followers)} followers`, n(b.following) && `${n(b.following)} following`,
                         n(b.posts) && `${n(b.posts)} posts`].filter(Boolean).join(" · ")));
    if (b.bio) info.append(el("p", null, b.bio));
    head.replaceChildren(av, info); head.hidden = false;
    $("pf-title").textContent = b.nick || "@" + b.handle;
    return;
  }
  if (!r && !a) { head.hidden = true; return; }
  const name = r ? "u/" + r.name : a.name.replace(/_/g, " ");
  const av = el("span", "av lg", r && r.avatar ? null : name.replace(/^u\//, "").slice(0, 1).toUpperCase()), info = el("div");
  if (r && r.avatar) { const im = el("img"); im.alt = ""; im.src = r.avatar; av.append(im); }
  info.append(el("b", null, name));
  if (r) info.append(el("small", null, ["Reddit", r.karma != null && `${Number(r.karma).toLocaleString()} karma`,
                                         r.since && `since ${new Date(r.since.replace(" ", "T") + "Z").getFullYear()}`].filter(Boolean).join(" · ")));
  else info.append(el("small", null, ["e621 artist", a.posts != null && `${Number(a.posts).toLocaleString()} posts`].filter(Boolean).join(" · ")),
                   ...(a.other_names.length ? [el("small", null, "also " + a.other_names.slice(0, 4).join(", ").replace(/_/g, " "))] : []));
  head.replaceChildren(av, info); head.hidden = false;
}
// Their latest posts, live from X (their media), Reddit (what they posted) and e621 (what they drew), each a page at a time.
function startPersonPosts(d, gen, who) {
  const feeds = [...(d.e621 || []).map(h => ({ source: "e621", handle: h, cursor: "" })),
                 ...d.x.map(h => ({ source: "x", handle: h, cursor: "" })), ...(d.bsky || []).map(h => ({ source: "bsky", handle: h, cursor: "" })),
                 ...d.reddit.map(h => ({ source: "reddit", handle: h, cursor: "" }))];
  pf.posts = { gen, feeds, who, loading: false };
  $("pf-posts").replaceChildren(); $("pf-more").hidden = true;
  const xv = (d.xvideos || [])[0], rg = (d.redgifs || [])[0];
  pf.xv = xv ? { name: xv, page: 0, gen, loaded: false } : null;
  pf.rg = rg ? { name: rg, page: 1, gen, loaded: false } : null;
  $("pf-xv-grid").replaceChildren(); $("pf-xv-more").hidden = true; $("pf-xv-note").textContent = "";
  $("pf-rg-grid").replaceChildren(); $("pf-rg-more").hidden = true; $("pf-rg-note").textContent = "";
  const tabs = [feeds.length && "posts", rg && "redgifs", xv && "xvideos"].filter(Boolean);
  $("pf-post-sec").hidden = !tabs.length;
  $("pf-tabs").hidden = tabs.length < 2;
  $("pf-tabs").style.gridTemplateColumns = `repeat(${tabs.length}, 1fr)`;
  document.querySelectorAll("#pf-tabs button").forEach(b => { b.hidden = !tabs.includes(b.dataset.t); });
  setPfTab(tabs[0] || "posts");
  const following = new Set(d.following_x || []);
  $("pf-prev-sec").replaceChildren(...d.x.map(h => el("small", "note", `@${h}: ${following.has(h) ? "you follow them on X" : "you don't follow them on X"}`)));
  $("pf-prev-sec").hidden = !d.x.length;
  if (feeds.length) morePersonPosts();
}
// Posts, or their xvideos videos (loaded when that tab is opened), watched in xvideos' own player.
function setPfTab(t) {
  $("pf-posts-tab").hidden = t !== "posts"; $("pf-xv").hidden = t !== "xvideos"; $("pf-rg").hidden = t !== "redgifs";
  document.querySelectorAll("#pf-tabs button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.t === t)));
  if (t === "xvideos" && pf.xv && !pf.xv.loaded) moreXvideos();
  if (t === "redgifs" && pf.rg && !pf.rg.loaded) moreRedgifs();
}
// Their RedGifs clips (the free ones they post themselves), played here from redgifs' servers.
async function moreRedgifs() {
  const st = pf.rg; if (!st || st.loading) return;
  st.loaded = st.loading = true; $("pf-rg-more").hidden = true;
  if (st.page === 1) $("pf-rg-note").textContent = `Reading RedGifs: ${st.name}…`;
  let d;
  try { d = await api(`api/redgifs?name=${encodeURIComponent(st.name)}&page=${st.page}`); }
  catch (err) { if (pf.rg === st) { $("pf-rg-note").textContent = err.message; st.loading = false; } return; }
  if (pf.rg !== st) return;
  st.loading = false; st.page++;
  $("pf-rg-note").textContent = d.total ? `${Number(d.total).toLocaleString()} clips on RedGifs (${st.name})` : `No clips on RedGifs (${st.name}).`;
  $("pf-rg-grid").append(...d.clips.map(c => {
    const b = el("button", "xv-card"), shot = el("span", "shot"); b.type = "button";
    if (c.poster) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = c.poster; shot.append(im); }
    if (c.duration) shot.append(el("span", "len", vidLength(c.duration)));
    b.append(shot, el("small", null, [c.views != null && `${Number(c.views).toLocaleString()} views`, (c.tags || []).slice(0, 3).join(", ")]
      .filter(Boolean).join(" · ")));
    b.onclick = () => openClip(c);
    return b;
  }));
  $("pf-rg-more").hidden = !d.more;
}
$("pf-rg-more").onclick = moreRedgifs;
document.querySelectorAll("#pf-tabs button").forEach(b => b.onclick = () => setPfTab(b.dataset.t));
async function moreXvideos() {
  const st = pf.xv; if (!st || st.loading) return;
  st.loaded = st.loading = true; $("pf-xv-more").hidden = true;
  $("pf-xv-note").textContent = st.page ? "" : `Reading xvideos: ${st.name}…`;
  let d;
  try { d = await api(`api/xvideos?name=${encodeURIComponent(st.name)}&page=${st.page}`); }
  catch (err) { if (pf.xv === st) { $("pf-xv-note").textContent = err.message; st.loading = false; } return; }
  if (pf.xv !== st) return;
  st.loading = false; st.page++;
  $("pf-xv-note").textContent = d.total ? `${Number(d.total).toLocaleString()} videos on xvideos (${st.name})` : `No videos on xvideos (${st.name}).`;
  $("pf-xv-grid").append(...d.videos.map(v => {
    const b = el("button", "xv-card"), shot = el("span", "shot"); b.type = "button";
    if (v.thumb) { const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = v.thumb; shot.append(im); }
    if (v.duration) shot.append(el("span", "len", v.duration));
    b.append(shot, el("b", null, v.title), el("small", null, [v.views && `${v.views} views`, v.when].filter(Boolean).join(" · ")));
    b.onclick = () => openXvideo(v);
    return b;
  }));
  $("pf-xv-more").hidden = !d.more;
}
$("pf-xv-more").onclick = moreXvideos;
function openClip(c) { nav.clips.set(c.id, c); go(`redgifs/${enc(c.id)}`); }
async function showClip(id) {
  let c = nav.clips.get(id);
  $("xv-title").textContent = "RedGifs"; $("xv-open").href = `https://www.redgifs.com/watch/${enc(id)}`;
  xvStop(); $("xv-video").loop = true; $("xv-player").hidden = false;
  if (!c) {
    try { c = (await api(`api/redgifs/clip?id=${enc(id)}`)).clip; } catch (err) { toast(err.message); return leave(); }
    if (here() !== `redgifs/${enc(id)}`) return;
  }
  const v = $("xv-video"); v.poster = c.poster || ""; v.src = c.url; v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
}
// An xvideos video in dreamfeed's own player (its stream, up to 1080p; its MP4 where HLS can't
// play), not xvideos' page with its ads.
const xv = { hls: null, gen: 0 };
function xvStop() {
  xv.gen++; if (xv.hls) { xv.hls.destroy(); xv.hls = null; }
  const v = $("xv-video"); v.pause(); v.removeAttribute("src"); v.removeAttribute("poster"); v.load();
  $("xv-msg").hidden = true;
}
async function showXvideo(it) {
  xvStop(); const gen = xv.gen, v = $("xv-video");
  $("xv-title").textContent = it.title || "xvideos"; v.loop = false;
  $("xv-open").href = `https://www.xvideos.com/video.${encodeURIComponent(it.id)}/`;
  $("xv-player").hidden = false;
  if (it.thumb) v.poster = it.thumb;
  let f;
  try { f = await api(`api/xvideos/video?id=${encodeURIComponent(it.id)}`); }
  catch (err) { if (gen === xv.gen) { $("xv-msg").textContent = err.message; $("xv-msg").hidden = false; } return; }
  if (gen !== xv.gen) return;
  if (f.title) $("xv-title").textContent = f.title;
  if (f.poster) v.poster = f.poster;
  const mp4 = f.mp4 || f.mp4_low, play = () => v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
  if (f.hls && v.canPlayType("application/vnd.apple.mpegurl")) { v.src = f.hls; return play(); }
  if (f.hls) {
    try {
      const Hls = await hlsLib();
      if (gen !== xv.gen) return;
      if (Hls.isSupported()) {
        xv.hls = new Hls({ capLevelToPlayerSize: true }); xv.hls.loadSource(f.hls); xv.hls.attachMedia(v);
        xv.hls.on(Hls.Events.MANIFEST_PARSED, play);
        // (a stream that won't play: its MP4 instead; the stream's player is let go after it's done)
        xv.hls.on(Hls.Events.ERROR, (_, e) => {
          if (!e.fatal || gen !== xv.gen || !xv.hls) return;
          const h = xv.hls; xv.hls = null; setTimeout(() => h.destroy(), 0);
          if (mp4) { v.src = mp4; play(); }
        });
        return;
      }
    } catch {}
  }
  if (mp4) { v.src = mp4; play(); }
}
function closeXvideo() { xvStop(); $("xv-player").hidden = true; }
$("xv-close").onclick = leave;
async function morePersonPosts() {
  const st = pf.posts; if (!st || st.loading) return;
  const gen = st.gen, todo = st.feeds.filter(f => f.cursor !== null);
  if (!todo.length) return;
  st.loading = true; $("pf-more").hidden = true;
  const wait = el("p", "note", "Reading their latest posts…"); $("pf-posts").append(wait);
  const pages = await Promise.all(todo.map(async f => {
    try {
      const r = await api(`api/person/posts?source=${f.source}&handle=${encodeURIComponent(f.handle)}&cursor=${encodeURIComponent(f.cursor)}`);
      f.cursor = r.cursor; return r.posts;
    } catch (err) { f.cursor = null; return [el("p", "note", `${{ x: "@", bsky: "Bluesky @", reddit: "u/", e621: "e621 " }[f.source]}${f.handle}: ${err.message}`)]; }
  }));
  if (gen !== pf.gen || pf.posts !== st) return;
  wait.remove();
  const items = pages.flat().sort((a, b) => (b.posted_at || "").localeCompare(a.posted_at || ""));
  $("pf-posts").append(...items.map(x => x instanceof Node ? x : postCard(x)));
  if (!$("pf-posts").children.length) $("pf-posts").append(el("p", "note", "No pictures or videos lately."));
  st.loading = false; $("pf-more").hidden = !st.feeds.some(f => f.cursor !== null);
  if (st.feeds.some(f => f.source === "x") && pf.data) {   // X said who they are with their posts: the header, filled in
    const k = pf.key, q = k.room ? `room=${encodeURIComponent(k.room)}` : k.x ? `x=${encodeURIComponent(k.x)}`
      : k.e621 ? `e621=${encodeURIComponent(k.e621)}` : "";
    try { if (q) { const d = await api(`api/profile?${q}`); if (gen === pf.gen && pf.data) { pf.data.xusers = d.xusers; renderXHead(pf.data); } } } catch {}
  }
}
$("pf-more").onclick = morePersonPosts;
function renderProfile(gen) {
  clearTimeout(pf.timer);
  $("pf-vid-sec").hidden = !pf.videos.length;
  $("pf-vcount").textContent = `Your videos (${pf.videos.length})`;
  $("pf-grid").replaceChildren(...pf.videos.map((f, i) => {
    const item = el("div", "pf-item"), b = el("button", "pf-vid"), shot = el("span", "shot"); b.type = "button";
    if (f.poster) { const img = el("img"); img.alt = ""; img.loading = "lazy"; img.src = f.poster; shot.append(img); }
    else shot.append(el("span", "ph"));
    if (f.highlight) shot.append(el("span", "hl", "HIGHLIGHTS"));
    if (f.duration) shot.append(el("span", "len", vidLength(f.duration)));
    const about = f.highlight && f.duration && f.of ? `${vidLength(f.duration)} of ${vidLength(f.of)}` : vidDate(f);
    b.append(shot, el("b", null, f.title), el("small", null, `${about} · ${vidSize(f.size)}`));
    b.onclick = () => go(`room/${enc(pf.room.name)}/video/${enc(pf.videos[i].path)}`);
    item.append(b, videoActions(f));
    return item;
  }));
  const working = pf.videos.some(f => f.job && ["queued", "running"].includes(f.job.status));
  if (working) pf.timer = setTimeout(() => reloadProfile(gen), 5000);
}
async function reloadProfile(gen) {
  if (gen !== pf.gen || $("pf-view").hidden) return;
  try { const d = await api(`api/live/videos?name=${encodeURIComponent(pf.room.name)}`); if (gen !== pf.gen) return; pf.videos = d.videos; }
  catch { /* next time */ }
  renderProfile(gen);
}
// Under each video: Highlights (cut it down to the action: how much to keep) and Delete.
const KEEP = [["Short", 0.1], ["Medium", 0.25], ["Long", 0.5]];
const HL_PHASE = { motion: "looking for motion", sound: "listening", cutting: "cutting" };
function videoActions(f) {
  const acts = el("div", "pf-acts"), job = f.job || {};
  const btn = (label, fn) => { const b = el("button", "secondary", label); b.type = "button"; b.onclick = fn; return b; };
  const del = btn("Delete", () => deleteVideo(f));
  if (f.highlight) { acts.append(del); return acts; }
  if (job.status === "queued") acts.append(el("small", null, "Highlights: waiting their turn…"));
  else if (job.status === "running") acts.append(el("small", null, `Highlights: ${HL_PHASE[job.phase] || "starting"}${job.pct != null ? ` ${job.pct}%` : ""}…`));
  else {
    if (job.status === "failed") acts.append(el("small", "err", `Highlights failed: ${job.error || "?"}`));
    const hl = btn(f.has_highlight ? "Redo highlights" : "Highlights", () => {
      acts.replaceChildren(el("small", null, "Keep about:"),
        ...KEEP.map(([label, keep]) => btn(`${label} (${Math.round(keep * 100)}%)`, () => requestHighlights(f, keep))),
        btn("Cancel", () => acts.replaceWith(videoActions(f))));
    });
    acts.append(hl);
  }
  acts.append(del);
  return acts;
}
async function requestHighlights(f, keep) {
  try { await api("api/live/highlights", { name: pf.room.name, path: f.path, keep }); }
  catch (err) { toast(err.message); }
  reloadProfile(pf.gen);
}
async function deleteVideo(f) {
  if (!confirm(`Delete "${f.title}"${f.highlight ? " (highlights)" : ""}? It stays in the trash for a week.`)) return;
  let d;
  try { d = await api("api/live/delete", { name: pf.room.name, path: f.path }); } catch (err) { return toast(err.message); }
  pf.videos = pf.videos.filter(v => v !== f); renderProfile(pf.gen); refreshFollowing();
  toast("Deleted.", "Undo", async () => {
    try { await api("api/live/restore", { undo: d.undo }); } catch (err) { return toast(err.message); }
    reloadProfile(pf.gen); refreshFollowing();
  });
}
function closeProfile() { pf.gen++; clearTimeout(pf.timer); clearTimeout(pf.ptimer); clearTimeout(pf.ftimer); $("pf-view").hidden = true; }
$("pf-close").onclick = leave;
$("pf-live").onclick = () => openRoom(pf.card && pf.card.name === pf.room.name ? pf.card : { ...pf.room, info: (pf.data || {}).info || {} }, null);
function closeRoom() { pl.gen++; clearTimeout(pl.timer); stopVideo(); $("player").hidden = true; }
$("pl-close").onclick = leave;
document.addEventListener("keydown", e => {
  if ($("player").hidden) {
    if (!$("vfeed").hidden) {
      if (e.key === "Escape") leave();
      else if (["ArrowDown", "j", "PageDown"].includes(e.key)) { e.preventDefault(); vfStep(1); }
      else if (["ArrowUp", "k", "PageUp"].includes(e.key)) { e.preventDefault(); vfStep(-1); }
      else if (e.key === "m") vfSound(vf.muted);
      return;
    }
    if (e.key === "Escape") {
      if (!$("pic-view").hidden) closePicture(); else if (!$("mv-picker").hidden) $("mv-picker").hidden = true;
      else if (["xv-player", "multi", "post-view", "browse", "profile"].some(id => !$(id).hidden)) leave();
    }
    return;
  }
  if (e.key === "Escape") leave();
  else if (e.key === "ArrowRight") $("pl-next").click();
  else if (e.key === "ArrowLeft") $("pl-prev").click();
});

