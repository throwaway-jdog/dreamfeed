// Updates, History, Search and Mute: what each shows, and what a tap sends.
const { load, run, assert } = require("./harness");

const now = Date.now() / 1000;
const NOTICES = { more: false, counts: { live: 1, comics: 1 }, topics: ["live", "recordings", "comics", "health"], notices: [
  { id: 3, topic: "live", title: "someroom is live", body: "hi · 40 watching", link: "room/someroom/watch", thumb: null, at: now - 60, read: false, live_now: true },
  { id: 2, topic: "comics", title: "A comic: 3 new pages", body: "20 pages now", link: "comics/e621/123", thumb: null, at: now - 120, read: false },
  { id: 1, topic: "recordings", title: "Highlights of someroom: 12 min of 1 h 30 min", body: "x", link: "room/someroom", thumb: null, at: now - 3 * 86400, read: true }] };
const POST = { id: "reddit:abc", source: "reddit", author: "someone", place: "pics", text: "a post", media: [{ kind: "image", url: "https://i.redd.it/a.jpg" }],
               posted_at: "2026-11-01 00:00:00", link: "https://www.reddit.com/r/pics/abc" };
const HISTORY = { more: false, kinds: [], items: [
  { kind: "post", key: POST.id, title: "a post", thumb: null, link: "post/reddit/abc", data: POST, at: now - 30 },
  { kind: "room", key: "someroom", title: "someroom", thumb: null, link: "room/someroom/watch", data: null, at: now - 90 }] };

