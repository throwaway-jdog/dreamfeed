// Comics: multporn's New and Updated comics (rows, and See all), Browse by tag (chips, typed,
// e621's), a tag's comics in an order, and a search that names a tag.
const { load, run, assert } = require("./harness");

const mp = (slug, extra) => ({ id: `mp:${slug}`, source: "multporn", title: slug.replace(/_/g, " "), pages: null, cover: null,
  thumb: "comic-search/thumb?u=x", tags: [], link: `https://multporn.net/comics/${slug}`, ...extra });
const TAGS = { tags: [{ tag: "anal", name: "Anal" }, { tag: "big_tits", name: "Big Tits" }, { tag: "furry", name: "Furry" }] };
const FEED = { comics: [], more: false, updated: [], continue: [], following: [], library: [], taste: { tags: ["furry"], n: 2 } };
const answer = u =>
  u.includes("api/comics/feed") ? FEED
  : u.includes("api/comics/tags") ? TAGS
  : u.includes("list=new") ? { results: [mp("fresh_one", { posted: new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 19).replace("T", " ") })], more: true }
  : u.includes("list=updated") ? { results: [mp("grown_one"), mp("grown_two")], more: true }
  : u.includes("list=tag") ? { results: [mp("tagged_one")], more: true, tag: { tag: "anal", name: "Anal", site: "multporn" } }
  : u.includes("api/comics/search") ? { results: [mp("found_one")], more: false, tags: [{ tag: "furry", name: "Furry" }] }
  : undefined;

run("Comics: New, Updated, tags", async () => {
  let p = await load("/dreamfeed/comics", answer, { wait: 600 });
  assert.ok(p.shown("cn-sec") && p.text("cn-row").includes("fresh one") && p.text("cn-row").includes("2 d ago"), "New on multporn, with when");
  assert.ok(p.shown("cw-sec") && p.d.querySelectorAll("#cw-row .comic-card").length === 2, "Updated on multporn");
  const chips = [...p.d.querySelectorAll("#ct-chips .chip")].map(c => c.textContent);
  assert.deepStrictEqual(chips, ["Furry", "Anal", "Big Tits"], "your tags first, then A to Z");
  // See all: the whole list, page by page
  await p.click(p.$("cw-all"), 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/updated");
  assert.strictEqual(p.text("cg-title"), "Updated on multporn");
  assert.ok(!p.shown("ct-sec") && !p.shown("cn-sec") && p.shown("cg-back") && !p.shown("cg-bar"));
  assert.match(p.lastCall("list=updated").u, /page=0/);
  await p.click(p.$("cg-more"), 200);
  assert.match(p.lastCall("list=updated").u, /page=1/);
  await p.click(p.$("cg-back"), 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics");
  assert.ok(p.shown("ct-sec") && p.text("cg-title") === "For you");
  // a tag chip: that tag's comics, in an order
  await p.click([...p.d.querySelectorAll("#ct-chips .chip")].find(c => c.textContent === "Anal"), 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/tag/anal");
  assert.strictEqual(p.text("cg-title"), "Anal");
  assert.ok(p.shown("cg-bar"));
  assert.match(p.lastCall("list=tag").u, /tag=anal&sort=new&site=multporn&page=0/);
  p.$("cg-sort").value = "popular"; p.$("cg-sort").dispatchEvent(new p.w.Event("change")); await p.sleep(200);
  assert.match(p.lastCall("list=tag").u, /sort=popular/);
  // open one and come back: the list stays as it was (no new request)
  const n = p.calls.filter(c => c.u.includes("list=tag")).length;
  await p.click("#cg .comic-card", 100);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/mp/tagged_one");
  p.w.eval("history.back()"); await p.sleep(300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/tag/anal");
  assert.strictEqual(p.calls.filter(c => c.u.includes("list=tag")).length, n);
  assert.strictEqual(p.$("cg-sort").value, "popular");
  p.noErrors(); p.w.close();

  // typed, on e621: its own address; the order's names are e621's
  p = await load("/dreamfeed/comics", answer, { wait: 600 });
  p.$("ct-q").value = "Big Tits"; p.$("ct-form").dispatchEvent(new p.w.Event("submit", { cancelable: true })); await p.sleep(300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/tag/big_tits", "a tag's name finds its tag");
  p.w.eval("history.back()"); await p.sleep(300);
  p.$("ct-q").value = "red panda"; p.$("ct-site").value = "e621"; p.$("ct-form").dispatchEvent(new p.w.Event("submit", { cancelable: true })); await p.sleep(300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/tag/red_panda/e621");
  assert.match(p.lastCall("list=tag").u, /tag=red_panda&sort=new&site=e621/);
  assert.strictEqual(p.$("cg-sort").options[1].textContent, "Top score");
  // a search that names a tag offers it
  p.w.eval("history.back()"); await p.sleep(300);
  p.$("cs-q").value = "furry"; p.$("cs-form").dispatchEvent(new p.w.Event("submit", { cancelable: true })); await p.sleep(300);
  assert.ok(p.shown("cg-tags") && p.text("cg-tags").includes("Browse the tag Furry"));
  await p.click("#cg-tags .chip", 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/tag/furry");
  p.noErrors(); p.w.close();

  // straight to a tag's address
  p = await load("/dreamfeed/comics/tag/anal", answer, { wait: 600 });
  assert.strictEqual(p.text("cg-title"), "Anal");
  assert.ok(!p.calls.some(c => c.u.includes("api/comics/feed")), "For you isn't asked for");
  p.noErrors();
});
