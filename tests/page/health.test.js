// The Dashboard's Health: each part with ✓ ⚠ ✗, worst first, and a line saying how many.
const { load, run, assert } = require("./harness");

run("Health", async () => {
  const p = await load("/dreamfeed/dashboard", u => u.includes("api/health") ? { worst: "bad", at: 0, parts: [
    { part: "X sign-in", state: "ok", says: "set" }, { part: "Recorder", state: "bad", says: "streamonitor didn't answer" },
    { part: "e621 in the Feed", state: "warn", says: "femboy: not something to look for" }, { part: "Bluesky sign-in", state: "off", says: "not set" }] } : undefined);
  const rows = [...p.d.querySelectorAll("#hl-list li")].map(li => li.querySelector(".dot").textContent + " " + li.querySelector("b").textContent);
  p.same(rows, ["✗ Recorder", "⚠ e621 in the Feed", "✓ X sign-in", "– Bluesky sign-in"]);
  assert.strictEqual(p.text("hl-note"), "1 not working, 1 to look at.");
  await p.click(p.$("hl-again"), 200);
  assert.strictEqual(p.calls.filter(c => c.u.includes("api/health")).length, 2, "Look again asks again");
  p.noErrors();
});
