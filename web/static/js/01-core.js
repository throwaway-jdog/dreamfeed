const LABEL = { anime: "Anime", furry: "Furry" };
const $ = id => document.getElementById(id);
const grid = $("grid"), tpl = $("card-tpl");
const state = { view: "feed", medium: "all", savedSource: "all", persona: "", people: [], items: [], offset: 0, more: true, loading: false, idx: -1, gen: 0 };

async function api(url, body) {
  const opts = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(url, opts);
  if (r.status === 401) { location.href = "login"; throw new Error("signed out"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}

let toastTimer;
function toast(msg, action, onAction) {
  const t = $("toast"); t.textContent = msg; t.hidden = false;
  if (action) {
    const b = document.createElement("button"); b.type = "button"; b.className = "toast-act"; b.textContent = action;
    b.onclick = () => { t.hidden = true; clearTimeout(toastTimer); onAction(); };
    t.append(" ", b);
  }
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, action ? 6000 : 2600);
}

function nightLabel(n) {
  if (n.startsWith("test-")) return "Test batch";
  const job = { comicanim: "Panel animation", comicimport: "Comic import", comicjob: "Comic", comicupdate: "New comic pages" }[n.split("-")[0]];
  if (job) return job;
  const v = n.match(/^video-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/);
  if (v) {
    const d = new Date(+v[1], v[2] - 1, +v[3], +v[4], +v[5]);
    return "Clips " + d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }
  const m = n.match(/^manual-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/);
  if (m) {
    const d = new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]);
    return "Made " + d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }
  const d = new Date(n + "T12:00:00");
  return isNaN(d) ? n : d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  const sec = (Date.now() - d) / 1000;
  if (isNaN(sec)) return "";
  if (sec < 60) return "now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  if (sec < 7 * 86400) return `${Math.floor(sec / 86400)}d`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
const personaOf = h => state.people.find(p => p.handle === h);
function avatarEl(cls, who) {
  const a = document.createElement("span"); a.className = "av" + (cls ? " " + cls : "");
  fillAvatar(a, who); return a;
}
function fillAvatar(a, who) {
  a.replaceChildren();
  if (who && who.avatar) { const i = new Image(); i.alt = ""; i.loading = "lazy"; i.src = `avatar/${who.handle}`; a.append(i); }
  else a.textContent = (who?.name || "?").replace(/[^\p{L}\p{N}]/gu, "").slice(0, 1).toUpperCase() || "·";
}
// e621's files, through dreamfeed: e621 turns away pictures a browser shows on another site
// (the API keeps e621's own addresses: the iOS app loads them itself).
const viaUs = u => typeof u === "string" && u.startsWith("https://static1.e621.net/data/") ? "e621-media/" + u.slice(25) : u;