run("Updates, History, Search, Mute", async () => {
  // Updates: by day, unread marked, and opening the page marks them read; a tap opens its address
  let p = await load("/dreamfeed/updates", u => u.includes("api/notices?") ? NOTICES : u.includes("api/summary") ? { live: 0, notices: 2 } : undefined);
  assert.ok(p.shown("updates"));
  const days = [...p.d.querySelectorAll("#up-list .lday")].map(h => h.textContent);
  assert.strictEqual(days[0], "Today"); assert.strictEqual(days.length, 2);
  assert.strictEqual(p.d.querySelectorAll("#up-list .lrow.unread").length, 2);
  assert.ok(p.text("up-list").includes("● live now"));
  assert.ok(p.lastSent("api/notices/read"), "opening Updates marks them read");
  assert.strictEqual(p.text("upd-n"), "2");
  assert.ok(p.d.querySelector('#up-topic [data-t="live"]').textContent.includes("1"), "each topic says how many are unread");
  await p.click(p.d.querySelector("#up-list .lrow-open"), 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/room/someroom/watch");
  p.noErrors(); p.w.close();

  // a topic, then ✕ one
  p = await load("/dreamfeed/updates", u => u.includes("api/notices?") ? NOTICES : undefined);
  await p.click('#up-topic [data-t="comics"]', 200);
  assert.ok(p.lastCall("api/notices?").u.includes("topic=comics"));
  await p.click(p.d.querySelector("#up-list .lrow-x"), 200);
  p.same(p.lastSent("api/notices/clear").body, { id: 3 });
  p.noErrors(); p.w.close();

  // History: by day; a post opens its page; Clear history asks the server to clear it
  p = await load("/dreamfeed/history", u => u.includes("api/history?") ? HISTORY : undefined);
  assert.strictEqual(p.d.querySelectorAll("#hi-list .lrow").length, 2);
  await p.click(p.d.querySelector("#hi-list .lrow-open"), 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/post/reddit/abc");
  assert.ok(p.shown("post-view"));
  assert.strictEqual(p.lastSent("api/history").body.kind, "post", "opening a post notes it");
  p.w.history.back(); await p.sleep(300);
  await p.click(p.$("hi-clear"), 200);
  p.same(p.lastSent("api/history/remove").body, { all: true, kind: "" });
  p.noErrors(); p.w.close();

  // Search: every part asked at once; posts shown, with their 🔇
  p = await load("/dreamfeed/search/wolf%20solo", u =>
    u.includes("api/search?in=posts") ? { posts: [POST], cursor: null, errors: { x: "X isn't signed in" } }
    : u.includes("api/search?in=subreddits") ? { subreddits: [{ name: "wolves", title: "Wolves", subscribers: 1200, icon: null, nsfw: true }] }
    : u.includes("api/search?in=yours") ? { saved: [], rooms: [{ name: "wolfroom", live: true, info: {} }], comics: [], history: [] }
    : u.includes("api/vids/search") ? { videos: [{ id: "abcd12345", url: "/video.abcd12345/x", title: "A wolf video", duration: 600 }], more: false }
    : undefined, { wait: 900 });
  assert.strictEqual(p.$("se-q").value, "wolf solo");
  for (const part of ["in=yours", "in=subreddits", "in=posts", "api/vids/search", "api/discover/cb?mode=search", "site=multporn", "site=e621"])
    assert.ok(p.calls.some(c => c.u.includes(part) && c.u.includes("wolf%20solo")), `asks ${part}`);
  assert.ok(p.shown("se-posts-sec") && p.d.querySelectorAll("#se-posts .post").length === 1);
  assert.ok(p.text("se-posts-note").includes("X: X isn't signed in"));
  assert.ok(p.shown("se-subs-sec") && p.text("se-subs").includes("r/wolves"));
  assert.ok(p.shown("se-yours-sec") && p.text("se-yours").includes("wolfroom"));
  assert.ok(p.shown("se-vids-sec"));
  await p.click('#se-source [data-s="reddit"]', 300);
  assert.ok(p.lastCall("api/search?in=posts").u.includes("source=reddit"));
  // a post's 🔇: mute its author or its subreddit
  await p.click("#se-posts .mute-btn", 100);
  const picks = [...p.d.querySelectorAll(".mute-pick button")].map(b => b.textContent);
  p.same(picks, ["Mute u/someone", "Mute r/pics", "Cancel"]);
  await p.click(p.d.querySelectorAll(".mute-pick button")[1], 300);
  p.same(p.lastSent("api/mutes").body, { kind: "subreddit", value: "pics" });
  assert.strictEqual(p.d.querySelectorAll("#se-posts .post").length, 0, "the muted post goes");
  // a new search from the box: its own address
  p.$("se-q").value = "fox"; p.$("se-form").dispatchEvent(new p.w.Event("submit", { cancelable: true })); await p.sleep(300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/search/fox");
  p.noErrors(); p.w.close();

  // Mute on the Dashboard: the list, add one, unmute one
  p = await load("/dreamfeed/dashboard", (u, body) => u.includes("api/mutes") ? { mutes: [{ kind: "word", value: "feet", site: "", at: 1 },
    { kind: "account", value: "someone", site: "x", at: 2 }], kinds: [], sites: [] } : undefined);
  assert.ok(p.text("mu-list").includes("feet") && p.text("mu-list").includes("account on X"));
  p.$("mu-kind").value = "account"; p.$("mu-kind").dispatchEvent(new p.w.Event("change"));
  assert.ok(p.shown("mu-site"), "an account asks which site");
  p.$("mu-site").value = "e621"; p.$("mu-value").value = "someartist";
  p.$("mu-form").dispatchEvent(new p.w.Event("submit", { cancelable: true })); await p.sleep(200);
  p.same(p.lastSent("api/mutes").body, { kind: "account", value: "someartist", site: "e621" });
  await p.click(p.d.querySelector("#mu-list .secondary"), 200);
  p.same(p.lastSent("api/mutes").body, { kind: "word", value: "feet", site: "", remove: true });
  p.noErrors(); p.w.close();

  // a room's After a recording: highlights, then the original deleted (asked first)
  p = await load("/dreamfeed/room/someroom", u => u.includes("api/profile") ? { room: "someroom", followed: true, x: [], reddit: [], links: [], xusers: {},
    xvideos: [], e621: [], redgifs: [], bsky: [], bio: {}, dvr: { on: false }, auto: { mode: "off", keep: 0.25, since: null, folder: true } }
    : u.includes("api/live/auto") ? { mode: "delete", keep: 0.25, since: now } : undefined, { wait: 900 });
  assert.ok(p.shown("pf-auto-sec"));
  assert.ok(!p.shown("pf-auto-keep"), "off: no amount to keep");
  p.$("pf-auto-mode").value = "delete"; p.$("pf-auto-mode").dispatchEvent(new p.w.Event("change")); await p.sleep(200);
  p.same(p.lastSent("api/live/auto").body, { name: "someroom", mode: "delete", keep: 0.25 });
  assert.ok(p.shown("pf-auto-keep") && p.text("pf-auto-note").includes("trash"));
  p.noErrors();
});
