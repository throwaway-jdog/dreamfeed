// Videos → Recordings: every room's recordings, newest first; All / Recordings / Highlights; a room's
// chip (its own address); a tap plays it; and For you is still the tab's other side.
const { load, run, assert } = require("./harness");

const vid = (room, path, mtime, highlight = false) => ({ room, path, title: path.replace(".mp4", ""), size: 2e9, mtime, duration: 3600,
  highlight, url: `cb-videos/${room}/${path}`, poster: null, job: null, has_highlight: false });
const ALL = [vid("aroom", "a2.mp4", 300), vid("broom", "b1.highlights.mp4", 200, true), vid("aroom", "a1.mp4", 100)];
const ROOMS = [{ name: "aroom", count: 2, latest: 300 }, { name: "broom", count: 1, latest: 200 }];

run("Videos: Recordings", async () => {
  const p = await load("/dreamfeed/vids/recordings", u => {
    if (u.includes("api/live/recordings")) {
      const q = new URL(u, "https://x/").searchParams, room = q.get("room"), kind = q.get("kind");
      const vs = ALL.filter(v => (!room || v.room === room) && (!kind || v.highlight === (kind === "highlights")));
      return { videos: vs, more: false, total: vs.length, rooms: ROOMS, folder: true };
    }
    if (u.includes("api/live/videos")) return { videos: ALL.filter(v => v.room === "aroom"), folder: true };
  });
  assert.ok(p.shown("vr-pane") && !p.shown("vx-pane"), "Recordings shown, For you not");
  assert.strictEqual(p.d.querySelector('#vs-tab [data-t="recs"]').getAttribute("aria-pressed"), "true");
  p.same([...p.d.querySelectorAll("#vr-grid .pf-vid b")].map(b => b.textContent), ["a2", "b1.highlights", "a1"]);
  assert.ok(p.text("vr-grid").includes("aroom ·"), "each says whose");
  p.same([...p.d.querySelectorAll("#vr-rooms .chip")].map(c => c.textContent), ["All 3", "aroom 2", "broom 1"]);
  assert.ok(p.text("vr-note").includes("3 videos"));
  // Highlights only (remembered)
  await p.click('#vr-kind [data-k="highlights"]', 200);
  assert.ok(p.lastCall("api/live/recordings").u.includes("kind=highlights"));
  p.same([...p.d.querySelectorAll("#vr-grid .pf-vid b")].map(b => b.textContent), ["b1.highlights"]);
  assert.strictEqual(p.w.localStorage.getItem("recsKind"), "highlights");
  await p.click('#vr-kind [data-k=""]', 200);
  // a room's chip: its own address, only theirs, and its Profile
  await p.click(p.d.querySelectorAll("#vr-rooms .chip")[1], 200);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/vids/recordings/aroom");
  assert.ok(p.lastCall("api/live/recordings").u.includes("room=aroom"));
  assert.strictEqual(p.text("vr-title"), "aroom"); assert.ok(p.shown("vr-profile"));
  assert.ok(!p.text("vr-grid").includes("aroom ·"), "one room's: no need to say whose");
  // a tap plays it (that room's videos, from this one)
  await p.click("#vr-grid .pf-vid", 300);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/room/aroom/video/a2.mp4");
  assert.ok(p.shown("player"));
  p.w.history.back(); await p.sleep(300);
  // For you: the other side; and the Videos tab button comes back to where you were
  await p.click('#vs-tab [data-t="foryou"]', 200);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/vids");
  assert.ok(p.shown("vx-pane") && !p.shown("vr-pane"));
  await p.click('#vs-tab [data-t="recs"]', 200);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/vids/recordings/aroom", "back to the room you were on");
  p.w.eval('go("feed")'); await p.sleep(200);
  await p.click('[data-view="vids"]', 200);
  assert.strictEqual(p.w.location.pathname, "/dreamfeed/vids/recordings/aroom");
  p.noErrors();
});
