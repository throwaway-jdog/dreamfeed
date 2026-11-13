/* ---------- Saved ----------
   What you saved from the Feed (and brought in from the sites), newest first, a page at a time. */
async function reset() {
  state.gen++; state.items = []; state.offset = 0; state.more = true; grid.replaceChildren();
  $("empty").hidden = true; await loadMore();
}

async function loadMore() {
  if (state.view === "posts") { if (fp.more) loadPosts(false); return; }
  if (state.view !== "liked" || state.loading || !state.more) return;
  state.loading = true; $("loading").hidden = false;
  const gen = state.gen;
  try {
    const data = await api(`api/feed?${new URLSearchParams({ view: "liked", source: state.savedSource, offset: state.offset })}`);
    if (gen !== state.gen) return;
    state.offset += data.items.length; state.more = data.more;
    for (const it of data.items) {
      if (!it.post) continue;
      state.items.push(it); const w = el("div", "fposts saved-post"); w.append(postCard(it.post)); grid.append(w);
    }
    showEmpty();
  } catch (e) { if (e.message !== "signed out") toast(e.message); state.more = false; }
  finally { state.loading = false; $("loading").hidden = true; }
}

// Feed videos don't play by themselves: one you start stops when it's scrolled away.
const playObs = new IntersectionObserver(es => {
  for (const e of es) if (!e.isIntersecting || e.intersectionRatio < .2) e.target.pause();
}, { threshold: [0, .2] });

function showEmpty() {
  const e = $("empty");
  if (state.items.length) { e.hidden = true; return; }
  e.hidden = false;
  e.innerHTML = "<strong>Nothing saved yet</strong>Tap Save on Feed posts, or bring in what you saved on the sites: they're kept here.";
}
