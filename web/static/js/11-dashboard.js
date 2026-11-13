/* ---------- dashboard ---------- */
// Health: whether each part is working (sign-ins, the Feed's sites, the recorder, the server's
// browser, jobs, disk), worst first.
async function loadHealth() {
  $("hl-note").textContent = "Looking…";
  let d;
  try { d = await api("api/health"); } catch (err) { $("hl-note").textContent = err.message; return; }
  const order = { bad: 0, warn: 1, ok: 2, off: 3 }, mark = { bad: "✗", warn: "⚠", ok: "✓", off: "–" };
  d.parts = d.parts || [];
  const rows = d.parts.slice().sort((a, b) => order[a.state] - order[b.state]);
  $("hl-list").replaceChildren(...rows.map(r => {
    const li = el("li", r.state), body = el("div");
    body.append(el("b", null, r.part), el("small", null, r.says));
    li.append(el("span", "dot", mark[r.state]), body); return li;
  }));
  const n = s => d.parts.filter(r => r.state === s).length;
  $("hl-note").textContent = n("bad") ? `${n("bad")} not working${n("warn") ? `, ${n("warn")} to look at` : ""}.` : n("warn") ? `${n("warn")} to look at.` : "Everything's working.";
}
$("hl-again").onclick = loadHealth;
