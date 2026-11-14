// The page in jsdom, with the API answered by a test's own fake. Each test: load an address,
// do what a person would, and assert what should happen. Any error the page throws fails it.
//   const t = require("./harness"); const p = await t.load("/dreamfeed/vids", u => ({ ... }));
// jsdom doesn't draw, enforce the page's security policy or play media: tests/browser/ does
// those in a real browser.
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const assert = require("assert");

const PAGE = process.env.PAGE || "/out/page.html";
const sleep = ms => new Promise(r => setTimeout(r, ms));

// what most addresses answer when a test doesn't say (enough for the page to start)
function quiet(u) {
  if (u.includes("api/post/comments")) return { comments: [] };
  if (u.includes("api/health")) return { parts: [], worst: "ok", at: 0 };
  if (u.includes("api/following/posts")) return { posts: [], more: false, cursor: null, errors: {} };
  if (u.includes("api/following/settings")) return { reddit: { follow: [], subscribed: [], top: 0 }, e621: { searches: [], top: 0 } };
  if (u.includes("api/following")) return { rooms: [], status: {}, dvr: {} };
  if (u.includes("api/feed")) return { items: [], more: false };
  if (u.includes("api/discover/cb")) return { rooms: [], more: false };
  if (u.includes("api/discover/x")) return { people: [] };
  if (u.includes("api/personas")) return { personas: [] };
  if (u.includes("api/person/posts")) return { posts: [], cursor: null };
  if (u.includes("api/signins")) return { sites: [], reddit: { site: "reddit", from: null, app: false }, e621: { site: "e621", from: null, signed_in: false },
                                         bsky: { site: "bsky", from: null, signed_in: false }, browser: null };
  if (u.includes("api/saved/import")) return { running: false, files: {} };
  if (u.includes("api/vids")) return { videos: [], more: false, continue: [], taste: { tags: [], n: 0 } };
  if (u.includes("api/comics/tags")) return { tags: [] };
  if (u.includes("api/comics/browse")) return { results: [], more: false };
  if (u.includes("api/comics")) return { comics: [], making: [], failed: [] };
  if (u.includes("api/notices")) return { notices: [], more: false, counts: {}, topics: [] };
  if (u.includes("api/history")) return { items: [], more: false, kinds: [] };
  if (u.includes("api/mutes")) return { mutes: [], kinds: [], sites: [] };
  if (u.includes("api/search?in=posts")) return { posts: [], cursor: null, errors: {} };
  if (u.includes("api/search?in=subreddits")) return { subreddits: [] };
  if (u.includes("api/search?in=yours")) return { saved: [], rooms: [], comics: [], history: [] };
  return {};
}

async function load(path, answer = () => undefined, opts = {}) {
  const raw = fs.readFileSync(PAGE, "utf8");
  const errs = [], calls = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", e => errs.push(String(e.stack || e.message || e).slice(0, 600)));
  const dom = new JSDOM(raw, { runScripts: "dangerously", virtualConsole: vc, url: "http://localhost" + path, pretendToBeVisual: true,
    beforeParse(w) {
      w.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
      w.confirm = () => true;
      w.addEventListener("unhandledrejection", e => errs.push("unhandled: " + (e.reason && e.reason.stack || e.reason)));
      w.fetch = async (u, o) => {
        u = String(u); const body = o && o.body ? JSON.parse(o.body) : null; calls.push({ u, body, method: (o && o.method) || "GET" });
        const got = answer(u, body);
        const status = got && got.__status || 200;
        const data = got === undefined ? quiet(u) : got;
        return { ok: status < 400, status, json: async () => data, headers: { get: () => "application/json" } };
      };
      w.HTMLMediaElement.prototype.load = () => {}; w.HTMLMediaElement.prototype.pause = () => {};
      w.HTMLMediaElement.prototype.play = () => Promise.resolve();
      w.HTMLMediaElement.prototype.canPlayType = () => "";
      w.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
      w.scrollTo = () => {}; w.Element.prototype.scrollTo = function () {}; w.Element.prototype.scrollIntoView = function () {};
      if (opts.before) opts.before(w);
    } });
  await sleep(opts.wait || 600);
  const w = dom.window, d = w.document;
  return {
    w, d, errs, calls, sleep,
    $: id => d.getElementById(id),
    text: id => d.getElementById(id).textContent,
    shown: id => !d.getElementById(id).hidden,
    click: async (el, ms = 150) => { (typeof el === "string" ? d.querySelector(el) : el).click(); await sleep(ms); },
    lastCall: part => calls.filter(c => c.u.includes(part)).at(-1),
    lastSent: part => calls.filter(c => c.u.includes(part) && c.body).at(-1),       // (the last that sent something)
    same: (a, b, msg) => assert.strictEqual(JSON.stringify(a), JSON.stringify(b), msg),  // (values from inside the page)
    noErrors() { assert.deepStrictEqual(errs, [], "the page threw:\n" + errs.join("\n")); },
  };
}

// one test file: its checks in order, each printed; the first failure ends it (exit 1)
async function run(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    console.log(`ok   ${name} (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
    process.exit(0);
  } catch (e) {
    console.log(`FAIL ${name}\n     ${String(e.message || e).split("\n").join("\n     ")}`);
    process.exit(1);
  }
}

module.exports = { load, run, assert, sleep };
