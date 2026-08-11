(() => {
  "use strict";

  const shell = document.querySelector("#pt-global-navigation-shell[data-polyptich-navigation-shell]");
  if (!shell) return;

  const listRoot = shell.querySelector("[data-pt-navigation-list]");
  const title = shell.querySelector("[data-pt-navigation-title]");
  const toc = shell.querySelector("[data-pt-navigation-toc]");
  const toggle = shell.querySelector(".pt-global-navigation__toggle");
  const overlay = shell.querySelector(".pt-global-navigation__overlay");
  const sidebar = shell.querySelector(".pt-global-navigation__sidebar");
  const contextElement = document.getElementById("pt-global-navigation-context");
  let pageContext = {navigation_id: null, toc: true};
  try {
    if (contextElement) pageContext = JSON.parse(contextElement.textContent);
  } catch (_error) {
    pageContext = {navigation_id: null, toc: true};
  }
  let controlIndex = 0;
  let returnFocus = null;
  let preferredNavigationAvailable = false;

  const isActive = (href) => {
    const target = new URL(href, window.location.href);
    const current = new URL(window.location.href);
    const trim = (value) => value.length > 1 ? value.replace(/\/+$/, "") : value;
    return trim(target.pathname) === trim(current.pathname) && target.search === current.search;
  };

  const containsNavigationId = (items, id) => items.some((item) =>
    item.id === id || (Array.isArray(item.children) && containsNavigationId(item.children, id))
  );

  const markActive = (anchor, item) => {
    if (pageContext.navigation_id && item.id === pageContext.navigation_id) {
      shell.querySelectorAll('[aria-current="page"]').forEach((current) => current.removeAttribute("aria-current"));
      preferredNavigationAvailable = true;
      anchor.setAttribute("aria-current", "page");
    } else if (!preferredNavigationAvailable && item.href && isActive(item.href)) {
      anchor.setAttribute("aria-current", "page");
    }
  };

  const openDrawer = () => {
    returnFocus = document.activeElement;
    shell.classList.add("pt-global-navigation--open");
    toggle.setAttribute("aria-expanded", "true");
    sidebar.setAttribute("aria-modal", "true");
    sidebar.setAttribute("role", "dialog");
    const focusable = sidebar.querySelector("a, button, input");
    if (focusable) focusable.focus();
  };

  const closeDrawer = () => {
    shell.classList.remove("pt-global-navigation--open");
    toggle.setAttribute("aria-expanded", "false");
    sidebar.removeAttribute("aria-modal");
    sidebar.removeAttribute("role");
    if (returnFocus && typeof returnFocus.focus === "function") returnFocus.focus();
    else toggle.focus();
  };

  toggle.addEventListener("click", () => {
    if (shell.classList.contains("pt-global-navigation--open")) closeDrawer();
    else openDrawer();
  });
  overlay.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && shell.classList.contains("pt-global-navigation--open")) {
      event.preventDefault();
      closeDrawer();
    }
    if (event.key !== "Tab" || !shell.classList.contains("pt-global-navigation--open")) return;
    const focusable = [...sidebar.querySelectorAll("a[href], button:not([disabled]), input:not([disabled])")];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  const makePageItem = (item) => {
    const li = document.createElement("li");
    if (item.favorite) li.className = "pt-global-navigation__favorite";
    const row = document.createElement("div");
    row.className = "pt-global-navigation__row";
    const spacer = document.createElement("span");
    spacer.className = "pt-global-navigation__spacer";
    row.append(spacer);
    const anchor = document.createElement("a");
    anchor.className = "pt-global-navigation__link";
    anchor.href = item.href;
    anchor.textContent = item.label;
    markActive(anchor, item);
    row.append(anchor);
    li.append(row);
    return li;
  };

  const renderCollection = (host, config) => {
    if (host._ptEnsureCollectionLoaded) {
      host._ptEnsureCollectionLoaded();
      return;
    }
    let page = 1;
    let query = "";
    let controller = null;
    let debounce = null;
    let ready = false;

    const status = document.createElement("p");
    status.className = "pt-global-navigation__status";
    status.textContent = "Loading…";
    const favoriteTitle = document.createElement("span");
    favoriteTitle.className = "pt-global-navigation__collection-title";
    favoriteTitle.textContent = "Favorites";
    favoriteTitle.hidden = true;
    const favorites = document.createElement("ul");
    const label = document.createElement("label");
    label.className = "pt-global-navigation__collection-label";
    const inputId = `pt-global-navigation-search-${++controlIndex}`;
    label.htmlFor = inputId;
    label.textContent = config.placeholder || "Search";
    const input = document.createElement("input");
    input.id = inputId;
    input.type = "search";
    input.placeholder = config.placeholder || "Search";
    const results = document.createElement("ul");
    const more = document.createElement("button");
    more.className = "pt-global-navigation__load-more";
    more.type = "button";
    more.textContent = "Load more";
    more.hidden = true;
    host.replaceChildren(favoriteTitle, favorites, label, input, results, more, status);

    const requestPage = async (requestedPage, append) => {
      if (controller) controller.abort();
      const activeController = new AbortController();
      controller = activeController;
      ready = false;
      const url = new URL(config.href, window.location.href);
      url.searchParams.set("q", query);
      url.searchParams.set("page", String(requestedPage));
      url.searchParams.set("page_size", "20");
      status.textContent = "Loading…";
      more.disabled = true;
      try {
        const response = await fetch(url, {headers: {Accept: "application/json"}, signal: activeController.signal});
        if (!response.ok) throw new Error(`Navigation request failed (${response.status})`);
        const payload = await response.json();
        if (!payload || !Array.isArray(payload.items) || !Array.isArray(payload.favorites)) {
          throw new Error("Navigation collection returned an invalid response");
        }
        if (controller !== activeController) return;
        favorites.replaceChildren(...payload.favorites.map(makePageItem));
        favoriteTitle.hidden = payload.favorites.length === 0;
        const itemElements = payload.items.map(makePageItem);
        if (append) results.append(...itemElements);
        else results.replaceChildren(...itemElements);
        page = requestedPage;
        more.hidden = !payload.has_more;
        more.disabled = false;
        status.textContent = payload.items.length || append ? "" : "No matching pages";
        ready = true;
      } catch (error) {
        if (controller === activeController && error.name !== "AbortError") {
          status.textContent = "Navigation is temporarily unavailable";
        }
      } finally {
        if (controller === activeController) controller = null;
      }
    };

    const ensureLoaded = () => {
      if (!ready && !controller) requestPage(1, false);
    };
    host._ptEnsureCollectionLoaded = ensureLoaded;

    input.addEventListener("input", () => {
      window.clearTimeout(debounce);
      debounce = window.setTimeout(() => {
        query = input.value.trim();
        requestPage(1, false);
      }, 250);
    });
    more.addEventListener("click", () => requestPage(page + 1, true));
    ensureLoaded();
  };

  const renderNodes = (items) => {
    const ul = document.createElement("ul");
    const ordered = [...items].sort((left, right) => Number(Boolean(right.favorite)) - Number(Boolean(left.favorite)));
    ordered.forEach((item) => {
      const li = document.createElement("li");
      if (item.favorite) li.classList.add("pt-global-navigation__favorite");
      const row = document.createElement("div");
      row.className = "pt-global-navigation__row";
      const expandable = (Array.isArray(item.children) && item.children.length > 0) || item.collection;
      let disclosure = null;
      let panel = null;
      if (expandable) {
        const panelId = `pt-global-navigation-panel-${++controlIndex}`;
        disclosure = document.createElement("button");
        disclosure.className = "pt-global-navigation__disclosure";
        disclosure.type = "button";
        disclosure.setAttribute("aria-label", `Expand ${item.label}`);
        disclosure.setAttribute("aria-expanded", "false");
        disclosure.setAttribute("aria-controls", panelId);
        row.append(disclosure);
        panel = document.createElement("div");
        panel.id = panelId;
        panel.hidden = true;
      } else {
        const spacer = document.createElement("span");
        spacer.className = "pt-global-navigation__spacer";
        row.append(spacer);
      }
      let destination = null;
      if (item.href) {
        destination = document.createElement("a");
        destination.className = "pt-global-navigation__link";
        destination.href = item.href;
        destination.textContent = item.label;
        markActive(destination, item);
      } else {
        destination = document.createElement("span");
        destination.className = "pt-global-navigation__label";
        destination.textContent = item.label;
      }
      row.append(destination);
      li.append(row);
      if (panel) {
        let collection = null;
        if (Array.isArray(item.children) && item.children.length) panel.append(renderNodes(item.children));
        if (item.collection) {
          collection = document.createElement("div");
          collection.className = "pt-global-navigation__collection";
          panel.append(collection);
        }
        const setExpanded = (expanded) => {
          disclosure.setAttribute("aria-expanded", String(expanded));
          disclosure.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${item.label}`);
          panel.hidden = !expanded;
          if (expanded && collection) renderCollection(collection, item.collection);
        };
        disclosure.addEventListener("click", () => setExpanded(disclosure.getAttribute("aria-expanded") !== "true"));
        if (destination.getAttribute && destination.getAttribute("aria-current") === "page") {
          setExpanded(true);
        }
        if (panel.querySelector('[aria-current="page"]')) setExpanded(true);
        li.append(panel);
      }
      ul.append(li);
    });
    return ul;
  };

  const renderToc = () => {
    if (pageContext.toc === false) return;
    const headings = [...document.querySelectorAll("h2, h3")].filter((heading) => !heading.closest("#pt-global-navigation-shell"));
    const entries = headings.map((heading) => {
      let id = heading.id;
      if (!id) {
        const owner = heading.closest("[id]");
        id = owner ? owner.id : "";
      }
      return {heading, id};
    }).filter((entry) => entry.id && entry.heading.textContent.trim());
    if (!entries.length) return;
    const heading = document.createElement("div");
    heading.className = "pt-global-navigation__toc-title";
    heading.textContent = "On this page";
    const ul = document.createElement("ul");
    entries.forEach((entry) => {
      const li = document.createElement("li");
      li.className = `pt-global-navigation__toc-level-${entry.heading.tagName === "H3" ? "3" : "2"}`;
      const anchor = document.createElement("a");
      anchor.href = `${window.location.pathname}${window.location.search}#${encodeURIComponent(entry.id)}`;
      anchor.textContent = entry.heading.textContent.trim();
      li.append(anchor);
      ul.append(li);
    });
    toc.replaceChildren(heading, ul);
    toc.hidden = false;
  };

  fetch(shell.dataset.navigationUrl, {headers: {Accept: "application/json"}})
    .then((response) => {
      if (!response.ok) throw new Error(`Navigation request failed (${response.status})`);
      return response.json();
    })
    .then((payload) => {
      title.textContent = payload.title || "Navigation";
      const items = Array.isArray(payload.items) ? payload.items : [];
      preferredNavigationAvailable = Boolean(
        pageContext.navigation_id && containsNavigationId(items, pageContext.navigation_id)
      );
      listRoot.replaceChildren(renderNodes(items));
    })
    .catch(() => {
      listRoot.replaceChildren();
      const status = document.createElement("p");
      status.className = "pt-global-navigation__status";
      status.textContent = "Navigation is temporarily unavailable";
      listRoot.append(status);
    });

  renderToc();
})();
