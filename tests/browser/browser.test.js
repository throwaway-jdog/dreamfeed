// Real Firefox against the running site (what jsdom can't: drawing, the page's security policy,
// playing video). Env: URL (the site, e.g. https://example/dreamfeed), COOKIE (a dreamfeed session,
// name=value). Firefox: Playwright's Chromium has no H.264, so videos never start in it.
//   - Live: a card's Profile opens the room's profile, visibly
//   - Videos: For you lists videos and one plays
//   - Search: its parts' pictures load; Updates and History open, the header fits a phone
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
  await step("Feed: e621's pictures load (through dreamfeed: e621 turns away other sites' pages)", async () => {
    const p = await page(browser, { viewport: { width: 1280, height: 900 } });
    await p.goto(`${base}/feed`, { waitUntil: "networkidle" });
    await p.evaluate(() => { try { localStorage.setItem("feedSource", "e621"); } catch {} });
    await p.goto(`${base}/feed`, { waitUntil: "networkidle" }); await p.waitForTimeout(5000);
    const ok = await p.evaluate(() => [...document.querySelectorAll("#f-posts img")].slice(0, 8).map(i => i.naturalWidth > 0));
    await p.evaluate(() => { try { localStorage.removeItem("feedSource"); } catch {} });
    if (!ok.length) { console.log("     (no e621 posts: skipped)"); return; }
    assert.ok(ok.some(Boolean), `none of ${ok.length} e621 pictures loaded`);
    assert.deepStrictEqual(p.errs, []);
  });
  await step("Comics: covers and pages load from the sites", async () => {
    const p = await page(browser, { viewport: { width: 1280, height: 900 } });
    await p.goto(`${base}/comics`, { waitUntil: "networkidle" });
    await p.waitForSelector("#cg .comic-card", { timeout: 60000 });
    await p.locator("#cg .comic-card").first().scrollIntoViewIfNeeded(); await p.waitForTimeout(3000);   // (For you is below the rows: its covers load when near)
    const covers = await p.evaluate(() => [...document.querySelectorAll("#cg .comic-card img")].slice(0, 12).map(i => ({ host: new URL(i.src, location.href).hostname, ok: i.complete && i.naturalWidth > 0 })));
    for (const host of new Set(covers.map(c => c.host))) {
      const mine = covers.filter(c => c.host === host);
      assert.ok(mine.some(c => c.ok), `no cover from ${host} loaded (${mine.length} tried)`);
    }
    // (a comic can be refused once opened: a page with a word dreamfeed never allows. Then the next.)
    const loaded = () => p.evaluate(() => { const i = document.querySelector("#rd-track img"); return !document.getElementById("reader").hidden && !!i && i.complete && i.naturalWidth > 0; });
    let ok = false;
    for (let n = 0; n < 3 && !ok; n++) {
      await p.locator("#cg .comic-card").nth(n).click();
      for (let i = 0; i < 20 && !(ok = await loaded()); i++) await p.waitForTimeout(1000);
      if (!ok) { await p.goto(`${base}/comics`, { waitUntil: "networkidle" }); await p.waitForSelector("#cg .comic-card"); }
    }
    assert.ok(ok, "none of the first 3 comics showed its first page");
    assert.deepStrictEqual(p.errs, []);
  });
  await step("Comics: multporn's New and Updated, and a tag's comics, with their covers", async () => {
    const p = await page(browser, { viewport: { width: 390, height: 844 } });
    await p.goto(`${base}/comics`, { waitUntil: "networkidle" });
    for (const row of ["#cn-row", "#cw-row"]) await p.waitForSelector(`${row} .comic-card`, { timeout: 60000 });
    assert.ok(await p.locator("#ct-chips .chip").count() > 50, "multporn's tags aren't listed");
    await p.goto(`${base}/comics/tag/furry`, { waitUntil: "networkidle" });
    await p.waitForSelector("#cg .comic-card", { timeout: 60000 }); await p.waitForTimeout(3000);
    assert.strictEqual(await p.textContent("#cg-title"), "Furry");
    const ok = await p.evaluate(() => [...document.querySelectorAll("#cg .comic-card img")].slice(0, 4).some(i => i.complete && i.naturalWidth > 0));
    assert.ok(ok, "no cover of a tag's comics loaded");
    const wide = await p.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(wide <= 390, `the page is wider than a phone: ${wide}`);
    assert.deepStrictEqual(p.errs, []);
  });
  await step("Feed: switching tabs back and forth fast, it's there each time, as you left it", async () => {
    const p = await page(browser, { viewport: { width: 390, height: 844 } });
    await p.goto(`${base}/feed`, { waitUntil: "domcontentloaded" });
    await p.waitForSelector("#f-posts article.post", { timeout: 90000 });
    await p.mouse.wheel(0, 1500); await p.waitForTimeout(800);
    const y = await p.evaluate(() => scrollY);
    for (let i = 0; i < 6; i++) {               // (quicker than a page could be read)
      await p.click('[data-view="vids"]'); await p.waitForTimeout(150);
      await p.click('[data-view="posts"]'); await p.waitForTimeout(150);
    }
    const t = Date.now();
    await p.waitForSelector("#f-posts article.post", { timeout: 2000 });
    assert.ok(Date.now() - t < 1000, "the Feed took a second to come back");
    await p.waitForTimeout(400);
    const back = await p.evaluate(() => scrollY);
    assert.ok(Math.abs(back - y) < 200, `not where you left it: ${back} (was ${y})`);
    assert.ok(await p.locator("#f-posts article.post").count() <= 40, "drawn a few at a time");
    assert.deepStrictEqual(p.errs, []);
  });
  await step("Search: posts, subreddits and videos, their pictures allowed by the page's policy", async () => {
    const p = await page(browser, { viewport: { width: 1280, height: 900 } });
    await p.goto(`${base}/search/femboy`, { waitUntil: "networkidle" });
    await p.waitForSelector("#se-posts .post", { timeout: 90000 });
    await p.locator("#se-posts .post").first().scrollIntoViewIfNeeded();    // (its pictures load when near)
    const look = () => p.evaluate(() => [...document.querySelectorAll("#se-posts .post .media img")].slice(0, 6)
      .map(i => ({ host: new URL(i.src, location.href).hostname, done: i.complete, ok: i.complete && i.naturalWidth > 0 })));
    let pics = [];
    for (let i = 0; i < 20 && !(pics = await look()).some(x => x.ok); i++) {   // (the other parts answering above push the posts down)
      await p.locator("#se-posts .post .media img").first().scrollIntoViewIfNeeded().catch(() => {}); await p.waitForTimeout(1000);
    }
    assert.ok(pics.some(x => x.ok), `none of ${pics.length} pictures loaded: ${JSON.stringify(pics)}`);
    assert.ok(await p.isVisible("#se-subs-sec"), "no subreddits");
    assert.deepStrictEqual(p.errs, []);
  });
  await step("Updates and History open; the header's buttons fit a phone", async () => {
    const p = await page(browser, { viewport: { width: 390, height: 844 } });
    await p.goto(`${base}/feed`, { waitUntil: "networkidle" });
    for (const id of ["search-btn", "upd-btn", "menu-btn"]) {
      const box = await p.locator("#" + id).boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= 390, `#${id} is off the screen: ${JSON.stringify(box)}`);
    }
    await p.click("#upd-btn"); await p.waitForTimeout(1500);
    assert.ok(await p.isVisible("#updates"), "Updates isn't visible");
    await p.click("#menu-btn"); await p.click("#sheet-history"); await p.waitForTimeout(1500);
    assert.ok(await p.isVisible("#history"), "History isn't visible");
    assert.deepStrictEqual(p.errs, []);
  });
  await browser.close();
  process.exit(failed ? 1 : 0);
})();
