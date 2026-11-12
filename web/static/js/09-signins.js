/* ---------- the Reddit list (Dashboard) ---------- */
const rf = { follow: [], top: 10, subscribed: [] };
const e6 = { searches: [], top: 10 };
/* Sign-ins (dashboard): X's and Chaturbate's cookies, pasted from an export; Reddit: your app's
   keys, then Sign in with Reddit (it comes back here by itself). */
const SI_HOW = {
  x: "While signed in to x.com, export its cookies with a browser extension (cookies.txt or JSON, e.g. Cookie-Editor), or copy the Cookie header from the developer tools. auth_token and ct0 are needed.",
  chaturbate: "While signed in to chaturbate.com, export its cookies the same way. sessionid and csrftoken are needed.",
};
function siWhen(t) { return new Date(t * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); }
async function loadSignins() {
  const q = new URLSearchParams(location.search).get("reddit");
  if (q) { toast(q); history.replaceState(history.state, "", location.pathname); }
  let d;
  try { d = await api("api/signins"); } catch (err) { $("si-list").replaceChildren(el("li", "note", err.message)); return; }
  $("si-list").replaceChildren(...d.sites.map(st => siCookieRow(st, d.browser)), siBskyRow(d.bsky), siRedditRow(d.reddit), siE621Row(d.e621));
}
function siCookieRow(st, browser) {
  const li = el("li", "si-row"), head = el("div", "si-head");
  const where = st.set === "dashboard" ? "set here" : st.set === "file" ? "from the mounted file" : null;
  const words = !st.set ? "Not set" : st.missing.length ? `Missing ${st.missing.join(", ")}` :
    [where, `${st.count} cookies`, st.expires ? `good until ${siWhen(st.expires)}` : st.expires === 0 ? "until the browser closes" : "",
     st.updated ? `updated ${siWhen(st.updated)}` : ""].filter(Boolean).join(" · ");
  const up = el("button", "secondary", st.set ? "Update" : "Add"); up.type = "button";
  const info = el("small", !st.set || st.missing.length || (st.expires && st.expires * 1000 < Date.now() + 7 * 864e5) ? "bad" : null, words);
  head.append(el("b", null, st.name), up);
  if (st.set === "dashboard") {
    const rm = el("button", "secondary", "Forget"); rm.type = "button";
    rm.onclick = async () => {
      if (!confirm(`Forget the ${st.name} cookies set here?` + (st.set === "dashboard" ? " (A mounted file, if there is one, is used again.)" : ""))) return;
      try { await api("api/signins", { site: st.site, forget: true }); loadSignins(); } catch (err) { toast(err.message); }
    };
    head.append(rm);
  }
  head.append(info); li.append(head);
  if (browser) {       // the server's own browser: sign in there yourself, then take its cookies
    const site = { x: "x.com", chaturbate: "chaturbate.com" }[st.site] || st.site;
    const row = el("div", "si-acts"), open = el("button", "secondary", "Sign in on the server's browser"), take = el("button", "primary", "Take its cookies");
    open.type = take.type = "button";
    open.onclick = async () => {        // it runs only when needed: started now, the tab opened once it's up
      const tab = window.open("", "_blank");
      open.disabled = true; open.textContent = "Starting it…";
      try { await api("api/browser/start", {}); if (tab) tab.location = browser; else location.href = browser; }
      catch (err) { if (tab) tab.close(); toast(err.message); }
      finally { open.disabled = false; open.textContent = "Sign in on the server's browser"; }
    };
    take.onclick = async () => {
      take.disabled = true; take.textContent = "Checking…";
      try {
        const r = await api("api/signins", { site: st.site, from_browser: true });
        toast(r.check ? `Taken, but: ${r.check}` : `${st.name}: signed in ✓`); loadSignins();
      } catch (err) { toast(err.message); take.disabled = false; take.textContent = "Take its cookies"; }
    };
    const rf = st.refresh, auto = st.browser
      ? (rf && rf.error ? `Couldn't take them again by itself: ${rf.error}. Sign in there again.`
        : `Taken from it: taken again by itself each day${rf ? ` (last ${relTime(new Date(rf.at * 1000).toISOString())} ago)` : ""}.`)
      : `Opens a browser running on your server: go to ${site} there and sign in, then come back and tap Take its cookies. It stays signed in, and the cookies are then taken again by themselves each day.`;
    row.append(open, take, el("small", rf && rf.error ? "hint bad" : "hint", auto));
    li.append(row);
  }
  up.onclick = () => {
    if (li.querySelector(".si-form")) return;
    const form = el("form", "si-form"), ta = el("textarea", "in"), file = el("input"), save = el("button", "primary", "Save and check"), err = el("div", "ed-err");
    form.noValidate = true; ta.rows = 5; ta.placeholder = "Paste cookies.txt, JSON or a Cookie header"; ta.spellcheck = false;
    ta.setAttribute("autocomplete", "off"); ta.setAttribute("autocapitalize", "off");
    file.type = "file"; file.accept = ".txt,.json,text/plain,application/json";
    file.onchange = async () => { if (file.files[0]) ta.value = await file.files[0].text(); };
    save.type = "submit"; err.setAttribute("role", "alert");
    const acts = el("div", "si-acts"); acts.append(save, file);
    form.append(el("small", "hint", SI_HOW[st.site] || ""), ta, acts, err);
    form.onsubmit = async e => {
      e.preventDefault(); err.textContent = ""; save.disabled = true; save.textContent = "Checking…";
      try {
        const r = await api("api/signins", { site: st.site, cookies: ta.value });
        ta.value = "";
        toast(r.check ? `Saved, but: ${r.check}` : `${st.name}: signed in ✓`);
        loadSignins();
      } catch (x) { err.textContent = x.message; save.disabled = false; save.textContent = "Save and check"; }
    };
    li.append(form); ta.focus();
  };
  return li;
}
function siBskyRow(st) {
  const li = el("li", "si-row"), head = el("div", "si-head");
  const words = st.signed_in ? `Signed in as @${st.handle}` : st.error ? `Not signed in: ${st.error}` : "Not signed in: Bluesky in the Feed needs it";
  const set = el("button", "secondary", st.signed_in ? "Change" : "Sign in"); set.type = "button";
  head.append(el("b", null, "Bluesky"), set);
  if (st.from) {
    const rm = el("button", "secondary", "Forget"); rm.type = "button";
    rm.onclick = async () => { if (!confirm("Forget your Bluesky sign-in?")) return;
      try { await api("api/signins", { site: "bsky", forget: true }); loadSignins(); } catch (err) { toast(err.message); } };
    head.append(rm);
  }
  head.append(el("small", st.signed_in ? null : "bad", words)); li.append(head);
  set.onclick = () => {
    if (li.querySelector(".si-form")) return;
    const form = el("form", "si-form"), name = el("input", "in"), pw = el("input", "in"), save = el("button", "primary", "Sign in"), err = el("div", "ed-err");
    form.noValidate = true; name.placeholder = "handle, e.g. you.bsky.social"; name.value = st.handle || ""; pw.type = "password"; pw.placeholder = "app password";
    for (const x of [name, pw]) { x.setAttribute("autocomplete", "off"); x.setAttribute("autocapitalize", "off"); x.spellcheck = false; }
    save.type = "submit"; err.setAttribute("role", "alert");
    form.append(el("small", "hint", "Use an app password, not your own: on Bluesky, Settings, Privacy and security, App passwords. For adult posts, turn on adult content in Bluesky's own settings (on the web)."), name, pw, save, err);
    form.onsubmit = async e => {
      e.preventDefault(); err.textContent = ""; save.disabled = true; save.textContent = "Checking…";
      try { await api("api/signins", { site: "bsky", identifier: name.value, password: pw.value }); toast("Bluesky: signed in ✓"); loadSignins(); }
      catch (x) { err.textContent = x.message; save.disabled = false; save.textContent = "Sign in"; }
    };
    li.append(form); (st.handle ? pw : name).focus();
  };
  return li;
}
function siE621Row(st) {
  const li = el("li", "si-row"), head = el("div", "si-head");
  const words = st.signed_in ? [`Signed in as ${st.username}`, st.favorites != null ? `${Number(st.favorites).toLocaleString()} favorites` : "",
    st.blacklist ? `your blacklist's ${st.blacklist} lines applied` : "", st.from === "env" ? "from .env" : ""].filter(Boolean).join(" · ")
    : st.error ? `Not signed in: ${st.error}` : "Not signed in: Save favorites, votes, your favorites in Saved and For you need it";
  const set = el("button", "secondary", st.signed_in ? "Change" : "Sign in"); set.type = "button";
  head.append(el("b", null, "e621"), set);
  if (st.from === "dashboard") {
    const rm = el("button", "secondary", "Forget"); rm.type = "button";
    rm.onclick = async () => { if (!confirm("Forget your e621 username and API key?")) return;
      try { await api("api/signins", { site: "e621", forget: true }); loadSignins(); } catch (err) { toast(err.message); } };
    head.append(rm);
  }
  head.append(el("small", st.signed_in ? null : "bad", words)); li.append(head);
  set.onclick = () => {
    if (li.querySelector(".si-form")) return;
    const form = el("form", "si-form"), name = el("input", "in"), key = el("input", "in"), save = el("button", "primary", "Sign in"), err = el("div", "ed-err");
    form.noValidate = true; name.placeholder = "username"; name.value = st.username || ""; key.type = "password"; key.placeholder = "API key";
    for (const x of [name, key]) { x.setAttribute("autocomplete", "off"); x.setAttribute("autocapitalize", "off"); x.spellcheck = false; }
    save.type = "submit"; err.setAttribute("role", "alert");
    form.append(el("small", "hint", "On e621.net: your Account, then Manage API Access, makes the key (with your password). It's checked before it's kept."), name, key, save, err);
    form.onsubmit = async e => {
      e.preventDefault(); err.textContent = ""; save.disabled = true; save.textContent = "Checking…";
      try { await api("api/signins", { site: "e621", username: name.value, api_key: key.value }); toast("e621: signed in ✓"); loadSignins(); }
      catch (x) { err.textContent = x.message; save.disabled = false; save.textContent = "Sign in"; }
    };
    li.append(form); (st.username ? key : name).focus();
  };
  return li;
}
function siRedditRow(st) {
  const li = el("li", "si-row"), head = el("div", "si-head");
  const words = st.signed_in ? [`Signed in${st.username ? " as u/" + st.username : ""}`, st.from === "env" ? "from .env" : "set here"].join(" · ")
    : st.app ? "Your app is set: sign in with Reddit" : "Not set";
  head.append(el("b", null, "Reddit"));
  const go = el("a", "primary", st.signed_in ? "Sign in again" : "Sign in with Reddit"); go.href = "reddit/login";
  if (st.from === "dashboard" && st.app) head.append(go);
  const keys = el("button", "secondary", st.app ? "App keys" : "Add app keys"); keys.type = "button"; head.append(keys);
  if (st.from === "env") {
    const mv = el("button", "secondary", "Keep here instead"); mv.type = "button";
    mv.title = "Copy .env's Reddit app and sign-in here, so they're managed from this page";
    mv.onclick = async () => { try { await api("api/signins", { site: "reddit", from_env: true }); toast("Reddit: kept here now."); loadSignins(); } catch (err) { toast(err.message); } };
    head.append(mv);
  }
  if (st.from === "dashboard") {
    const rm = el("button", "secondary", "Forget"); rm.type = "button";
    rm.onclick = async () => {
      if (!confirm("Forget your Reddit app and sign-in set here? (.env's, if any, are used again.)")) return;
      try { await api("api/signins", { site: "reddit", forget: true }); loadSignins(); } catch (err) { toast(err.message); }
    };
    head.append(rm);
  }
  head.append(el("small", st.signed_in ? null : "bad", words)); li.append(head);
  keys.onclick = () => {
    if (li.querySelector(".si-form")) return;
    const form = el("form", "si-form"), id = el("input", "in"), sec = el("input", "in"), save = el("button", "primary", "Save keys"), err = el("div", "ed-err");
    form.noValidate = true; id.placeholder = "client id (under the app's name)"; id.value = st.client_id || "";
    sec.type = "password"; sec.placeholder = "secret"; sec.setAttribute("autocomplete", "off"); id.setAttribute("autocomplete", "off");
    id.spellcheck = false; id.setAttribute("autocapitalize", "off");
    save.type = "submit"; err.setAttribute("role", "alert");
    const how = el("small", "hint", "Your own app at reddit.com/prefs/apps (one you have already works). Edit it so its redirect uri is exactly this address:");
    const uri = el("div", "si-uri", st.redirect || "(open this page through its usual address)");
    const copy = el("button", "secondary", "Copy address"); copy.type = "button";
    copy.onclick = async () => { try { await navigator.clipboard.writeText(st.redirect); toast("Copied."); } catch { toast("Couldn't copy: select it instead."); } };
    const acts = el("div", "si-acts"); acts.append(save, copy);
    form.append(how, uri, id, sec, acts, err);
    form.onsubmit = async e => {
      e.preventDefault(); err.textContent = ""; save.disabled = true;
      try { await api("api/signins", { site: "reddit", client_id: id.value, client_secret: sec.value }); toast("Saved: now sign in with Reddit."); loadSignins(); }
      catch (x) { err.textContent = x.message; save.disabled = false; }
    };
    li.append(form); (st.client_id ? sec : id).focus();
  };
  return li;
}
async function loadReddit() {
  try { const d = await api("api/following/settings"); Object.assign(rf, d.reddit); Object.assign(e6, d.e621); renderReddit(); renderE6(); }
  catch (err) { $("rf-err").textContent = err.message; }
}
function renderE6() {
  $("e6-list").replaceChildren(...e6.searches.map(q => {
    const li = el("li", "rf-row"), rm = el("button", "secondary", "Remove"); rm.type = "button";
    rm.onclick = () => saveE6(e6.searches.filter(x => x !== q), e6.top);
    li.append(el("b", null, q), rm); return li;
  }));
  if (!e6.searches.length) $("e6-list").append(el("li", "note", "None yet."));
}
async function saveE6(searches, top) {
  $("e6-err").textContent = "";
  try { Object.assign(e6, (await api("api/following/settings", { e621: { searches, top } })).e621); renderE6(); return true; }
  catch (err) { $("e6-err").textContent = err.message; return false; }
}
$("e6-form").onsubmit = async e => {
  e.preventDefault(); const v = $("e6-q").value.trim(); if (!v) return;
  if (await saveE6([...e6.searches, v], e6.top)) { $("e6-q").value = ""; toast("Added: in your Feed now."); }
};
function renderReddit() {
  $("rf-list").replaceChildren(...rf.follow.map(name => {
    const li = el("li", "rf-row"), rm = el("button", "secondary", "Remove"); rm.type = "button";
    rm.onclick = () => saveReddit(rf.follow.filter(x => x !== name), rf.top);
    li.append(el("b", null, name), rm); return li;
  }));
  if (!rf.follow.length) $("rf-list").append(el("li", "note", "None yet."));
  $("rf-subs").textContent = rf.subscribed.length
    ? `Signed in: your ${rf.subscribed.length} subscriptions are read (${rf.subscribed.slice(0, 8).join(", ")}${rf.subscribed.length > 8 ? ", …" : ""}).`
    : "Not signed in to Reddit: only these are read.";
  $("rf-also").textContent = rf.subscribed.length ? "Also read" : "Read";
}
async function saveReddit(follow, top) {
  $("rf-err").textContent = "";
  try { Object.assign(rf, (await api("api/following/settings", { reddit: { follow, top } })).reddit); renderReddit(); return true; }
  catch (err) { $("rf-err").textContent = err.message; return false; }
}
$("rf-form").onsubmit = async e => {
  e.preventDefault(); const v = $("rf-name").value.trim(); if (!v) return;
  if (await saveReddit([...rf.follow, v], rf.top)) { $("rf-name").value = ""; toast("Added: in your Feed now."); }
};


