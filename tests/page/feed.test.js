// The Feed: sites picked several at once (remembered), a Bluesky post (its profile, More videos),
// an e621 post's votes and Save (favorited there too), and Saved's import asking which sites.
const { load, run, assert } = require("./harness");

const bsky = { id: "bsky:z72i7hdynmk6r22z27h6tvur_3n22yg6lg2k2f", source: "bsky", author: "someone.bsky.social", nick: "Some One", place: "Femboy",
  text: "hi", posted_at: "2026-01-01 10:00:00", link: "https://bsky.app/profile/someone.bsky.social/post/3n22yg6lg2k2f", likes: 3, comments: 2,
  media: [{ kind: "hls", url: "https://video.bsky.app/watch/x/playlist.m3u8", poster: "" }] };
const e6 = { id: "e621:5", source: "e621", author: "a", artists: ["a"], place: "artists you like", text: "", posted_at: "2026-01-01 00:00:00",
  link: "https://e621.net/posts/5", score: 10, votable: true, media: [{ kind: "image", url: "https://static1.e621.net/x.jpg" }] };

run("Feed: sites, Bluesky, e621, Saved's import", async () => {
  const p = await load("/dreamfeed/feed", (u, b) => {
    if (u.includes("api/following/posts")) return { posts: [bsky], more: false, cursor: null, errors: {} };
    if (u.includes("api/profile?bsky")) return { room: null, x: [], reddit: [], e621: [], bsky: ["someone.bsky.social"], links: [], xusers: {}, xvideos: [],
      redgifs: [], bio: {}, dvr: {}, bskyuser: { handle: "someone.bsky.social", nick: "Some One", followers: 10, following: 2, posts: 5, you_follow: true } };
    if (u.includes("api/person/posts")) return { posts: [bsky], cursor: null };
    if (u.includes("api/e621/vote")) return { score: 11, up: 12, down: -1, ours: b.score };
    if (u.includes("api/following/save")) return { saved: b.save, sync: { status: "done" }, keep: null };
    if (u.includes("api/saved/import") && b) return { running: false, bsky: { found: 6, added: 6 }, e621: { found: 1, added: 1 }, files: {} };
  }, { before: w => w.localStorage.setItem("feedSource", "x,reddit") });
  const on = () => [...p.d.querySelectorAll("#f-source button")].filter(b => b.getAttribute("aria-pressed") === "true").map(b => b.dataset.s).join(",");
  const src = () => decodeURIComponent(p.lastCall("api/following/posts").u.match(/source=([^&]*)/)[1]);
  const pick = s => p.click(`#f-source button[data-s="${s}"]`, 120);
  assert.strictEqual(on(), "x,reddit", "the remembered pick"); assert.strictEqual(src(), "x,reddit");
  await pick("bsky"); assert.strictEqual(src(), "x,bsky,reddit");
  await pick("x"); await pick("bsky"); assert.strictEqual(on(), "reddit"); assert.ok(p.shown("br-form"), "Reddit alone: Browse");
  await pick("reddit"); assert.strictEqual(on(), "all", "none left: All");
  // a Bluesky post
  const card = p.d.querySelector("#f-posts article.post");
  assert.match(card.querySelector(".head").textContent, /Bluesky · Femboy/);
  assert.strictEqual(card.querySelector("a.out").textContent, "Open on Bluesky");
  const more = [...card.querySelectorAll("button")].find(b => /More videos/.test(b.textContent));
  assert.ok(more, "a Bluesky video has More videos"); await p.click(more, 300);
  assert.match(p.w.location.pathname, /^\/dreamfeed\/videos\/bsky\//); p.w.eval("history.back()"); await p.sleep(300);
  await p.click(card.querySelector(".name"), 400);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/bsky/someone.bsky.social");
  assert.strictEqual(p.text("pf-title"), "Some One"); p.w.eval("history.back()"); await p.sleep(300);
  // an e621 post: vote, Save
  const e = p.w.eval("postCard")(e6); p.d.body.append(e);
  const [up] = e.querySelectorAll(".e6-vote button"); await p.click(up, 150);
  assert.deepStrictEqual(p.lastCall("api/e621/vote").body, { id: "e621:5", score: 1 });
  assert.match(e.querySelector(".e6-vote").textContent, /11/);
  await p.click(e.querySelector("button.save"), 150);
  assert.match(e.querySelector(".acts small").textContent, /favorited on e621 too/);
  // Saved's import: asks which sites, remembers them
  p.w.eval(`go("saved")`); await p.sleep(300);
  assert.ok(p.$("saved-pick").hidden); await p.click(p.$("saved-import"));
  for (const s of ["x", "reddit"]) await p.click(`#saved-pick-sites button[data-s="${s}"]`, 30);
  await p.click(p.$("saved-pick-go"), 300);
  assert.deepStrictEqual(p.lastCall("api/saved/import").body, { sites: ["bsky", "e621"] });
  assert.match(p.text("saved-note"), /Bluesky: 6 new of 6/);
  assert.strictEqual(p.w.localStorage.getItem("importSites"), '["bsky","e621"]');
  p.noErrors();
});
