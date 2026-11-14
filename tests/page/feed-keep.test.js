// The Feed: a page of posts drawn a few at a time (More draws the rest before reading the next
// page), and kept as you left it when you switch tabs and come back (not read again).
const { load, run, assert } = require("./harness");

const post = n => ({ id: `reddit:p${n}`, source: "reddit", author: "someone", place: "pics", text: `post ${n}`,
  media: [], posted_at: "2026-11-01 00:00:00", link: `https://www.reddit.com/r/pics/p${n}` });

run("Feed: drawn a few at a time, kept across tabs", async () => {
  const p = await load("/dreamfeed/feed", u => u.includes("api/following/posts")
    ? (u.includes("cursor=c2") ? { posts: [post(99)], more: false, cursor: null, errors: {} }
      : { posts: Array.from({ length: 30 }, (_, i) => post(i)), more: true, cursor: "c2", errors: {} }) : undefined);
  const cards = () => p.d.querySelectorAll("#f-posts article.post").length;
  const reads = () => p.calls.filter(c => c.u.includes("api/following/posts")).length;
  assert.strictEqual(cards(), 12, "the first few drawn");
  assert.ok(p.shown("f-more"));
  await p.click(p.$("f-more"), 100); assert.strictEqual(cards(), 24);
  await p.click(p.$("f-more"), 100); assert.strictEqual(cards(), 30);
  assert.strictEqual(reads(), 1, "the rest of the page drawn before the next is read");
  await p.click(p.$("f-more"), 200);
  assert.strictEqual(reads(), 2); assert.ok(p.lastCall("api/following/posts").u.includes("cursor=c2")); assert.strictEqual(cards(), 31);
  assert.ok(!p.shown("f-more"));
  // another tab and back: as it was, not read again
  p.w.eval(`go("vids")`); await p.sleep(200);
  p.w.eval(`go("feed")`); await p.sleep(200);
  assert.strictEqual(cards(), 31); assert.strictEqual(reads(), 2);
  // a different Feed (For you): read
  await p.click('#f-mode button[data-m="foryou"]', 200);
  assert.strictEqual(reads(), 3); assert.ok(p.lastCall("api/following/posts").u.includes("mode=foryou"));
  // and after a while away, read again
  p.w.eval(`go("vids")`); await p.sleep(100);
  p.w.eval("fp.at -= FEED_KEEP + 1"); p.w.eval(`go("feed/foryou")`); await p.sleep(200);
  assert.strictEqual(reads(), 4);
  p.noErrors(); p.w.close();

  // what's new since: offered at the top (the page shown may be one read a while ago)
  let later = false;
  const q = await load("/dreamfeed/feed", u => u.includes("api/following/posts")
    ? { posts: (later ? [post(100), post(101)] : []).concat([post(1), post(2)]), more: false, cursor: null, errors: {} } : undefined);
  q.w.eval("checkNew(fp.gen)"); await q.sleep(100);
  assert.ok(!q.d.querySelector(".new-posts"), "nothing new: nothing offered");
  later = true; q.w.eval("checkNew(fp.gen)"); await q.sleep(100);
  assert.strictEqual(q.d.querySelector(".new-posts").textContent, "↑ 2 new posts");
  await q.click(q.d.querySelector(".new-posts"), 200);
  assert.ok(!q.d.querySelector(".new-posts")); assert.strictEqual(q.d.querySelectorAll("#f-posts article.post").length, 4);
  q.noErrors();
});
