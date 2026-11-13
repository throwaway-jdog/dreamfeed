// The Dashboard's Sign-ins: each site's row says what's set (never the values), pasting
// cookies, the server's browser (started first, then its cookies taken), Reddit's keys, e621's
// and Bluesky's sign-in.
const { load, run, assert } = require("./harness");

let e621 = { site: "e621", name: "e621", from: null, username: null, signed_in: false };
const status = () => ({
  sites: [{ site: "x", name: "X", set: "file", count: 12, expires: 1825207464, updated: 1790000000, missing: [], browser: true, refresh: { at: Date.now() / 1000 - 7200, error: null } },
          { site: "xvideos", name: "xvideos", set: null, count: 0, expires: null, updated: null, missing: [], browser: false }],
  reddit: { site: "reddit", name: "Reddit", from: "env", app: true, client_id: "abc", signed_in: true, username: "me", redirect: "https://h/dreamfeed/reddit/callback" },
  e621, bsky: { site: "bsky", name: "Bluesky", from: "dashboard", handle: "me.bsky.social", signed_in: true }, browser: "browser/" });

run("Sign-ins", async () => {
  const p = await load("/dreamfeed/dashboard?reddit=Signed%20in%20to%20Reddit%20as%20u%2Fme", (u, b) => {
    if (u.includes("api/signins") && b) {
      if (b.site === "e621" && b.api_key) e621 = { ...e621, from: "dashboard", username: b.username, signed_in: true, favorites: 1234, blacklist: 3 };
      return b.site === "e621" ? { site: e621 } : { site: status().sites[0], check: null, ok: true };
    }
    if (u.includes("api/signins")) return status();
    if (u.includes("api/browser/start")) return { running: true, viewers: 0 };
  });
  const rows = () => [...p.d.querySelectorAll("#si-list .si-head")].map(h => h.textContent);
  assert.strictEqual(p.w.location.search, "", "Reddit's ?reddit= note is taken off the address");
  assert.ok(rows().some(r => /^X.*12 cookies/.test(r)), "X: set, its count");
  assert.ok(rows().some(r => /^xvideos.*Not set/.test(r)));
  assert.ok(rows().some(r => /Bluesky.*Signed in as @me\.bsky\.social/.test(r)));
  assert.match(p.text("si-list"), /taken again by itself each day \(last 2h ago\)/);
  // paste cookies
  await p.click([...p.d.querySelectorAll("#si-list button")].find(b => b.textContent === "Update"), 50);
  const f = p.d.querySelector(".si-form"); f.querySelector("textarea").value = "auth_token=a; ct0=b";
  f.dispatchEvent(new p.w.Event("submit")); await p.sleep(250);
  assert.deepStrictEqual(p.lastSent("api/signins").body, { site: "x", cookies: "auth_token=a; ct0=b" });
  // the server's browser: started, then the tab sent to it
  p.w.open = () => { const t = { location: null, close() {} }; p.w._tab = t; return t; };
  await p.click([...p.d.querySelectorAll("#si-list button")].find(b => /server's browser/.test(b.textContent)), 300);
  assert.ok(p.lastCall("api/browser/start"), "it starts the browser first"); assert.strictEqual(p.w._tab.location, "browser/");
  await p.click([...p.d.querySelectorAll("#si-list button")].find(b => b.textContent === "Take its cookies"), 300);
  assert.deepStrictEqual(p.lastSent("api/signins").body, { site: "x", from_browser: true });
  // Reddit: keep here, its keys form shows the redirect address
  await p.click([...p.d.querySelectorAll("#si-list button")].find(b => b.textContent === "App keys"), 50);
  assert.match(p.d.querySelector(".si-uri").textContent, /\/dreamfeed\/reddit\/callback$/);
  // e621
  await p.click([...p.d.querySelectorAll("#si-list button")].find(b => b.textContent === "Sign in"), 50);
  const forms = p.d.querySelectorAll(".si-form"), ef = forms[forms.length - 1]; const [n, k] = ef.querySelectorAll("input");
  n.value = "me"; k.value = "abcdefghij1234567890"; ef.dispatchEvent(new p.w.Event("submit")); await p.sleep(300);
  assert.ok(rows().some(r => /e621.*Signed in as me · 1,234 favorites/.test(r)));
  p.noErrors();
});
