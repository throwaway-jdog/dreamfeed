// Real Firefox against the running site (what jsdom can't: drawing, the page's security policy,
// playing video). Env: URL (the site, e.g. https://example/dreamfeed), COOKIE (a dreamfeed session,
// name=value). Firefox: Playwright's Chromium has no H.264, so videos never start in it.
//   - Live: a card's Profile opens the room's profile, visibly
//   - Videos: For you lists videos and one plays
const { firefox, devices } = require("playwright");
const assert = require("assert");
const base = process.env.URL.replace(/\/$/, ""), cookie = process.env.COOKIE, host = new URL(base).hostname;

async function page(browser, opts) {
  const ctx = await browser.newContext(opts);
  const i = cookie.indexOf("=");
  await ctx.addCookies([{ name: cookie.slice(0, i), value: cookie.slice(i + 1), domain: host, path: new URL(base).pathname, secure: true, httpOnly: true, sameSite: "Lax" }]);
  const p = await ctx.newPage(); p.errs = [];
  p.on("pageerror", e => p.errs.push(String(e).slice(0, 300)));
  p.on("console", m => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) p.errs.push(m.text().slice(0, 300)); });
  return p;
}

(async () => {
  const browser = await firefox.launch(); let failed = false;
  const step = async (name, fn) => { try { await fn(); console.log(`ok   ${name}`); } catch (e) { failed = true; console.log(`FAIL ${name}\n     ${String(e.message || e).split("\n")[0]}`); } };
  for (const [label, opts] of [["desktop", { viewport: { width: 1280, height: 900 } }], ["phone-sized", { viewport: { width: 390, height: 844 } }]]) {
    await step(`Live: Profile opens (${label})`, async () => {
      const p = await page(browser, opts);
      await p.goto(`${base}/live`, { waitUntil: "networkidle" });
      const prof = p.locator("button.vids", { hasText: "Profile" }).first();
      if (!await prof.count()) { console.log("     (no rooms on Live: skipped)"); return; }
      await prof.click(); await p.waitForTimeout(2500);
      assert.ok(await p.isVisible("#pf-view"), "the profile window isn't visible");
      const box = await p.locator("#pf-view").boundingBox();
      assert.ok(box && box.width > 300 && box.height > 400, `the profile window is ${JSON.stringify(box)}`);
      assert.ok((await p.textContent("#pf-title")).trim(), "its title is empty");
      assert.deepStrictEqual(p.errs, []);
    });
  }
  await step("Videos: For you, and one plays", async () => {
    const p = await page(browser, { viewport: { width: 1280, height: 900 } });
    await p.goto(`${base}/vids`, { waitUntil: "networkidle" });
    await p.waitForSelector("#vg .pf-vid", { timeout: 60000 });
    await p.locator("#vg .pf-vid").first().click();
    // (polled from here: the page's own policy doesn't let a test run code inside it by eval)
    for (let i = 0; i < 30 && await p.evaluate(() => document.getElementById("xv-video").currentTime) <= 1; i++) await p.waitForTimeout(1000);
    const v = await p.evaluate(() => { const v = document.getElementById("xv-video"); return { w: v.videoWidth, playing: !v.paused }; });
    assert.ok(v.w > 0 && v.playing, JSON.stringify(v));
    await p.click("#xv-close");
    assert.deepStrictEqual(p.errs, []);
  });
  await browser.close();
  process.exit(failed ? 1 : 0);
})();
