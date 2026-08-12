(() => {
  "use strict";

  const shell = document.querySelector("#pt-global-navigation-shell[data-polyptich-navigation-shell]");
  if (!shell) return;

  const listRoot = shell.querySelector("[data-pt-navigation-list]");
  const title = shell.querySelector("[data-pt-navigation-title]");
  const toggle = shell.querySelector(".pt-global-navigation__toggle");
  const overlay = shell.querySelector(".pt-global-navigation__overlay");
  const sidebar = shell.querySelector(".pt-global-navigation__sidebar");
  let mobileControls = shell.querySelector(".pt-global-navigation__mobile-controls");
  if (!mobileControls) {
    mobileControls = document.createElement("div");
    mobileControls.className = "pt-global-navigation__mobile-controls";
    toggle.before(mobileControls);
    mobileControls.append(toggle);
  }
  let tocToggle = shell.querySelector(".pt-global-navigation__toc-toggle");
  if (!tocToggle) {
    tocToggle = document.createElement("button");
    tocToggle.className = "pt-global-navigation__toc-toggle";
    tocToggle.type = "button";
    tocToggle.setAttribute("aria-controls", "pt-global-navigation-toc-sidebar");
    tocToggle.setAttribute("aria-expanded", "false");
    tocToggle.textContent = "On this page";
    tocToggle.hidden = true;
    mobileControls.append(tocToggle);
  }
  let toc = shell.querySelector("[data-pt-navigation-toc]");
  if (!toc) {
    toc = document.createElement("nav");
    toc.className = "pt-global-navigation__toc";
    toc.setAttribute("data-pt-navigation-toc", "");
  }
  let tocSidebar = shell.querySelector(".pt-global-navigation__toc-sidebar");
  if (!tocSidebar) {
    tocSidebar = document.createElement("aside");
    tocSidebar.id = "pt-global-navigation-toc-sidebar";
    tocSidebar.className = "pt-global-navigation__toc-sidebar";
    tocSidebar.setAttribute("aria-label", "On this page");
    tocSidebar.hidden = true;
    sidebar.after(tocSidebar);
  }
  tocSidebar.append(toc);
  let body = shell.querySelector(".pt-global-navigation__body");
  if (!body) {
    body = document.createElement("div");
    body.className = "pt-global-navigation__body";
    body.append(title, listRoot);
    sidebar.prepend(body);
  }
  let actionsRoot = shell.querySelector("[data-pt-navigation-actions]");
  if (!actionsRoot) {
    actionsRoot = document.createElement("div");
    actionsRoot.className = "pt-global-navigation__actions";
    actionsRoot.setAttribute("aria-label", "Workspace actions");
    actionsRoot.setAttribute("data-pt-navigation-actions", "");
    actionsRoot.hidden = true;
    sidebar.append(actionsRoot);
  }
  let contextElement = document.getElementById("pt-global-navigation-context");
  let pageContext = {navigation_id: null, toc: true};
  try {
    if (contextElement) pageContext = JSON.parse(contextElement.textContent);
  } catch (_error) {
    pageContext = {navigation_id: null, toc: true};
  }
  let controlIndex = 0;
  let returnFocus = null;
  let openDrawerName = null;
  let preferredNavigationAvailable = false;
  let navigationItems = [];
  let pageController = null;
  let navigationSequence = 0;
  let currentPageUrl = new URL(window.location.href);
  const navigationStateKey = "polyptichNavigation";
  const loadedScripts = new Set();
  const navigationScriptUrl = document.currentScript?.src || "";
  const navigationIcons = new Set([
    "agent", "tasks", "sources", "task", "overview", "evidence", "metrics", "examples",
    "releases", "release", "folder", "document",
  ]);

  const isNavigationAsset = (url) => /\/static\/polyptich-navigation\.(?:js|css)(?:[?#]|$)/.test(url);
  const isCurrentNavigationAsset = (url) => {
    const current = new URL(navigationScriptUrl || window.location.href);
    const candidate = new URL(url, window.location.href);
    const currentBase = current.pathname.replace(/polyptich-navigation\.js$/, "");
    return candidate.pathname === `${currentBase}polyptich-navigation.js`
      || candidate.pathname === `${currentBase}polyptich-navigation.css`;
  };

  for (const element of document.head.querySelectorAll("link[rel~='stylesheet'], style, meta:not([charset])")) {
    if (element.hasAttribute("data-polyptich-navigation-persistent")) continue;
    if (element.tagName === "LINK" && isCurrentNavigationAsset(element.href)) continue;
    element.dataset.polyptichPageResource = "";
  }
  for (const script of document.scripts) {
    if (!script.src || script.hasAttribute("data-polyptich-navigation-persistent") || isCurrentNavigationAsset(script.src)) continue;
    loadedScripts.add(script.src);
    script.dataset.polyptichPageScript = "";
  }

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

  const applyActiveNavigation = () => {
    preferredNavigationAvailable = Boolean(
      pageContext.navigation_id && containsNavigationId(navigationItems, pageContext.navigation_id)
    );
    const anchors = [...listRoot.querySelectorAll("a.pt-global-navigation__link")];
    anchors.forEach((anchor) => anchor.removeAttribute("aria-current"));
    let active = null;
    if (preferredNavigationAvailable) {
      active = anchors.find((anchor) => anchor.dataset.navigationId === pageContext.navigation_id) || null;
    }
    if (!active) active = anchors.find((anchor) => isActive(anchor.href)) || null;
    if (active) {
      active.setAttribute("aria-current", "page");
      for (let panel = active.parentElement; panel && panel !== listRoot; panel = panel.parentElement) {
        if (!panel.id?.startsWith("pt-global-navigation-panel-")) continue;
        panel.hidden = false;
        const disclosure = listRoot.querySelector(`[aria-controls="${CSS.escape(panel.id)}"]`);
        if (disclosure) {
          disclosure.setAttribute("aria-expanded", "true");
          disclosure.setAttribute("aria-label", disclosure.getAttribute("aria-label")?.replace(/^Expand /, "Collapse ") || "Collapse");
        }
      }
    }
  };

  const openDrawer = (name) => {
    returnFocus = document.activeElement;
    openDrawerName = name;
    shell.classList.toggle("pt-global-navigation--navigation-open", name === "navigation");
    shell.classList.toggle("pt-global-navigation--toc-open", name === "toc");
    toggle.setAttribute("aria-expanded", String(name === "navigation"));
    tocToggle.setAttribute("aria-expanded", String(name === "toc"));
    const drawer = name === "toc" ? tocSidebar : sidebar;
    drawer.setAttribute("aria-modal", "true");
    drawer.setAttribute("role", "dialog");
    const focusable = drawer.querySelector("a, button, input");
    if (focusable) focusable.focus();
  };

  const closeDrawer = () => {
    shell.classList.remove("pt-global-navigation--navigation-open", "pt-global-navigation--toc-open");
    toggle.setAttribute("aria-expanded", "false");
    tocToggle.setAttribute("aria-expanded", "false");
    sidebar.removeAttribute("aria-modal");
    sidebar.removeAttribute("role");
    tocSidebar.removeAttribute("aria-modal");
    tocSidebar.removeAttribute("role");
    openDrawerName = null;
    if (returnFocus && typeof returnFocus.focus === "function") returnFocus.focus();
    else toggle.focus();
  };

  toggle.addEventListener("click", () => {
    if (openDrawerName === "navigation") closeDrawer();
    else openDrawer("navigation");
  });
  tocToggle.addEventListener("click", () => {
    if (openDrawerName === "toc") closeDrawer();
    else openDrawer("toc");
  });
  overlay.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && openDrawerName) {
      event.preventDefault();
      closeDrawer();
    }
    if (event.key !== "Tab" || !openDrawerName) return;
    const drawer = openDrawerName === "toc" ? tocSidebar : sidebar;
    const focusable = [...drawer.querySelectorAll("a[href], button:not([disabled]), input:not([disabled])")];
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

  const isLocalUrl = (value) => {
    if (typeof value !== "string" || !value || value.length > 2048 || value.includes("\\")) return false;
    try {
      return new URL(value, window.location.href).origin === window.location.origin;
    } catch (_error) {
      return false;
    }
  };

  const validateCollectionConfig = (value) => value
    && typeof value === "object"
    && Object.keys(value).every((key) => ["type", "href", "placeholder"].includes(key))
    && ["directory", "endpoint"].includes(value.type)
    && isLocalUrl(value.href)
    && (!("placeholder" in value) || (
      typeof value.placeholder === "string"
      && value.placeholder.length > 0
      && value.placeholder.length <= 200
    ));

  const validateNavigationNode = (item, depth = 0) => {
    if (!item || typeof item !== "object" || depth > 32) return false;
    if (!Object.keys(item).every((key) => [
      "id", "label", "type", "href", "children", "favorite", "collection", "icon",
    ].includes(key))) return false;
    if (typeof item.id !== "string" || !/^[A-Za-z][A-Za-z0-9_.:-]*$/.test(item.id)) return false;
    if (typeof item.label !== "string" || !item.label.trim() || item.label.length > 200) return false;
    if (!["section", "page", "collection"].includes(item.type)) return false;
    if ("icon" in item && !navigationIcons.has(item.icon)) return false;
    if ("favorite" in item && typeof item.favorite !== "boolean") return false;
    if ("href" in item && !isLocalUrl(item.href)) return false;
    if (item.type === "page" && !isLocalUrl(item.href)) return false;
    if ((item.type === "collection") !== ("collection" in item)) return false;
    if ("collection" in item && !validateCollectionConfig(item.collection)) return false;
    if ("children" in item && (!Array.isArray(item.children)
      || !item.children.every((child) => validateNavigationNode(child, depth + 1)))) return false;
    return true;
  };

  const validateCollectionPayload = (payload) => {
    if (!payload || payload.schema !== "polyptich.www.navigation.collection" || payload.schema_version !== 1) return false;
    if (!Object.keys(payload).every((key) => [
      "schema", "schema_version", "items", "favorites", "page", "page_size", "has_more", "total",
      "total_lower_bound", "truncated",
    ].includes(key))) return false;
    if (!Array.isArray(payload.items) || !payload.items.every((item) => validateNavigationNode(item))) return false;
    if (!Array.isArray(payload.favorites) || !payload.favorites.every((item) => validateNavigationNode(item))) return false;
    return Number.isInteger(payload.page) && payload.page > 0
      && Number.isInteger(payload.page_size) && payload.page_size > 0
      && (payload.total === null || Number.isInteger(payload.total) && payload.total >= 0)
      && (!("total_lower_bound" in payload)
        || Number.isInteger(payload.total_lower_bound) && payload.total_lower_bound >= 0)
      && (!("truncated" in payload) || typeof payload.truncated === "boolean")
      && typeof payload.has_more === "boolean";
  };

  const makeIcon = (icon) => {
    if (!navigationIcons.has(icon)) return null;
    const element = document.createElement("span");
    element.className = "pt-global-navigation__icon";
    element.dataset.icon = icon;
    element.setAttribute("aria-hidden", "true");
    return element;
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
    let total = 0;
    const pageSize = 20;

    const status = document.createElement("p");
    status.className = "pt-global-navigation__status";
    status.textContent = "Loading…";
    const favoriteTitle = document.createElement("span");
    favoriteTitle.className = "pt-global-navigation__collection-title";
    favoriteTitle.textContent = "Favorites";
    favoriteTitle.hidden = true;
    const favorites = document.createElement("ul");
    let label = null;
    let input = null;
    if (config.placeholder) {
      label = document.createElement("label");
      label.className = "pt-global-navigation__collection-label";
      const inputId = `pt-global-navigation-search-${++controlIndex}`;
      label.htmlFor = inputId;
      label.textContent = config.placeholder;
      input = document.createElement("input");
      input.id = inputId;
      input.type = "search";
      input.placeholder = config.placeholder;
    }
    const results = document.createElement("ul");
    const toolbar = document.createElement("div");
    toolbar.className = "pt-global-navigation__collection-toolbar";
    const previous = document.createElement("button");
    previous.type = "button";
    previous.textContent = "Previous";
    const pageStatus = document.createElement("span");
    pageStatus.className = "pt-global-navigation__page-status";
    const next = document.createElement("button");
    next.type = "button";
    next.textContent = "Next";
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.className = "pt-global-navigation__refresh";
    refresh.textContent = "Refresh";
    toolbar.append(previous, pageStatus, next, refresh);
    toolbar.hidden = true;
    host.replaceChildren(
      favoriteTitle,
      favorites,
      ...(label && input ? [label, input] : []),
      results,
      toolbar,
      status,
    );

    const requestPage = async (requestedPage) => {
      if (controller) controller.abort();
      const activeController = new AbortController();
      controller = activeController;
      ready = false;
      const url = new URL(config.href, window.location.href);
      if (config.placeholder) url.searchParams.set("q", query);
      url.searchParams.set("page", String(requestedPage));
      url.searchParams.set("page_size", String(pageSize));
      status.textContent = "Loading…";
      previous.disabled = true;
      next.disabled = true;
      refresh.disabled = true;
      try {
        const response = await fetch(url, {headers: {Accept: "application/json"}, signal: activeController.signal});
        if (!response.ok) throw new Error(`Navigation request failed (${response.status})`);
        const payload = await response.json();
        if (!validateCollectionPayload(payload)) {
          throw new Error("Navigation collection returned an invalid response");
        }
        if (controller !== activeController) return;
        favorites.replaceChildren(...renderNodes(payload.favorites, 1).children);
        favoriteTitle.hidden = payload.favorites.length === 0;
        results.replaceChildren(...renderNodes(payload.items, 1).children);
        page = payload.page;
        total = payload.total;
        const pages = Number.isInteger(total) ? Math.max(1, Math.ceil(total / payload.page_size)) : null;
        toolbar.hidden = false;
        previous.disabled = page <= 1;
        next.disabled = !payload.has_more;
        refresh.disabled = false;
        pageStatus.textContent = pages === null ? `Page ${page}` : `Page ${page} of ${pages}`;
        const reportedTotal = Number.isInteger(total) ? total : payload.total_lower_bound;
        status.textContent = payload.items.length
          ? `${reportedTotal}${Number.isInteger(total) ? "" : "+"} item${reportedTotal === 1 ? "" : "s"}`
          : "No matching pages";
        ready = true;
      } catch (error) {
        if (controller === activeController && error.name !== "AbortError") {
          status.textContent = "Navigation is temporarily unavailable";
          previous.disabled = page <= 1;
          next.disabled = page * pageSize >= total;
          refresh.disabled = false;
        }
      } finally {
        if (controller === activeController) controller = null;
      }
    };

    const ensureLoaded = () => {
      if (!ready && !controller) requestPage(1);
    };
    host._ptEnsureCollectionLoaded = ensureLoaded;

    if (input) {
      input.addEventListener("input", () => {
        window.clearTimeout(debounce);
        debounce = window.setTimeout(() => {
          query = input.value.trim();
          requestPage(1);
        }, 250);
      });
    }
    previous.addEventListener("click", () => requestPage(Math.max(1, page - 1)));
    next.addEventListener("click", () => requestPage(page + 1));
    refresh.addEventListener("click", () => requestPage(page));
    ensureLoaded();
  };

  const renderNodes = (items, depth = 0) => {
    const ul = document.createElement("ul");
    ul.className = `pt-global-navigation__level pt-global-navigation__level--${Math.min(depth, 6)}`;
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
      const icon = makeIcon(item.icon);
      if (icon) {
        if (expandable) {
          const iconToggle = document.createElement("button");
          iconToggle.className = "pt-global-navigation__icon-toggle";
          iconToggle.type = "button";
          iconToggle.setAttribute("aria-label", `Expand ${item.label}`);
          iconToggle.append(icon);
          row.append(iconToggle);
          icon._ptToggle = iconToggle;
        } else {
          row.append(icon);
        }
      }
      let destination = null;
      if (item.href) {
        destination = document.createElement("a");
        destination.className = "pt-global-navigation__link";
        destination.href = item.href;
        destination.textContent = item.label;
        destination.dataset.navigationId = item.id;
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
        if (Array.isArray(item.children) && item.children.length) {
          panel.append(renderNodes(item.children, depth + 1));
        }
        if (item.collection) {
          collection = document.createElement("div");
          collection.className = "pt-global-navigation__collection";
          panel.append(collection);
        }
        const setExpanded = (expanded) => {
          disclosure.setAttribute("aria-expanded", String(expanded));
          disclosure.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${item.label}`);
          if (icon?._ptToggle) {
            icon._ptToggle.setAttribute("aria-expanded", String(expanded));
            icon._ptToggle.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${item.label}`);
          }
          panel.hidden = !expanded;
          if (expanded && collection) renderCollection(collection, item.collection);
        };
        disclosure.addEventListener("click", () => setExpanded(disclosure.getAttribute("aria-expanded") !== "true"));
        if (icon?._ptToggle) {
          icon._ptToggle.addEventListener("click", () => setExpanded(disclosure.getAttribute("aria-expanded") !== "true"));
        }
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
    toc.replaceChildren();
    toc.hidden = true;
    tocSidebar.hidden = true;
    tocToggle.hidden = true;
    document.body.removeAttribute("data-polyptich-toc-visible");
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
    tocSidebar.hidden = false;
    tocToggle.hidden = false;
    document.body.setAttribute("data-polyptich-toc-visible", "");
  };

  const pageState = (url, scrollX = window.scrollX, scrollY = window.scrollY) => ({
    ...(history.state && typeof history.state === "object" ? history.state : {}),
    [navigationStateKey]: {url: String(url), scrollX, scrollY},
  });

  const rememberScroll = () => {
    history.replaceState(pageState(window.location.href), "", window.location.href);
  };

  const absoluteResourceUrl = (element, attribute, baseUrl) => {
    const value = element.getAttribute(attribute);
    return value ? new URL(value, baseUrl).href : "";
  };

  const comparableResourceUrl = (element, attribute, baseUrl) => {
    const url = absoluteResourceUrl(element, attribute, baseUrl);
    if (!url) return "";
    const parsed = new URL(url);
    if (isNavigationAsset(parsed.href) || parsed.pathname.endsWith("/static/polyptich-www.css")) {
      return `${parsed.origin}${parsed.pathname}${parsed.search}`;
    }
    return parsed.href;
  };

  const resourceKey = (element, baseUrl) => {
    if (element.tagName === "LINK") return `link:${comparableResourceUrl(element, "href", baseUrl)}`;
    if (element.tagName === "STYLE") return `style:${element.textContent}`;
    if (element.tagName === "META") return `meta:${element.getAttribute("name") || element.getAttribute("property") || ""}`;
    return `${element.tagName}:${element.outerHTML}`;
  };

  const copyAttributes = (source, target, baseUrl) => {
    for (const attribute of source.attributes) {
      let value = attribute.value;
      if (attribute.name === "src" || attribute.name === "href") value = new URL(value, baseUrl).href;
      target.setAttribute(attribute.name, value);
    }
  };

  const resolveMainUrls = (main, baseUrl) => {
    const attributes = ["src", "href", "poster"];
    main.querySelectorAll("[src], [href], [poster], [srcset]").forEach((element) => {
      for (const attribute of attributes) {
        const value = element.getAttribute(attribute);
        if (value) element.setAttribute(attribute, new URL(value, baseUrl).href);
      }
      const srcset = element.getAttribute("srcset");
      if (srcset) {
        element.setAttribute("srcset", srcset.split(",").map((candidate) => {
          const match = candidate.trim().match(/^(\S+)(\s+.*)?$/);
          return match ? `${new URL(match[1], baseUrl).href}${match[2] || ""}` : candidate;
        }).join(", "));
      }
    });
  };

  const parsePage = (html, responseUrl) => {
    const documentNode = new DOMParser().parseFromString(html, "text/html");
    const host = documentNode.body;
    if (!host.matches("[data-polyptich-navigation-host]")) {
      throw new Error("Destination is not a managed WorkspacePage");
    }
    if (host.dataset.polyptichPageVersion && host.dataset.polyptichPageVersion !== "1") {
      throw new Error("Destination WorkspacePage protocol is unsupported");
    }
    if (documentNode.querySelector("base")) throw new Error("Managed pages cannot define a base URL");
    const mains = documentNode.querySelectorAll("main#pt-global-navigation-main");
    const contexts = documentNode.querySelectorAll("#pt-global-navigation-context");
    if (mains.length !== 1 || contexts.length !== 1) throw new Error("Destination has an invalid workspace shell");
    let context;
    try {
      context = JSON.parse(contexts[0].textContent);
    } catch (_error) {
      throw new Error("Destination page context is invalid");
    }
    if (context?.schema !== "polyptich.www.page-context" || context.schema_version !== 1) {
      throw new Error("Destination page context is unsupported");
    }
    const inlineScripts = [...documentNode.scripts].filter((script) =>
      !script.src && (!script.type || ["text/javascript", "application/javascript", "module"].includes(script.type))
    );
    if (inlineScripts.length) throw new Error("Managed pages cannot use executable inline scripts");
    return {
      documentNode,
      main: mains[0],
      contextElement: contexts[0],
      context,
      title: documentNode.title,
      responseUrl,
      resources: [...documentNode.head.querySelectorAll("link[rel~='stylesheet'], style, meta:not([charset])")]
        .filter((element) =>
          !element.hasAttribute("data-polyptich-navigation-persistent")
          && (element.tagName !== "LINK" || !isCurrentNavigationAsset(absoluteResourceUrl(element, "href", responseUrl)))
        ),
      scripts: [...documentNode.scripts].filter((script) =>
        script.src
        && !script.hasAttribute("data-polyptich-navigation-persistent")
        && absoluteResourceUrl(script, "src", responseUrl) !== navigationScriptUrl
        && !isCurrentNavigationAsset(absoluteResourceUrl(script, "src", responseUrl))
      ),
    };
  };

  const loadStylesheet = (source, baseUrl) => new Promise((resolve, reject) => {
    const link = document.createElement("link");
    copyAttributes(source, link, baseUrl);
    link.dataset.polyptichPageResource = "";
    link.addEventListener("load", () => resolve(link), {once: true});
    link.addEventListener("error", () => reject(new Error(`Could not load ${link.href}`)), {once: true});
    document.head.append(link);
  });

  const prepareResources = async (page) => {
    const existing = new Map(
      [...document.head.querySelectorAll("[data-polyptich-page-resource]")]
        .map((element) => [resourceKey(element, window.location.href), element])
    );
    const desiredKeys = new Set();
    const additions = [];
    try {
      for (const source of page.resources) {
        const key = resourceKey(source, page.responseUrl);
        desiredKeys.add(key);
        if (existing.has(key)) continue;
        let element;
        if (source.tagName === "LINK") element = await loadStylesheet(source, page.responseUrl);
        else {
          element = document.createElement(source.tagName.toLowerCase());
          copyAttributes(source, element, page.responseUrl);
          element.textContent = source.textContent;
          element.dataset.polyptichPageResource = "";
          document.head.append(element);
        }
        additions.push(element);
      }
    } catch (error) {
      additions.forEach((element) => element.remove());
      throw error;
    }
    return {
      additions,
      obsolete: [...existing].filter(([key]) => !desiredKeys.has(key)).map(([, element]) => element),
    };
  };

  const executeScripts = async (page) => {
    for (const source of page.scripts) {
      const src = absoluteResourceUrl(source, "src", page.responseUrl);
      if (!src) throw new Error("Managed page script URL is invalid");
      if (source.dataset.polyptichScript === "once" && loadedScripts.has(src)) continue;
      const script = document.createElement("script");
      copyAttributes(source, script, page.responseUrl);
      script.removeAttribute("nonce");
      script.removeAttribute("defer");
      script.async = false;
      script.dataset.polyptichPageScript = "";
      await new Promise((resolve, reject) => {
        script.addEventListener("load", resolve, {once: true});
        script.addEventListener("error", () => reject(new Error(`Could not load ${src}`)), {once: true});
        document.body.append(script);
      });
      loadedScripts.add(src);
    }
  };

  const verifyScripts = async (page) => {
    for (const source of page.scripts) {
      const src = absoluteResourceUrl(source, "src", page.responseUrl);
      if (!src || loadedScripts.has(src)) continue;
      const url = new URL(src);
      if (url.origin !== window.location.origin) continue;
      const response = await fetch(url, {credentials: "same-origin"});
      if (!response.ok) throw new Error(`Could not load ${src}`);
    }
  };

  const restorePosition = (url, scrollPosition) => {
    if (url.hash) {
      const target = document.getElementById(decodeURIComponent(url.hash.slice(1)));
      if (target) {
        target.scrollIntoView();
        return;
      }
    }
    if (scrollPosition) window.scrollTo(scrollPosition.x, scrollPosition.y);
    else window.scrollTo(0, 0);
  };

  const commitPage = async (page, requestedUrl, {historyMode, scrollPosition}) => {
    const prepared = await prepareResources(page);
    try {
      await verifyScripts(page);
    } catch (error) {
      prepared.additions.forEach((element) => element.remove());
      throw error;
    }
    const oldMain = document.getElementById("pt-global-navigation-main");
    const oldContext = contextElement;
    const oldScripts = [...document.querySelectorAll("script[data-polyptich-page-script]")];
    let didSwap = false;
    try {
      window.dispatchEvent(new CustomEvent("polyptich:before-page-swap", {detail: {url: page.responseUrl}}));
      const importedMain = document.importNode(page.main, true);
      resolveMainUrls(importedMain, page.responseUrl);
      importedMain.querySelectorAll("script[src]").forEach((script) => script.remove());
      const importedContext = document.importNode(page.contextElement, true);
      oldMain.replaceWith(importedMain);
      oldContext.replaceWith(importedContext);
      didSwap = true;
      contextElement = importedContext;
      pageContext = page.context;
      document.title = page.title;
      for (const element of prepared.obsolete) element.remove();
      for (const script of oldScripts) script.remove();
      document.body.className = page.documentNode.body.className;
      for (const attribute of [...document.body.attributes]) {
        if (attribute.name.startsWith("data-") && attribute.name !== "data-polyptich-navigation-host") {
          document.body.removeAttribute(attribute.name);
        }
      }
      for (const attribute of page.documentNode.body.attributes) {
        if (attribute.name !== "class") document.body.setAttribute(attribute.name, attribute.value);
      }
      const finalUrl = new URL(page.responseUrl);
      finalUrl.hash = new URL(requestedUrl).hash;
      currentPageUrl = finalUrl;
      if (historyMode === "push") history.pushState(pageState(finalUrl, 0, 0), "", finalUrl);
      else if (historyMode === "replace") history.replaceState(pageState(finalUrl, 0, 0), "", finalUrl);
      applyActiveNavigation();
      renderToc();
      if (openDrawerName) closeDrawer();
      restorePosition(finalUrl, scrollPosition);
      if (!scrollPosition && !finalUrl.hash) importedMain.focus({preventScroll: true});
      await executeScripts(page);
      window.dispatchEvent(new CustomEvent("polyptich:page-swap", {detail: {url: finalUrl.href}}));
      return true;
    } catch (error) {
      prepared.additions.forEach((element) => element.remove());
      if (didSwap) error.polyptichPageSwapped = true;
      throw error;
    }
  };

  const navigate = async (value, options = {}) => {
    const url = new URL(value, window.location.href);
    if (url.origin !== window.location.origin) {
      window.location.assign(url);
      return false;
    }
    if (url.hash && url.pathname === currentPageUrl.pathname && url.search === currentPageUrl.search) {
      if (options.historyMode !== "pop" && url.href !== window.location.href) {
        rememberScroll();
        history.pushState(pageState(url, 0, 0), "", url);
      }
      restorePosition(url, options.scrollPosition || null);
      return true;
    }
    if (options.historyMode !== "pop" && url.pathname === window.location.pathname && url.search === window.location.search) {
      if (url.hash !== window.location.hash) {
        rememberScroll();
        history.pushState(pageState(url, 0, 0), "", url);
        restorePosition(url);
      }
      return true;
    }
    if (options.historyMode === "pop" && url.pathname === currentPageUrl.pathname && url.search === currentPageUrl.search) {
      restorePosition(url, options.scrollPosition || null);
      return true;
    }
    if (options.historyMode !== "pop") rememberScroll();
    if (pageController) pageController.abort();
    const controller = new AbortController();
    pageController = controller;
    const sequence = ++navigationSequence;
    let swapped = false;
    shell.classList.add("pt-global-navigation--loading");
    try {
      const timeout = window.setTimeout(() => controller.abort(), 20000);
      let response;
      try {
        response = await fetch(url, {
          headers: {Accept: "text/html", "X-Polyptich-Navigation": "partial"},
          credentials: "same-origin",
          signal: controller.signal,
        });
      } finally {
        window.clearTimeout(timeout);
      }
      if (!response.ok || response.redirected && new URL(response.url).origin !== window.location.origin) {
        throw new Error(`Navigation request failed (${response.status})`);
      }
      const contentType = response.headers.get("Content-Type") || "";
      const disposition = response.headers.get("Content-Disposition") || "";
      if (!contentType.toLowerCase().includes("text/html") || /attachment/i.test(disposition)) {
        throw new Error("Destination is not an inline HTML page");
      }
      const page = parsePage(await response.text(), response.url);
      if (controller.signal.aborted || sequence !== navigationSequence) return false;
      swapped = await commitPage(page, url, {
        historyMode: options.historyMode || "push",
        scrollPosition: options.scrollPosition || null,
      });
      return true;
    } catch (error) {
      if (error.name === "AbortError" && sequence !== navigationSequence) return false;
      if (swapped || error.polyptichPageSwapped || options.historyMode === "pop") window.location.reload();
      else window.location.assign(url);
      return false;
    } finally {
      if (pageController === controller) pageController = null;
      if (sequence === navigationSequence) shell.classList.remove("pt-global-navigation--loading");
    }
  };

  window.polyptichNavigate = (url) => navigate(url);
  history.scrollRestoration = "manual";
  if (!history.state?.[navigationStateKey]) {
    history.replaceState(pageState(window.location.href), "", window.location.href);
  }

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!anchor || anchor.hasAttribute("download") || anchor.dataset.polyptichReload != null) return;
    if (anchor.target && anchor.target.toLowerCase() !== "_self") return;
    const url = new URL(anchor.href, window.location.href);
    if (!["http:", "https:"].includes(url.protocol) || url.origin !== window.location.origin) return;
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash === window.location.hash) return;
    event.preventDefault();
    navigate(url);
  });

  window.addEventListener("popstate", (event) => {
    const state = event.state?.[navigationStateKey];
    const position = state ? {x: Number(state.scrollX || 0), y: Number(state.scrollY || 0)} : null;
    navigate(window.location.href, {historyMode: "pop", scrollPosition: position});
  });

  const waitForService = async (action, button, status) => {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      try {
        const healthUrl = new URL(action.health_url, window.location.href);
        healthUrl.searchParams.set("restart", String(Date.now()));
        const response = await fetch(healthUrl, {cache: "no-store"});
        if (response.ok) {
          window.location.reload();
          return;
        }
      } catch (_error) {
        // The service is expected to be briefly unreachable while it restarts.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    status.textContent = "Server has not returned; reload manually.";
    button.textContent = action.label;
    button.disabled = false;
  };

  const makeServiceRestartAction = (action) => {
    const host = document.createElement("div");
    host.className = "pt-global-navigation__action";
    const button = document.createElement("button");
    button.className = "pt-global-navigation__action-button";
    button.type = "button";
    button.textContent = action.label;
    const status = document.createElement("span");
    status.className = "pt-global-navigation__action-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    button.addEventListener("click", async () => {
      if (!window.confirm("Restart the web server? Active agent runs will continue.")) return;
      button.disabled = true;
      button.textContent = "Restarting...";
      status.textContent = "Authorizing restart";
      try {
        const sessionResponse = await fetch(action.session_url, {cache: "no-store"});
        const sessionPayload = await sessionResponse.json();
        const csrfToken = sessionPayload?.data?.csrf_token;
        if (!sessionResponse.ok || !csrfToken) throw new Error("Could not authorize restart");
        const response = await fetch(action.restart_url, {
          method: "POST",
          cache: "no-store",
          headers: {"Content-Type": "application/json", "X-Iomix-CSRF": csrfToken},
          body: "{}",
        });
        if (!response.ok) throw new Error(`Restart request failed (${response.status})`);
        status.textContent = "Waiting for server";
        window.setTimeout(() => waitForService(action, button, status), 1200);
      } catch (error) {
        button.textContent = action.label;
        button.disabled = false;
        status.textContent = error.message;
      }
    });
    host.append(button, status);
    return host;
  };

  const renderActions = (actions) => {
    const rendered = actions.flatMap((action) => {
      if (action?.type === "service_restart") return [makeServiceRestartAction(action)];
      return [];
    });
    actionsRoot.replaceChildren(...rendered);
    actionsRoot.hidden = rendered.length === 0;
  };

  fetch(shell.dataset.navigationUrl, {headers: {Accept: "application/json"}})
    .then((response) => {
      if (!response.ok) throw new Error(`Navigation request failed (${response.status})`);
      return response.json();
    })
    .then((payload) => {
      title.textContent = payload.title || "Navigation";
      if (payload?.schema !== "polyptich.www.navigation" || payload.schema_version !== 1
        || !Array.isArray(payload.items)
        || !payload.items.every((item) => validateNavigationNode(item))) {
        throw new Error("Navigation returned an invalid response");
      }
      navigationItems = payload.items;
      preferredNavigationAvailable = Boolean(
        pageContext.navigation_id && containsNavigationId(navigationItems, pageContext.navigation_id)
      );
      listRoot.replaceChildren(renderNodes(navigationItems));
      applyActiveNavigation();
      renderActions(Array.isArray(payload.actions) ? payload.actions : []);
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
