// Every kind of address opens its page, with no error at start (a startup error silently stops
// everything after it), and Back goes back.
const { load, run, assert } = require("./harness");

const POST = { post: { id: "x:1234567", source: "x", author: "someone", text: "t", media: [], posted_at: "2026-01-01 00:00:00" } };
const answer = u => u.includes("api/post?") ? POST
  : u.includes("api/comics") ? { comics: [{ id: 7, title: "C", pages: 1, cast: ["a", "b"], panels: [], animations: [], story: "", imported: false }], making: [], failed: [] }
  : u.includes("api/profile") ? { room: u.includes("room=") ? "someroom" : null, followed: true, x: [], reddit: [], links: [], xusers: {}, xvideos: [],
                                  e621: [], redgifs: [], bsky: [], bio: {}, dvr: {} }
  : u.includes("api/reddit/browse") ? { posts: [], after: null, sub: "pics", sort: "hot" } : undefined;

const PAGES = [   // address -> the view it shows
  ["/dreamfeed/", "posts"], ["/dreamfeed/feed", "posts"], ["/dreamfeed/feed/foryou", "posts"], ["/dreamfeed/saved", "liked"],
  ["/dreamfeed/saved/x", "liked"], ["/dreamfeed/vids", "vids"], ["/dreamfeed/live", "follow"], ["/dreamfeed/live/discover", "follow"],
  ["/dreamfeed/comics", "comics"], ["/dreamfeed/dashboard", "dash"], ["/dreamfeed/personas", "feed"],
  ["/dreamfeed/room/someroom", null], ["/dreamfeed/room/someroom/watch", null], ["/dreamfeed/watch/a+b", null],
  ["/dreamfeed/r/pics/top", null], ["/dreamfeed/post/x/1234567", null], ["/dreamfeed/x/someone", null], ["/dreamfeed/u/someone", null],
  ["/dreamfeed/e621/someartist", null], ["/dreamfeed/bsky/someone.bsky.social", null], ["/dreamfeed/xvideos/abc123456", null],
  ["/dreamfeed/comics/7", "comics"], ["/dreamfeed/nonsense", "posts"],
];

run("every address opens, without errors", async () => {
  for (const [path, view] of PAGES) {
    const p = await load(path, answer);
    assert.deepStrictEqual(p.errs, [], `${path} threw:\n${p.errs.join("\n")}`);
    if (view) assert.strictEqual(p.w.eval("state.view"), view, `${path} should show ${view}`);
    p.w.close();
  }
  // opened from the Feed: a room's profile, then Back
  const p = await load("/dreamfeed/feed", answer);
  p.w.eval(`openRoomProfile({ name: "someroom", info: {} })`); await p.sleep(200);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/room/someroom");
  assert.ok(p.shown("pf-view"), "the room profile window should be open");
  p.w.eval("history.back()"); await p.sleep(300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/feed");
  assert.ok(!p.shown("pf-view"), "Back should close it");
  p.noErrors();
});
