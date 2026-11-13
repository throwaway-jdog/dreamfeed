const $ = id => document.getElementById(id);
const grid = $("grid");      // (Saved's posts)
const state = { view: "posts", savedSource: "all", items: [], offset: 0, more: true, loading: false, gen: 0 };
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

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
// e621's files, through dreamfeed: e621 turns away pictures a browser shows on another site
// (the API keeps e621's own addresses: the iOS app loads them itself).
const viaUs = u => typeof u === "string" && u.startsWith("https://static1.e621.net/data/") ? "e621-media/" + u.slice(25) : u;
