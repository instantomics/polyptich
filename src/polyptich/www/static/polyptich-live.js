(() => {
  if (window.polyptichLiveDocuments) return;
  window.polyptichLiveDocuments = true;
  const storageKey = "polyptich:live-document-scroll";
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
    sessionStorage.removeItem(storageKey);
    if (saved && saved.url === location.href && Date.now() - saved.time < 30000) {
      const restore = () => setTimeout(() => window.scrollTo(saved.x, saved.y), 0);
      if (document.readyState === "complete") restore();
      else window.addEventListener("load", restore, {once: true});
    }
  } catch (_) { /* Scroll persistence is optional when storage is disabled. */ }

  let checking = false;
  const check = async () => {
    const article = document.querySelector("[data-polyptich-revision-url]");
    if (!article || document.hidden || checking) return;
    checking = true;
    const url = location.href;
    try {
      const response = await fetch(article.dataset.polyptichRevisionUrl, {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) return;
      const {revision} = await response.json();
      // A request for the previous page may complete after partial navigation.
      if (!article.isConnected || location.href !== url || revision === article.dataset.polyptichRevision) return;
      try {
        sessionStorage.setItem(storageKey, JSON.stringify({
          url, x: window.scrollX, y: window.scrollY, time: Date.now(),
        }));
      } catch (_) { /* A reload still works without scroll persistence. */ }
      location.reload();
    } catch (_) { /* Retry on the next tick after transient network/auth failures. */ }
    finally { checking = false; }
  };
  setInterval(check, 2000);
  document.addEventListener("visibilitychange", check);
})();
