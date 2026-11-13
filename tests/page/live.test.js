// Live: a live card's Profile opens the room's profile (its window, not the persona Feed's header:
// they once shared an id), linking an account by hand, recording (this stream / all streams),
// and adding a room from Discover in multi view.
const { load, run, assert } = require("./harness");

const room = (name, live = true) => ({ name, source: "chaturbate", live, followed: true, thumb: "", info: { viewers: 5, title: "hi " + name }, times: [], videos: 0 });
let rec = null;
const profile = () => ({ room: "someroom", followed: true, live: true, x: [], reddit: [], xusers: {}, xvideos: [], e621: [], redgifs: [], bsky: [],
  bio: { followers: 10 }, links: [{ source: "onlyfans", handle: "someroom", state: "bio", via: "their Chaturbate bio" }],
  dvr: { on: true, room: rec, free: "1 TiB" }, linking: { running: false, at: "2026-01-01 00:00:00" } });

run("Live: profile, link an account, record, multi view", async () => {
  const p = await load("/dreamfeed/live", (u, b) => {
    if (u.includes("api/following")) return { rooms: [room("someroom"), room("other")], status: {}, dvr: { on: true } };
    if (u.includes("api/profile/link")) return { ok: true };
    if (u.includes("api/profile")) return profile();
    if (u.includes("api/dvr")) { rec = b.action === "once" ? { state: "waiting", running: true, once: true } : b.action === "record" ? { state: "waiting", running: true, once: false } : null; return { dvr: rec }; }
    if (u.includes("api/discover/cb")) return { rooms: u.includes("q=goth") ? [room("goth1")] : [room("d1"), room("d2")], more: true };
    if (u.includes("api/live/stream")) return { status: "offline", hls: null };
  });
  // a live card's Profile
  const prof = [...p.d.querySelectorAll(".live-item .acts button")].find(b => b.textContent.startsWith("Profile"));
  assert.ok(prof, "a live card should have Profile"); await p.click(prof, 400);
  assert.ok(p.shown("pf-view"), "Profile should open the room profile window");
  assert.ok(p.$("profile").hidden, "the persona Feed's header stays hidden");
  assert.match(p.text("pf-links"), /OnlyFans: someroom/);
  // link one by hand
  p.$("pf-link-src").value = "xvideos"; p.$("pf-link-in").value = "someroom_xv";
  p.$("pf-link-form").dispatchEvent(new p.w.Event("submit")); await p.sleep(200);
  assert.deepStrictEqual(p.lastCall("api/profile/link").body, { room: "someroom", source: "xvideos", handle: "someroom_xv", remove: false });
  // recording: this stream, then all
  const btn = t => [...p.d.querySelectorAll("#pf-dvr button")].find(b => b.textContent === t);
  assert.ok(btn("Record this stream") && btn("Record all streams"), "not recorded: both choices");
  await p.click(btn("Record this stream"), 300);
  assert.strictEqual(p.lastCall("api/dvr").body.action, "once");
  assert.match(p.text("pf-dvr"), /this stream only/);
  await p.click(btn("Record all streams"), 300);
  assert.strictEqual(p.lastCall("api/dvr").body.action, "record");
  assert.ok(btn("Only this stream"), "recording all: offers this stream only");
  p.w.eval("history.back()"); await p.sleep(300);
  // multi view: + Add from Discover, and a search there
  p.w.eval(`follow.live = [{ name: "someroom", info: {} }]; openMulti([{ name: "someroom", info: {} }])`); await p.sleep(200);
  await p.click(p.$("mv-add"), 300);
  assert.strictEqual(p.w.eval("mvp.tab"), "discover", "with none of yours left live, it opens on Discover");
  assert.deepStrictEqual([...p.d.querySelectorAll("#mv-list b")].map(b => b.textContent), ["d1", "d2"]);
  p.$("mv-q").value = "goth"; p.$("mv-search").dispatchEvent(new p.w.Event("submit")); await p.sleep(200);
  await p.click("#mv-list button", 200);
  p.same(p.w.eval("mv.tiles.map(t => t.r.name)"), ["someroom", "goth1"]);
  p.noErrors();
});
