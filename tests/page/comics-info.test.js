// Comics: a multporn comic's Info (its author, section, characters, tags, user tags, rating,
// views, description, translations, comments, more comments), and the lists its details open
// (an author's comics, a section's), with their order; a gay one (comics/mpg/SLUG).
const { load, run, assert } = require("./harness");

const FEED = { comics: [], more: false, updated: [], continue: [], following: [], library: [], taste: { tags: [], n: 0 } };
const card = (slug, extra) => ({ id: `mp:${slug}`, source: "multporn", title: slug.replace(/_/g, " "), pages: null, cover: null,
  thumb: "comic-search/thumb?u=x", tags: [], artists: ["Harkart"], link: `https://multporn.net/comics/${slug}`, ...extra });
const link = (list, slug, name) => ({ list, slug, name });
const READ = { ...card("the_surprise"), pages: 3, images: [1, 2, 3].map(n => ({ url: `https://multporn.net/sites/default/files/p${n}.jpg`, full: `https://multporn.net/sites/default/files/p${n}.jpg` })),
  about: { author: [link("author", "harkart", "Harkart")], section: [link("section", "gumball", "Gumball")], characters: [link("character", "nicole", "Nicole")],
           tags: [link("tag", "milf", "MILF")], usertags: [link("usertag", "mind_break_tag", "Mind Break")] },
  rating: { average: 4.7, votes: 7572 }, views: 8315233, description: "Line one\nline two", translations: [{ id: "mp:surpriz", lang: "Русский" }],
  comments: { comments: [{ id: "1", user: "Ann", at: "2026-11-10 10:00:00", text: "Good", score: 4.1, depth: 0 },
                         { id: "2", user: "Bo", at: null, text: "A reply", score: 0, depth: 1 }], more: true },
  page: 1, followed: false, new_from: null };

run("Comics: Info, and the lists it opens", async () => {
  const p = await load("/dreamfeed/comics/mp/the_surprise", u =>
    u.includes("api/comics/feed") ? FEED : u.includes("api/comics/tags") ? { tags: [] }
    : u.includes("api/comics/read") ? (u.includes("mpg%3A") ? { ...READ, id: "mpg:gay_one", title: "Gay one", about: { ...READ.about, section: [link("gsection", "furry", "Furry")] } } : READ)
    : u.includes("api/comics/comments") ? { comments: [{ id: "3", user: "Cy", at: null, text: "Page two", score: -1, depth: 0 }, { id: "1", user: "Ann", text: "Good" }], more: false }
    : u.includes("list=author") ? { results: [card("one"), card("two")], more: true, tag: { tag: "harkart", name: "Harkart", site: "multporn", list: "author" } }
    : u.includes("list=section") ? { results: [card("three")], more: false, tag: { tag: "gumball", name: "Gumball", site: "multporn", list: "section" } }
    : u.includes("list=new") || u.includes("list=updated") ? { results: [], more: false } : undefined, { wait: 600 });
  assert.ok(p.shown("reader") && p.shown("reader-info"));
  await p.click(p.$("reader-info"), 100);
  assert.ok(p.shown("rd-info") && !p.shown("rd-track") && !p.shown("rd-foot"));
  assert.strictEqual(p.$("reader-info").getAttribute("aria-pressed"), "true");
  const info = p.text("rd-info");
  for (const want of ["★ 4.7 (7,572 votes)", "8,315,233 views", "3 pages", "Line one", "Harkart", "Gumball", "Nicole", "MILF", "Mind Break", "Русский", "Ann", "A reply", "+4.1"])
    assert.ok(info.includes(want), want);
  assert.strictEqual(p.d.querySelectorAll(".rd-cmt")[1].style.getPropertyValue("--d"), "1", "a reply, a step in");
  // more comments: the next page, each once
  await p.click(p.$("rd-cmt-more"), 150);
  assert.match(p.lastCall("api/comics/comments").u, /id=mp%3Athe_surprise&page=1/);
  assert.deepStrictEqual([...p.d.querySelectorAll(".rd-cmt p")].map(x => x.textContent), ["Good", "A reply", "Page two"]);
  assert.ok(!p.shown("rd-cmt-more"));
  // the author: all their comics, in an order
  await p.click([...p.d.querySelectorAll("#rd-info .chip")].find(c => c.textContent === "Harkart"), 400);
  assert.ok(!p.shown("reader"));
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/author/harkart");
  assert.strictEqual(p.text("cg-title"), "Comics by Harkart");
  assert.ok(p.shown("cg-bar"));
  assert.match(p.lastCall("list=author").u, /tag=harkart&sort=new&site=multporn&page=0/);
  assert.match(p.text("cg"), /two.*by Harkart/);
  p.$("cg-sort").value = "top"; p.$("cg-sort").dispatchEvent(new p.w.Event("change")); await p.sleep(200);
  assert.match(p.lastCall("list=author").u, /sort=top/);
  // back to the comic, and its section
  p.w.eval("history.back()"); await p.sleep(400);
  assert.ok(p.shown("reader"));
  await p.click(p.$("reader-info"), 100);
  await p.click([...p.d.querySelectorAll("#rd-info .chip")].find(c => c.textContent === "Gumball"), 400);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/section/gumball");
  assert.strictEqual(p.text("cg-title"), "Section: Gumball");
  // a gay one: its own address; its section is the gay section's list
  p.w.eval("go('comics/mpg/gay_one')"); await p.sleep(400);
  assert.match(p.lastCall("api/comics/read").u, /id=mpg%3Agay_one/);
  await p.click(p.$("reader-info"), 100);
  await p.click([...p.d.querySelectorAll("#rd-info .chip")].find(c => c.textContent === "Furry"), 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/comics/gsection/furry");
  p.noErrors();
});
