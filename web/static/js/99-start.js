/* ---------- start ----------
   Last, once every part is read: the first page loads, and the page opens what its address names. */
new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) loadMore(); }, { rootMargin: "800px" }).observe($("sentinel"));
refreshSummary();
// The page opens what its address names (old #live-style links too).
{
  const old = { dashboard: "dashboard", comics: "comics", following: "live", live: "live" }[location.hash.slice(1)];
  history.replaceState({ n: 0 }, "", old ? BASE + old : location.pathname);
}
state.view = "";   // so setView runs for the first view
route();
