// The Videos tab: For you and Continue watching, search with a length (remembered), the player
// (dreamfeed's own: its stats, comments, 👍 sent with the video's page, how far you are, Up next),
// and Saved's new places (the Feed page, the menu).
const { load, run, assert } = require("./harness");

const vid = n => ({ id: "abc12345" + n, url: `/video.abc12345${n}/t${n}`, title: "Video " + n, duration: 900 + n,
  thumb: "https://thumb-cdn77.xvideos-cdn.com/x.jpg", uploader: "Up" + n, why: "You like cosplay" });

run("Videos", async () => {
  const p = await load("/dreamfeed/vids", (u, b) => {
    if (u.includes("api/vids/search")) return { videos: [vid(9)], more: false };
    if (u.includes("api/vids/video")) return { id: "abc123451", title: "Video 1", hls: null, mp4: "https://mp4-cdn77.xvideos-cdn.com/a.mp4", poster: null,
      related: [vid(7)], resume: 120, vote: 0, views: 444138, likes: 797, dislikes: 202, comments: 4 };
    if (u.includes("api/vids/comments")) return { comments: [{ id: "1", author: "Someone", at: "4 months ago", text: "hi", up: 2, down: 1 }] };
    if (u.includes("api/vids/vote")) return { vote: b.vote, site: { status: "done" } };
    if (u.includes("api/vids/watch")) return { ok: true };
    if (u.includes("api/vids")) return { videos: [vid(1), vid(2)], more: true, continue: [{ ...vid(3), resume: 300 }], taste: { tags: ["cosplay"], n: 2 } };
  });
  assert.strictEqual(p.d.querySelector('[data-view="vids"]').getAttribute("aria-pressed"), "true");
  assert.ok(!p.d.querySelector('[data-view="liked"]'), "Saved isn't a tab any more");
  assert.strictEqual(p.d.querySelectorAll("#vc-row .pf-vid").length, 1);
  assert.strictEqual(p.d.querySelectorAll("#vg .pf-vid").length, 2);
  assert.match(p.text("vg-note"), /cosplay/);
  // search, 20+ minutes
  p.$("vs-len").value = "20"; p.$("vs-len").dispatchEvent(new p.w.Event("change")); await p.sleep(150);
  p.$("vs-q").value = "cosplay"; p.$("vs-form").dispatchEvent(new p.w.Event("submit")); await p.sleep(150);
  assert.match(p.lastCall("api/vids/search").u, /q=cosplay&page=0&length=20/);
  assert.strictEqual(p.w.localStorage.getItem("vidsLength"), "20");
  await p.click(p.$("vg-back"), 200);
  // the player
  await p.click("#vg .pf-vid", 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/xvideos/abc123451");
  assert.strictEqual(p.$("xv-video").getAttribute("src"), "https://mp4-cdn77.xvideos-cdn.com/a.mp4");
  assert.match(p.text("xv-stats"), /444,138 views · 👍 797 · 👎 202.*80%/);
  await p.click(p.$("xv-com-btn"), 150);
  assert.match(p.text("xv-com-list"), /Someone · 4 months ago · 👍 2 👎 1hiThe other 3 on xvideos/);
  await p.click(p.$("xv-up"), 120);
  assert.deepStrictEqual(p.lastCall("api/vids/vote").body, { id: "abc123451", vote: 1, url: "/video.abc123451/t1" });
  assert.match(p.text("toast"), /voted on xvideos/);
  const v = p.$("xv-video");
  Object.defineProperty(v, "duration", { value: 1000, configurable: true }); Object.defineProperty(v, "paused", { value: false, configurable: true });
  for (const t of [0, 1, 2, 3]) { v.currentTime = t; v.dispatchEvent(new p.w.Event("timeupdate")); }
  v.dispatchEvent(new p.w.Event("ended")); await p.sleep(100);
  assert.deepStrictEqual(p.lastCall("api/vids/watch").body, { id: "abc123451", position: 3, duration: 1000, delta: 3 });
  assert.ok(p.shown("xv-next"), "Up next when it ends");
  await p.click(p.$("xv-next-go"), 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/xvideos/abc123457");
  // Saved: on the Feed page and in the menu
  await p.click(p.$("f-saved"), 200); assert.strictEqual(p.w.location.pathname, "/dreamfeed/saved");
  p.noErrors();
});
