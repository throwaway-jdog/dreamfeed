// Comics: Updated (followed, with new pages), Continue reading, For you (each says why), Your
// comics; reading a live one (its pages from the site, Follow, where you are told), search.
const { load, run, assert } = require("./harness");

const live = (n, extra) => ({ id: `e621:${n}`, source: "e621", title: "Comic " + n, pages: 10, cover: "https://static1.e621.net/data/sample/a.jpg",
  tags: ["wolf"], link: `https://e621.net/pools/${n}`, ...extra });
const read = { ...live(1), images: Array.from({ length: 10 }, (_, i) => ({ url: `https://static1.e621.net/data/sample/p${i + 1}.jpg`, full: `https://static1.e621.net/data/p${i + 1}.jpg` })),
  page: 3, followed: false, new_from: null };

run("Comics", async () => {
  const p = await load("/dreamfeed/comics", (u, b) => {
    if (u.includes("api/comics/feed")) return { comics: [live(1, { why: "Because you read wolf" }), live(2, { why: "Just updated on e621" })], more: true,
      updated: [{ ...live(5), new: 3 }], continue: [{ ...live(6), page: 4 }], following: [], library: [{ id: 12, title: "Kept one", pages: 25, imported: true }],
      taste: { tags: ["wolf"], n: 3 } };
    if (u.includes("api/comics/read")) return read;
    if (u.includes("api/comics/follow")) return { followed: b.follow };
    if (u.includes("api/comics/progress")) return { ok: true };
    if (u.includes("api/comics/search")) return { results: [{ id: "mp:some_comic", source: "multporn", title: "Found", thumb: "comic-search/thumb?u=x" }], more: false };
  });
  assert.strictEqual(p.w.eval("state.view"), "comics");
  assert.match(p.text("cu-row"), /Comic 5.*3 new pages/);
  assert.match(p.text("cc-row"), /page 4 of 10/);
  assert.deepStrictEqual([...p.d.querySelectorAll("#cg .why")].map(x => x.textContent), ["Because you read wolf", "Just updated on e621"]);
  assert.match(p.text("c-list"), /Kept one/);
  assert.ok(!p.$("cg-more").hidden);
  // read one: from where you left off, its pages straight from the site
  await p.click("#cg .comic-card", 400);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/e621/1");
  assert.ok(p.shown("reader"));
  assert.strictEqual(p.text("rd-count"), "3 / 10");
  assert.strictEqual(p.d.querySelectorAll("#rd-track img").length, 10);
  assert.strictEqual(p.d.querySelector("#rd-track img").getAttribute("src"), "e621-media/data/sample/p1.jpg", "e621 pages come through dreamfeed");
  await p.click(p.$("reader-follow"), 150);
  assert.deepStrictEqual(p.lastSent("api/comics/follow").body, { id: "e621:1", follow: true });
  assert.strictEqual(p.text("reader-follow"), "Following ✓");
  await p.click(p.$("rd-next"), 1700);
  assert.deepStrictEqual(p.lastSent("api/comics/progress").body, { id: "e621:1", page: 4 });
  p.w.eval("history.back()"); await p.sleep(300);
  assert.ok(!p.shown("reader"));
  // search
  p.$("cs-q").value = "found"; p.$("cs-form").dispatchEvent(new p.w.Event("submit")); await p.sleep(200);
  assert.match(p.lastCall("api/comics/search").u, /q=found&page=0&site=multporn/);
  assert.match(p.text("cg"), /Found/);
  p.noErrors();
});
