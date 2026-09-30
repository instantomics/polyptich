(function () {
  "use strict";

  const renderedPlotly = new Set();
  const renderedTables = new Set();
  const requestControllers = new Set();
  const cleanups = new Set();
  const tableUrlAppliers = new Set();
  const reportScriptUrl = document.currentScript?.src || "";
  let tableCorePromise = null;
  let plotlyPromise = null;
  let active = true;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function parseJson(value, fallback) {
    if (!value) return fallback;
    try {
      return JSON.parse(value);
    } catch (_error) {
      return fallback;
    }
  }

  function isVisible(node) {
    return !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
  }

  function decodeTarget(value) {
    try {
      return decodeURIComponent(value);
    } catch (_error) {
      return value;
    }
  }

  function parseFragment(value = window.location.hash) {
    const fragment = String(value || "").replace(/^#/, "");
    const separator = fragment.indexOf("?");
    if (separator >= 0) {
      return {
        target: decodeTarget(fragment.slice(0, separator)),
        params: new URLSearchParams(fragment.slice(separator + 1)),
      };
    }
    if (fragment.includes("=")) {
      return { target: "", params: new URLSearchParams(fragment) };
    }
    return { target: decodeTarget(fragment), params: new URLSearchParams() };
  }

  function formatFragment(target, params) {
    const encoded = target ? encodeURIComponent(target) : "";
    const state = new URLSearchParams(params).toString();
    if (encoded && state) return "#" + encoded + "?" + state;
    if (encoded) return "#" + encoded;
    return state ? "#" + state : "";
  }

  function updateFragment(update, target) {
    const fragment = parseFragment();
    update(fragment.params);
    const hash = formatFragment(target === undefined ? fragment.target : target, fragment.params);
    history.replaceState(history.state, "", window.location.pathname + window.location.search + hash);
  }

  function reportLocation() {
    const scriptPath = reportScriptUrl ? new URL(reportScriptUrl, window.location.href).pathname : "";
    const suffix = "/static/polyptich-www.js";
    const prefix = scriptPath.endsWith(suffix) ? scriptPath.slice(0, -suffix.length) : "";
    if (!window.location.pathname.startsWith(prefix + "/")) return { prefix, path: "" };
    return {
      prefix,
      path: decodeURIComponent(window.location.pathname.slice(prefix.length)).replace(/^\/+|\/+$/g, ""),
    };
  }

  function dataUrl(id) {
    const location = reportLocation();
    const path = encodeURIComponent(location.path).replace(/%2F/g, "/");
    return location.prefix + "/report-data/" + path + "/" + encodeURIComponent(id);
  }

  function downloadUrl(id, format, params) {
    const location = reportLocation();
    const path = encodeURIComponent(location.path).replace(/%2F/g, "/");
    const query = params && params.toString() ? "?" + params.toString() : "";
    return location.prefix + "/report-download/" + path + "/" + encodeURIComponent(id)
      + "." + format + query;
  }

  async function fetchResource(url, options = {}) {
    const controller = options.controller || new AbortController();
    requestControllers.add(controller);
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) {
        let message = "Request failed (" + response.status + ")";
        try {
          const payload = await response.json();
          if (payload.message) message = payload.message;
        } catch (_error) {
          // The shared server error pages are HTML.
        }
        throw new Error(message);
      }
      return response;
    } finally {
      requestControllers.delete(controller);
    }
  }

  async function fetchJson(url, options) {
    const response = await fetchResource(url, options);
    return response.json();
  }

  function dispatchStateChange() {
    window.dispatchEvent(new CustomEvent("polyptich:report-state-change"));
  }

  function copyText(value, button) {
    const done = () => {
      if (!button) return;
      const original = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => { button.textContent = original; }, 1200);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value).then(done).catch(() => {});
      return;
    }
    const input = element("textarea");
    input.value = value;
    document.body.append(input);
    input.select();
    document.execCommand("copy");
    input.remove();
    done();
  }

  function componentUrl(id) {
    const fragment = parseFragment();
    return window.location.origin + window.location.pathname + window.location.search
      + formatFragment(id, fragment.params);
  }

  function setTab(wrapper, tabId, focus, writeState) {
    let activeButton = null;
    wrapper.querySelectorAll(":scope > .tab-buttons > .tab-button").forEach((button) => {
      const selected = button.dataset.tab === tabId;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", selected ? "true" : "false");
      button.tabIndex = selected ? 0 : -1;
      if (selected) activeButton = button;
    });
    wrapper.querySelectorAll(":scope > .tab-panels > .tab-panel").forEach((panel) => {
      const selected = panel.id === tabId;
      panel.classList.toggle("active", selected);
      panel.hidden = !selected;
    });
    if (writeState) {
      updateFragment((params) => params.set("tab-" + wrapper.id, tabId));
    }
    if (focus && activeButton) activeButton.focus();
    queueRender(wrapper);
    dispatchStateChange();
  }

  function applyTabState(params = parseFragment().params) {
    document.querySelectorAll(".tabs[id]").forEach((wrapper) => {
      const buttons = Array.from(
        wrapper.querySelectorAll(":scope > .tab-buttons > .tab-button")
      );
      const requested = params.get("tab-" + wrapper.id);
      const selected = buttons.some((button) => button.dataset.tab === requested)
        ? requested
        : buttons[0]?.dataset.tab;
      if (selected) setTab(wrapper, selected, false, false);
    });
  }

  function initialiseTabs() {
    applyTabState();
    document.querySelectorAll(".tabs[id]").forEach((wrapper) => {
      const buttons = Array.from(
        wrapper.querySelectorAll(":scope > .tab-buttons > .tab-button")
      );
      buttons.forEach((button) => {
        button.addEventListener("click", () => setTab(wrapper, button.dataset.tab, false, true));
        button.addEventListener("keydown", (event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          let index;
          if (event.key === "Home") index = 0;
          else if (event.key === "End") index = buttons.length - 1;
          else {
            const offset = event.key === "ArrowRight" ? 1 : -1;
            index = (buttons.indexOf(button) + offset + buttons.length) % buttons.length;
          }
          if (buttons[index]) setTab(wrapper, buttons[index].dataset.tab, true, true);
        });
      });
    });
  }

  function persistOpenDetails() {
    const ids = Array.from(document.querySelectorAll(".component.collapsible[id][open]"))
      .map((details) => details.id);
    updateFragment((params) => {
      params.set("open", ids.join(","));
    });
    dispatchStateChange();
  }

  function applyDetailsState(params = parseFragment().params) {
    if (!params.has("open")) return;
    const open = new Set(params.get("open").split(",").filter(Boolean));
    document.querySelectorAll(".component.collapsible[id]").forEach((details) => {
      details.open = open.has(details.id);
    });
  }

  function initialiseDetails() {
    applyDetailsState();
    document.querySelectorAll(".component.collapsible[id]").forEach((details) => {
      details.addEventListener("toggle", () => {
        if (details.open) queueRender(details);
        persistOpenDetails();
      });
    });
  }

  function revealTarget(event) {
    const target = event.detail?.element || document.getElementById(event.detail?.target || "");
    if (!target) return;
    let parent = target.parentElement;
    while (parent) {
      if (parent.matches("details") && !parent.open) parent.open = true;
      if (parent.matches(".tab-panel") && parent.hidden) {
        const tabs = parent.closest(".tabs[id]");
        if (tabs) setTab(tabs, parent.id, false, false);
      }
      parent = parent.parentElement;
    }
    queueRender(target.closest(".component") || target);
  }

  function initialisePermalinks() {
    document.querySelectorAll(".report .anchor-link").forEach((anchor) => {
      anchor.addEventListener("click", (event) => {
        const id = anchor.closest("[id]")?.id;
        if (!id) return;
        event.preventDefault();
        const fragment = parseFragment();
        const hash = formatFragment(id, fragment.params);
        history.pushState(history.state, "", window.location.pathname + window.location.search + hash);
        document.getElementById(id)?.scrollIntoView();
      });
    });
  }

  function initialiseAutoBreadcrumbs() {
    const root = document.querySelector("[data-auto-breadcrumbs]");
    if (!root) return;
    const location = reportLocation();
    const parts = location.path.split("/").filter(Boolean);
    if (!parts.length) return;
    const list = element("ol");
    parts.forEach((part, index) => {
      const item = element("li");
      const label = decodeTarget(part).replace(/[-_]+/g, " ");
      if (index === parts.length - 1) {
        item.textContent = document.querySelector(".report-header h1")?.childNodes[0]?.textContent
          || label;
        item.setAttribute("aria-current", "page");
      } else {
        const link = element("a", "", label);
        link.href = location.prefix + "/" + parts.slice(0, index + 1)
          .map(encodeURIComponent).join("/") + "/";
        item.append(link);
      }
      list.append(item);
    });
    root.append(list);
  }

  function initialiseReportTools() {
    const actions = document.querySelectorAll("[data-report-action]");
    const run = async (action, button) => {
      if (action === "expand" || action === "collapse") {
        const open = action === "expand";
        document.querySelectorAll(".component.collapsible, .www-panel > details").forEach(
          (details) => { details.open = open; }
        );
        if (open) queueRender(document);
        persistOpenDetails();
      } else if (action === "copy") {
        copyText(window.location.href, button);
      } else if (action === "print") {
        beforePrint();
        await waitForReportReady();
        window.print();
      } else if (action === "top") {
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
      }
    };
    actions.forEach((button) => {
      button.addEventListener("click", () => run(button.dataset.reportAction, button));
    });
    document.querySelectorAll("[data-copy-component-link]").forEach((button) => {
      button.addEventListener("click", () => {
        copyText(componentUrl(button.dataset.copyComponentLink), button);
      });
    });

    const backToTop = document.querySelector(".report-back-to-top");
    const onScroll = () => {
      if (backToTop) backToTop.hidden = window.scrollY < 700;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    cleanups.add(() => window.removeEventListener("scroll", onScroll));
    onScroll();

    const mobileRoot = document.querySelector("[data-polyptich-mobile-page-actions]");
    if (mobileRoot) {
      [
        ["expand", "+", "Expand report sections"],
        ["top", "^", "Back to top"],
      ].forEach(([action, text, label]) => {
        const button = element("button", "pt-global-navigation__page-action", text);
        button.type = "button";
        button.setAttribute("aria-label", label);
        button.title = label;
        button.addEventListener("click", () => run(action, button));
        mobileRoot.append(button);
      });
      cleanups.add(() => mobileRoot.replaceChildren());
    }
  }

  let printState = null;
  function beforePrint() {
    if (printState) return;
    printState = {
      details: Array.from(
        document.querySelectorAll(".component.collapsible, .www-panel > details")
      ).map((details) => [details, details.open]),
      panels: Array.from(document.querySelectorAll(".tab-panel"))
        .map((panel) => [panel, panel.hidden, panel.classList.contains("active")]),
    };
    printState.details.forEach(([details]) => { details.open = true; });
    printState.panels.forEach(([panel]) => {
      panel.hidden = false;
      panel.classList.add("active");
    });
    renderVisiblePlotly(document);
    renderVisibleTables(document);
    queueRender(document);
  }

  function afterPrint() {
    if (!printState) return;
    printState.details.forEach(([details, open]) => { details.open = open; });
    printState.panels.forEach(([panel, hidden, wasActive]) => {
      panel.hidden = hidden;
      panel.classList.toggle("active", wasActive);
    });
    printState = null;
  }

  async function waitForReportReady() {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      const loading = document.querySelector('[aria-busy="true"], .plot-status');
      if (!loading) return;
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    }
  }

  function plotDialog() {
    let dialog = document.querySelector(".plot-dialog");
    if (dialog) return dialog;
    dialog = element("dialog", "plot-dialog");
    const close = element("button", "plot-dialog-close", "Close");
    close.type = "button";
    close.addEventListener("click", () => dialog.close());
    dialog.append(close, element("div", "plot-dialog-content"));
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    document.body.append(dialog);
    return dialog;
  }

  function initialisePlotControls() {
    document.querySelectorAll("[data-plot-fullscreen]").forEach((button) => {
      button.addEventListener("click", () => {
        const figure = button.closest(".report-figure");
        const dialog = plotDialog();
        const content = dialog.querySelector(".plot-dialog-content");
        content.replaceChildren();
        const image = figure.querySelector(".plot-image");
        const plot = figure.querySelector(".plotly");
        if (image) content.append(image.cloneNode(true));
        else if (plot && window.Plotly && plot.data) {
          const clone = element("div", "plot-dialog-plot");
          content.append(clone);
          if (typeof dialog.showModal === "function") dialog.showModal();
          else dialog.setAttribute("open", "");
          Plotly.newPlot(clone, plot.data, Object.assign({}, plot.layout, { autosize: true }), {
            responsive: true,
            displaylogo: false,
          }).then(() => Plotly.Plots.resize(clone));
          dialog.addEventListener("close", () => Plotly.purge(clone), { once: true });
          return;
        }
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
      });
    });
  }

  function loadPlotly() {
    if (window.Plotly) return Promise.resolve();
    if (plotlyPromise) return plotlyPromise;
    plotlyPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdn.plot.ly/plotly-2.35.2.min.js";
      script.onload = resolve;
      script.onerror = () => {
        plotlyPromise = null;
        reject(new Error("Plot controls could not be loaded"));
      };
      document.head.append(script);
    });
    return plotlyPromise;
  }

  function renderVisiblePlotly(scope) {
    const nodes = scope.querySelectorAll(".plotly[data-component-id]");
    if (!nodes.length) return;
    if (!window.Plotly) {
      nodes.forEach((node) => {
        const root = node.closest(".report-figure") || node.parentElement;
        let status = root.querySelector(".plot-status");
        if (!status) {
          status = element("div", "plot-status");
          node.before(status);
        }
        status.textContent = "Loading plot controls...";
      });
      loadPlotly().then(() => {
        if (active) renderVisiblePlotly(scope);
      }).catch((error) => {
        if (!active) return;
        nodes.forEach((node) => {
          const status = (node.closest(".report-figure") || node.parentElement)
            .querySelector(".plot-status");
          status.replaceChildren(document.createTextNode(error.message + " "));
          const retry = element("button", "", "Retry");
          retry.type = "button";
          retry.addEventListener("click", () => renderVisiblePlotly(scope));
          status.append(retry);
        });
      });
      return;
    }
    nodes.forEach((node) => {
      const id = node.dataset.componentId;
      if (renderedPlotly.has(id) || !isVisible(node)) return;
      renderedPlotly.add(id);
      const figureRoot = node.closest(".report-figure") || node.parentElement;
      let status = figureRoot.querySelector(".plot-status");
      if (!status) {
        status = element("div", "plot-status", "Loading interactive plot...");
        node.before(status);
      } else {
        status.textContent = "Loading interactive plot...";
      }
      fetchJson(node.dataset.asset || dataUrl(id)).then((figure) => {
        if (!active) return;
        const config = Object.assign(
          { displaylogo: false, responsive: true },
          parseJson(node.dataset.config, {})
        );
        const layout = Object.assign({}, figure.layout || {});
        const mode = figureRoot?.dataset.plotDisplay || "intrinsic";
        const width = Number(layout.width) || 700;
        const height = Number(layout.height) || 450;
        if (mode === "full-width") {
          delete layout.width;
          layout.autosize = true;
          node.style.width = "100%";
        } else {
          node.style.width = width + "px";
        }
        node.style.height = height + "px";
        return Plotly.newPlot(node, figure.data || [], layout, config).then(() => {
          if (status) status.remove();
          if (mode !== "intrinsic" && window.ResizeObserver) {
            const observer = new ResizeObserver(() => Plotly.Plots.resize(node));
            observer.observe(figureRoot.querySelector(".plot-frame") || figureRoot);
            cleanups.add(() => observer.disconnect());
          }
        });
      }).catch((error) => {
        renderedPlotly.delete(id);
        if (error.name === "AbortError" || !active) return;
        status.replaceChildren(document.createTextNode(error.message + " "));
        const retry = element("button", "", "Retry");
        retry.type = "button";
        retry.addEventListener("click", () => renderVisiblePlotly(figureRoot));
        status.append(retry);
      });
    });
  }

  function normaliseTableOptions(node) {
    const configured = parseJson(node.dataset.options, {});
    const sizes = Array.isArray(configured.page_size_options)
      ? configured.page_size_options.filter(
        (value) => Number.isInteger(value) && value > 0 && value <= 1000
      )
      : [10, 25, 50, 100];
    const pageSize = Number.isInteger(configured.page_size) && configured.page_size > 0
      ? Math.min(1000, configured.page_size)
      : 25;
    if (!sizes.includes(pageSize)) sizes.push(pageSize);
    sizes.sort((left, right) => left - right);
    const density = ["compact", "normal", "comfortable"].includes(configured.density)
      ? configured.density
      : "normal";
    const pinned = configured.pinned_columns || {};
    const pagination = configured.pagination !== false;
    return {
      dataMode: !pagination
        ? "client"
        : ["auto", "client", "server"].includes(configured.data_mode)
          ? configured.data_mode
          : "auto",
      pagination,
      pageSize,
      pageSizeOptions: sizes,
      searchable: configured.searchable !== false,
      sortable: configured.sortable !== false,
      columnFilters: configured.column_filters !== false,
      columnVisibility: configured.column_visibility !== false,
      columnPinning: configured.column_pinning !== false,
      pinnedLeft: Array.isArray(pinned.left) ? pinned.left : [],
      pinnedRight: Array.isArray(pinned.right) ? pinned.right : [],
      density,
      urlState: configured.url_state !== false,
    };
  }

  function tableStateFromUrl(id, defaults) {
    const value = parseFragment().params.get("table-" + id);
    const stored = parseJson(value, {});
    return {
      sorting: Array.isArray(stored.s) ? stored.s : [],
      columnFilters: Array.isArray(stored.f)
        ? stored.f.map((filter) => ({
          id: filter.id,
          value: filter.value && typeof filter.value === "object" && "operator" in filter.value
            ? filter.value
            : { operator: filter.operator || "contains", value: filter.value },
        }))
        : [],
      globalFilter: typeof stored.q === "string" ? stored.q : "",
      pagination: {
        pageIndex: Number.isInteger(stored.p) && stored.p > 0 ? stored.p - 1 : 0,
        pageSize: Number.isInteger(stored.z) && stored.z > 0
          ? Math.min(1000, stored.z)
          : defaults.pageSize,
      },
      columnPinning: {
        left: Array.isArray(stored.l) ? stored.l : defaults.pinnedLeft,
        right: Array.isArray(stored.r) ? stored.r : defaults.pinnedRight,
      },
      columnSizing: {},
      columnVisibility: Array.isArray(stored.v)
        ? Object.fromEntries(stored.v.map((column) => [column, true]))
        : null,
      density: ["compact", "normal", "comfortable"].includes(stored.d)
        ? stored.d
        : defaults.density,
    };
  }

  function saveTableState(id, state, options, allColumns, defaultVisibility) {
    if (!options.urlState) return;
    const visible = allColumns.filter((column) => state.columnVisibility[column] !== false);
    const visibilityIsDefault = allColumns.every(
      (column) => (state.columnVisibility[column] !== false) === defaultVisibility[column]
    );
    const stored = {
      p: state.pagination.pageIndex ? state.pagination.pageIndex + 1 : undefined,
      z: state.pagination.pageSize === options.pageSize ? undefined : state.pagination.pageSize,
      q: state.globalFilter || undefined,
      s: state.sorting.length ? state.sorting : undefined,
      f: state.columnFilters.length ? state.columnFilters : undefined,
      v: visibilityIsDefault ? undefined : visible,
      l: state.columnPinning.left.length ? state.columnPinning.left : undefined,
      r: state.columnPinning.right.length ? state.columnPinning.right : undefined,
      d: state.density === options.density ? undefined : state.density,
    };
    Object.keys(stored).forEach((key) => stored[key] === undefined && delete stored[key]);
    updateFragment((params) => {
      if (Object.keys(stored).length) params.set("table-" + id, JSON.stringify(stored));
      else params.delete("table-" + id);
    });
    dispatchStateChange();
  }

  function tableQuery(state, options, includeProtocol = true) {
    const params = new URLSearchParams();
    if (includeProtocol) params.set("protocol", "1");
    params.set("data_mode", options.dataMode);
    params.set("page", String(state.pagination.pageIndex + 1));
    params.set("page_size", String(state.pagination.pageSize));
    if (state.globalFilter) params.set("q", state.globalFilter);
    if (state.sorting.length) params.set("sort", JSON.stringify(state.sorting));
    if (state.columnFilters.length) {
      const filters = state.columnFilters.map((filter) => ({
        id: filter.id,
        operator: filter.value?.operator || filter.operator || "contains",
        value: filter.value?.value ?? filter.value,
      }));
      params.set("filters", JSON.stringify(filters));
    }
    return params;
  }

  function intlOptions(config) {
    const aliases = {
      minimum_fraction_digits: "minimumFractionDigits",
      maximum_fraction_digits: "maximumFractionDigits",
      minimum_significant_digits: "minimumSignificantDigits",
      maximum_significant_digits: "maximumSignificantDigits",
      date_style: "dateStyle",
      time_style: "timeStyle",
      time_zone: "timeZone",
    };
    const result = {};
    Object.entries(config || {}).forEach(([key, value]) => {
      if (key !== "type") result[aliases[key] || key] = value;
    });
    return result;
  }

  function canonicalJson(value) {
    if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
    if (value && typeof value === "object") {
      return "{" + Object.keys(value).sort().map((key) =>
        JSON.stringify(key) + ":" + canonicalJson(value[key])
      ).join(",") + "}";
    }
    return JSON.stringify(value);
  }

  function decimalParts(value) {
    const match = String(value).match(/^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i);
    if (!match) return null;
    const sign = match[1] === "-" ? -1 : 1;
    const fraction = match[3] || "";
    const exponent = Number(match[4] || 0);
    return { sign, digits: BigInt((match[2] + fraction).replace(/^0+(?=\d)/, "")), scale: fraction.length - exponent };
  }

  function compareDecimals(leftValue, rightValue) {
    const left = decimalParts(leftValue);
    const right = decimalParts(rightValue);
    if (!left || !right) return Number(leftValue) - Number(rightValue);
    if (left.sign !== right.sign) return left.sign - right.sign;
    const scale = Math.max(left.scale, right.scale);
    const leftInteger = left.digits * 10n ** BigInt(scale - left.scale);
    const rightInteger = right.digits * 10n ** BigInt(scale - right.scale);
    if (leftInteger === rightInteger) return 0;
    return (leftInteger > rightInteger ? 1 : -1) * left.sign;
  }

  function comparisonValue(value, type) {
    if (type === "integer" || type === "number") return value;
    if (type === "date" || type === "datetime") {
      const text = String(value);
      return Date.parse(type === "datetime" && !/(?:z|[+-]\d\d:\d\d)$/i.test(text)
        ? text + "Z"
        : text);
    }
    if (type === "json") return canonicalJson(value);
    if (type === "boolean") return value ? 1 : 0;
    return String(value).toLocaleLowerCase();
  }

  function compareValues(leftValue, rightValue, type) {
    if (type === "integer" || type === "number") {
      return compareDecimals(leftValue, rightValue);
    }
    const left = comparisonValue(leftValue, type);
    const right = comparisonValue(rightValue, type);
    if (left === right) return 0;
    return left > right ? 1 : -1;
  }

  function searchValue(value) {
    if (value === null || value === undefined) return "";
    return (typeof value === "object" ? canonicalJson(value) : String(value)).toLocaleLowerCase();
  }

  function formatValue(value, column) {
    if (value === null || value === undefined) return "NA";
    const config = column.config?.format;
    const type = column.type;
    try {
      if (typeof config === "string") {
        const decimals = config.match(/^\.(\d+)f$/);
        if (decimals) {
          return new Intl.NumberFormat(undefined, {
            minimumFractionDigits: Number(decimals[1]),
            maximumFractionDigits: Number(decimals[1]),
          }).format(Number(value));
        }
        const exponential = config.match(/^\.(\d+)e$/);
        if (exponential) return Number(value).toExponential(Number(exponential[1]));
        const significant = config.match(/^\.(\d+)g$/);
        if (significant) return Number(value).toPrecision(Number(significant[1]));
      }
      if (type === "integer" || type === "number" || config?.type === "number") {
        if (type === "integer" && typeof value === "string" && /^-?\d+$/.test(value)) {
          return value.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        }
        return new Intl.NumberFormat(undefined, intlOptions(config)).format(Number(value));
      }
      if (type === "date" && /^\d{4}-\d{2}-\d{2}$/.test(String(value))) {
        const [year, month, day] = String(value).split("-").map(Number);
        return new Intl.DateTimeFormat(undefined, intlOptions(config))
          .format(new Date(year, month - 1, day));
      }
      if (type === "datetime" || config?.type === "datetime") {
        return new Intl.DateTimeFormat(undefined, intlOptions(config)).format(new Date(value));
      }
      if (type === "boolean") return value ? "True" : "False";
      if (typeof value === "object") return JSON.stringify(value);
    } catch (_error) {
      return String(value);
    }
    return String(value);
  }

  function columnAlignment(column) {
    const configured = column.config?.align;
    if (["left", "center", "right"].includes(configured)) return configured;
    if (["integer", "number"].includes(column.type)) return "right";
    if (column.type === "boolean") return "center";
    return "left";
  }

  function cellHref(template, row) {
    if (typeof template !== "string") return null;
    const href = template.replace(/\{([^{}]+)\}/g, (_match, column) =>
      encodeURIComponent(row[column] ?? "")
    );
    try {
      const parsed = new URL(href, window.location.href);
      if (!["http:", "https:", "mailto:"].includes(parsed.protocol)) return null;
      return href;
    } catch (_error) {
      return null;
    }
  }

  function loadTableCore() {
    if (window.TableCore) return Promise.resolve();
    if (tableCorePromise) return tableCorePromise;
    tableCorePromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://unpkg.com/@tanstack/table-core@8.21.3/build/umd/index.production.js";
      script.onload = resolve;
      script.onerror = () => {
        tableCorePromise = null;
        reject(new Error("Table controls could not be loaded"));
      };
      document.head.append(script);
    });
    return tableCorePromise;
  }

  function createTableView(node, envelope) {
    node.classList.remove("table");
    node.classList.add("data-table");
    const id = node.dataset.componentId;
    const core = window.TableCore;
    const options = normaliseTableOptions(node);
    const metadata = envelope.columns;
    const allColumns = metadata.map((column) => column.id);
    const visibleConfigured = parseJson(node.dataset.visibleColumns, null);
    const urlState = tableStateFromUrl(id, options);
    const defaultVisibility = Object.fromEntries(
      allColumns.map((name) => [name, !visibleConfigured || visibleConfigured.includes(name)])
    );
    const initialVisibility = urlState.columnVisibility
      ? Object.fromEntries(allColumns.map((name) => [name, urlState.columnVisibility[name] === true]))
      : { ...defaultVisibility };
    if (allColumns.length && !allColumns.some((name) => initialVisibility[name] !== false)) {
      initialVisibility[allColumns[0]] = true;
    }
    let state = Object.assign(urlState, { columnVisibility: initialVisibility });
    let response = envelope;
    let mode = envelope.mode;
    let table;
    let requestSequence = 0;
    let refreshTimer = null;
    let serverController = null;
    let destroyed = false;
    let loading = false;
    if (envelope.mode === "server") {
      state.pagination.pageIndex = Math.max(0, envelope.page - 1);
      state.pagination.pageSize = envelope.page_size;
    }

    const columns = metadata.map((column) => ({
      id: column.id,
      accessorFn: (row) => row[column.id] === null ? undefined : row[column.id],
      header: column.config?.label || column.label || column.id,
      size: Math.max(60, Math.min(600, Number(column.config?.width) || 160)),
      enableSorting: options.sortable && column.config?.sortable !== false,
      enableColumnFilter: options.columnFilters && column.config?.filterable !== false,
      filterFn: "polyptich",
      sortingFn: "polyptichSort",
      sortUndefined: "last",
      meta: { info: column, align: columnAlignment(column) },
    }));

    const toolbar = element("div", "data-table-toolbar");
    const search = element("input", "data-table-search");
    search.type = "search";
    search.placeholder = "Search all columns";
    search.setAttribute("aria-label", "Search all columns");
    search.value = state.globalFilter;
    if (options.searchable) toolbar.append(search);

    const clear = element("button", "data-table-clear", "Clear filters");
    clear.type = "button";
    toolbar.append(clear);

    const density = element("select", "data-table-density");
    density.setAttribute("aria-label", "Table density");
    ["compact", "normal", "comfortable"].forEach((value) => {
      const option = element("option", "", value[0].toUpperCase() + value.slice(1));
      option.value = value;
      option.selected = value === state.density;
      density.append(option);
    });
    toolbar.append(density);

    const chooser = element("details", "data-table-columns");
    chooser.append(element("summary", "", "Columns"));
    const menu = element("div", "data-table-columns-menu");
    chooser.append(menu);
    if (options.columnVisibility || options.columnPinning) toolbar.append(chooser);

    const status = element("div", "data-table-status", "Loading table...");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const scroll = element("div", "data-table-scroll");
    const tableElement = element("table");
    const head = element("thead");
    const body = element("tbody");
    tableElement.append(head, body);
    scroll.append(tableElement);

    const footer = element("div", "data-table-pagination");
    const count = element("span", "data-table-count");
    const first = element("button", "", "First");
    const previous = element("button", "", "Previous");
    const page = element("span");
    const next = element("button", "", "Next");
    const last = element("button", "", "Last");
    const pageSize = element("select");
    first.type = previous.type = next.type = last.type = "button";
    options.pageSizeOptions.forEach((size) => {
      const option = element("option", "", String(size) + " rows");
      option.value = String(size);
      pageSize.append(option);
    });
    pageSize.value = String(state.pagination.pageSize);
    pageSize.setAttribute("aria-label", "Rows per page");
    footer.append(count, first, previous, page, next, last, pageSize);
    if (!options.pagination && mode !== "server") {
      [first, previous, page, next, last, pageSize].forEach((control) => {
        control.hidden = true;
      });
    }

    function setBusy(value, message) {
      loading = value;
      node.setAttribute("aria-busy", value ? "true" : "false");
      node.classList.toggle("data-table-loading", value);
      status.textContent = message || "";
    }

    function relevantState(value) {
      return JSON.stringify([
        value.sorting,
        value.columnFilters,
        value.globalFilter,
        value.pagination,
      ]);
    }

    const tableOptions = {
      data: response.rows,
      columns,
      state,
      enableSorting: options.sortable,
      enableFilters: options.columnFilters || options.searchable,
      enableColumnFilters: options.columnFilters,
      enableColumnPinning: options.columnPinning,
      globalFilterFn: "polyptichGlobal",
      sortingFns: {
        polyptichSort: (leftRow, rightRow, columnId) => {
          const info = metadata.find((item) => item.id === columnId);
          return compareValues(leftRow.getValue(columnId), rightRow.getValue(columnId), info?.type);
        },
      },
      filterFns: {
        polyptichGlobal: (row, columnId, filter) => searchValue(row.getValue(columnId))
          .includes(String(filter).toLocaleLowerCase()),
        polyptich: (row, columnId, filter) => {
          const value = row.getValue(columnId);
          const operator = filter?.operator || "contains";
          const expected = filter?.value ?? filter;
          if (value === null || value === undefined) return operator === "is_null";
          if (operator === "not_null") return true;
          const info = metadata.find((item) => item.id === columnId);
          if (["contains", "starts_with", "ends_with"].includes(operator)) {
            const left = searchValue(value);
            const right = String(expected).toLocaleLowerCase();
            if (operator === "contains") return left.includes(right);
            if (operator === "starts_with") return left.startsWith(right);
            return left.endsWith(right);
          }
          const comparison = compareValues(value, expected, info?.type);
          if (operator === "eq") return comparison === 0;
          if (operator === "ne") return comparison !== 0;
          if (operator === "gt") return comparison > 0;
          if (operator === "gte") return comparison >= 0;
          if (operator === "lt") return comparison < 0;
          if (operator === "lte") return comparison <= 0;
          if (operator === "between" && Array.isArray(expected)) {
            return compareValues(value, expected[0], info?.type) >= 0
              && compareValues(value, expected[1], info?.type) <= 0;
          }
          return true;
        },
      },
      getCoreRowModel: core.getCoreRowModel(),
      onStateChange: (updater) => {
        const before = relevantState(state);
        state = typeof updater === "function" ? updater(state) : updater;
        table.setOptions((current) => Object.assign({}, current, { state }));
        node.dataset.density = state.density;
        saveTableState(id, state, options, allColumns, defaultVisibility);
        render();
        if (mode === "server" && before !== relevantState(state)) scheduleRefresh();
      },
    };
    if (mode === "client") {
      tableOptions.getFilteredRowModel = core.getFilteredRowModel();
      tableOptions.getSortedRowModel = core.getSortedRowModel();
      if (options.pagination) tableOptions.getPaginationRowModel = core.getPaginationRowModel();
    } else {
      Object.assign(tableOptions, {
        manualFiltering: true,
        manualSorting: true,
        manualPagination: true,
        pageCount: Math.max(1, response.page_count),
        rowCount: response.filtered_count,
      });
    }
    table = core.createTable(tableOptions);
    node.dataset.density = state.density;

    function renderColumnsMenu() {
      const controls = table.getAllLeafColumns().map((column) => {
        const row = element("div", "data-table-column-control");
        const label = element("label");
        const checkbox = element("input");
        checkbox.type = "checkbox";
        checkbox.dataset.tableControl = "visibility";
        checkbox.dataset.columnId = column.id;
        checkbox.checked = column.getIsVisible();
        checkbox.disabled = !options.columnVisibility;
        if (checkbox.checked && table.getVisibleLeafColumns().length === 1) checkbox.disabled = true;
        checkbox.addEventListener("change", () => column.toggleVisibility(checkbox.checked));
        label.append(checkbox, document.createTextNode(String(column.columnDef.header)));
        row.append(label);
        if (options.columnPinning) {
          const pin = element("select");
          pin.dataset.tableControl = "pin";
          pin.dataset.columnId = column.id;
          pin.setAttribute("aria-label", "Pin " + column.columnDef.header);
          [["", "Not pinned"], ["left", "Pin left"], ["right", "Pin right"]]
            .forEach(([value, text]) => {
              const option = element("option", "", text);
              option.value = value;
              option.selected = column.getIsPinned() === value
                || (!value && !column.getIsPinned());
              pin.append(option);
            });
          pin.addEventListener("change", () => column.pin(pin.value || false));
          row.append(pin);
        }
        return row;
      });
      menu.replaceChildren(...controls);
    }

    function pinnedStyle(column) {
      const pinned = column.getIsPinned();
      if (!pinned) return {};
      return pinned === "left"
        ? { position: "sticky", left: column.getStart("left") + "px" }
        : { position: "sticky", right: column.getAfter("right") + "px" };
    }

    function applyCellStyle(cell, column) {
      cell.classList.add("data-table-align-" + (column.columnDef.meta.align || "left"));
      cell.style.width = column.getSize() + "px";
      cell.style.minWidth = column.getSize() + "px";
      const pinned = column.getIsPinned();
      if (pinned) {
        cell.classList.add("data-table-pinned", "data-table-pinned-" + pinned);
        Object.assign(cell.style, pinnedStyle(column));
      }
    }

    function render() {
      const activeControl = document.activeElement?.dataset?.tableControl;
      const activeColumn = document.activeElement?.dataset?.columnId;
      const headerRows = table.getHeaderGroups().map((group) => {
        const row = element("tr");
        group.headers.forEach((header) => {
          const column = header.column;
          const th = element("th");
          applyCellStyle(th, column);
          const direction = column.getIsSorted();
          th.setAttribute(
            "aria-sort",
            direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none"
          );
          const sort = element("button", "data-table-sort");
          sort.type = "button";
          sort.dataset.tableControl = "sort";
          sort.dataset.columnId = column.id;
          sort.disabled = !column.getCanSort();
          sort.textContent = String(column.columnDef.header)
            + (direction === "asc" ? " (asc)" : direction === "desc" ? " (desc)" : "");
          if (column.getCanSort()) sort.addEventListener("click", column.getToggleSortingHandler());
          th.append(sort);
          if (column.getCanFilter()) {
            const filter = element("input", "data-table-filter");
            filter.type = "search";
            filter.dataset.tableControl = "filter";
            filter.dataset.columnId = column.id;
            const current = state.columnFilters.find((item) => item.id === column.id);
            filter.value = current?.value?.value ?? current?.value ?? "";
            filter.placeholder = "Filter";
            filter.setAttribute("aria-label", "Filter " + column.columnDef.header);
            filter.addEventListener("change", () => {
              const operator = column.columnDef.meta.info.type === "string" ? "contains" : "eq";
              table.setColumnFilters((currentFilters) => {
                const remaining = currentFilters.filter((item) => item.id !== column.id);
                return filter.value
                  ? remaining.concat({ id: column.id, value: { operator, value: filter.value } })
                  : remaining;
              });
            });
            th.append(filter);
          }
          row.append(th);
        });
        return row;
      });
      head.replaceChildren(...headerRows);

      const bodyRows = table.getRowModel().rows.map((rowModel) => {
        const row = element("tr");
        rowModel.getVisibleCells().forEach((cell) => {
          const td = element("td");
          applyCellStyle(td, cell.column);
          const value = cell.getValue();
          const formatted = formatValue(value, cell.column.columnDef.meta.info);
          const href = cellHref(
            cell.column.columnDef.meta.info.config?.href,
            rowModel.original
          );
          if (href) {
            const link = element("a", "data-table-cell-link", formatted);
            link.href = href;
            td.append(link);
          } else {
            td.textContent = formatted;
          }
          if (value !== null && value !== undefined) td.title = String(value);
          row.append(td);
        });
        return row;
      });
      if (!bodyRows.length && !loading) {
        const row = element("tr");
        const cell = element(
          "td",
          "data-table-empty",
          response.total_count ? "No rows match the current filters." : "This table has no rows."
        );
        cell.colSpan = Math.max(1, table.getVisibleLeafColumns().length);
        row.append(cell);
        bodyRows.push(row);
      }
      body.replaceChildren(...bodyRows);

      const filtered = mode === "client"
        ? table.getFilteredRowModel().rows.length
        : response.filtered_count;
      const total = response.total_count;
      count.textContent = filtered === total
        ? total.toLocaleString() + (total === 1 ? " row" : " rows")
        : filtered.toLocaleString() + " of " + total.toLocaleString() + " rows";
      const pageCount = mode === "client" ? table.getPageCount() : response.page_count;
      page.textContent = "Page " + (state.pagination.pageIndex + 1) + " of " + Math.max(1, pageCount);
      first.disabled = previous.disabled = loading || !table.getCanPreviousPage();
      next.disabled = last.disabled = loading || !table.getCanNextPage();
      pageSize.value = String(state.pagination.pageSize);
      clear.disabled = !state.globalFilter && !state.columnFilters.length && !state.sorting.length;
      renderColumnsMenu();
      if (activeControl && activeColumn) {
        const replacement = Array.from(node.querySelectorAll("[data-table-control]"))
          .find((control) => control.dataset.tableControl === activeControl
            && control.dataset.columnId === activeColumn);
        replacement?.focus({ preventScroll: true });
      }
    }

    function applyServerResponse(nextResponse) {
      response = nextResponse;
      table.setOptions((current) => Object.assign({}, current, {
        data: response.rows,
        pageCount: Math.max(1, response.page_count),
        rowCount: response.filtered_count,
      }));
      if (response.page_count && state.pagination.pageIndex >= response.page_count) {
        table.setPageIndex(response.page_count - 1);
        return;
      }
      setBusy(false, "");
      render();
    }

    async function refresh() {
      const sequence = ++requestSequence;
      if (serverController) serverController.abort();
      serverController = new AbortController();
      setBusy(true, "Updating table...");
      try {
        const nextResponse = await fetchJson(
          dataUrl(id) + "?" + tableQuery(state, options),
          { controller: serverController }
        );
        if (!destroyed && sequence === requestSequence) applyServerResponse(nextResponse);
      } catch (error) {
        if (error.name === "AbortError" || destroyed) return;
        setBusy(false, "");
        status.replaceChildren(document.createTextNode(error.message + " "));
        status.setAttribute("role", "alert");
        const retry = element("button", "", "Retry");
        retry.type = "button";
        retry.addEventListener("click", refresh);
        status.append(retry);
      }
    }

    function scheduleRefresh() {
      window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(refresh, 250);
    }

    let searchTimer = null;
    search.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        table.setGlobalFilter(search.value);
        table.setPageIndex(0);
      }, 250);
    });
    clear.addEventListener("click", () => {
      search.value = "";
      table.setGlobalFilter("");
      table.setColumnFilters([]);
      table.setSorting([]);
      table.setPageIndex(0);
    });
    density.addEventListener("change", () => {
      state = Object.assign({}, state, { density: density.value });
      table.setOptions((current) => Object.assign({}, current, { state }));
      node.dataset.density = density.value;
      saveTableState(id, state, options, allColumns, defaultVisibility);
    });
    first.addEventListener("click", () => table.firstPage());
    previous.addEventListener("click", () => table.previousPage());
    next.addEventListener("click", () => table.nextPage());
    last.addEventListener("click", () => table.lastPage());
    pageSize.addEventListener("change", () => table.setPageSize(Number(pageSize.value)));

    node.replaceChildren(toolbar, status, scroll, footer);
    setBusy(false, "");
    render();
    if (mode === "server" && envelope.page - 1 !== urlState.pagination.pageIndex) {
      saveTableState(id, state, options, allColumns, defaultVisibility);
    }

    const applyUrlState = () => {
      const incoming = tableStateFromUrl(id, options);
      const incomingVisibility = incoming.columnVisibility
        ? Object.fromEntries(
          allColumns.map((name) => [name, incoming.columnVisibility[name] === true])
        )
        : { ...defaultVisibility };
      if (allColumns.length && !allColumns.some((name) => incomingVisibility[name] !== false)) {
        incomingVisibility[allColumns[0]] = true;
      }
      state = Object.assign({}, state, incoming, {
        columnVisibility: incomingVisibility,
      });
      table.setOptions((current) => Object.assign({}, current, { state }));
      search.value = state.globalFilter;
      density.value = state.density;
      node.dataset.density = state.density;
      render();
      if (mode === "server") scheduleRefresh();
    };
    tableUrlAppliers.add(applyUrlState);

    const actionRoot = node.closest(".component-table") || node.parentElement;
    Array.from(actionRoot.querySelectorAll("[data-table-export]"))
      .filter((button) => button.dataset.tableExport === id)
      .forEach((button) => {
        button.addEventListener("click", async () => {
          const format = button.dataset.format;
          const params = tableQuery(state, options, false);
          params.set("columns", JSON.stringify(
            table.getVisibleLeafColumns().map((column) => column.id)
          ));
          const original = button.textContent;
          button.disabled = true;
          button.textContent = "Preparing...";
          try {
            const responseValue = await fetchResource(downloadUrl(id, format, params));
            const blob = await responseValue.blob();
            const link = element("a");
            link.href = URL.createObjectURL(blob);
            link.download = id + "." + format;
            link.click();
            URL.revokeObjectURL(link.href);
          } catch (error) {
            status.textContent = error.message;
            status.setAttribute("role", "alert");
          } finally {
            button.disabled = false;
            button.textContent = original;
          }
        });
      });

    return () => {
      destroyed = true;
      tableUrlAppliers.delete(applyUrlState);
      if (serverController) serverController.abort();
      window.clearTimeout(refreshTimer);
      window.clearTimeout(searchTimer);
      node.replaceChildren();
    };
  }

  async function initialiseTable(node) {
    const id = node.dataset.componentId;
    if (renderedTables.has(id)) return;
    renderedTables.add(id);
    node.classList.add("data-table");
    node.setAttribute("aria-busy", "true");
    node.textContent = "Loading table...";
    try {
      await loadTableCore();
      if (!active) return;
      const options = normaliseTableOptions(node);
      const state = tableStateFromUrl(id, options);
      const envelope = await fetchJson(dataUrl(id) + "?" + tableQuery(state, options));
      if (!active) return;
      cleanups.add(createTableView(node, envelope));
    } catch (error) {
      renderedTables.delete(id);
      if (error.name === "AbortError" || !active) return;
      node.removeAttribute("aria-busy");
      node.replaceChildren(document.createTextNode(error.message + " "));
      const retry = element("button", "", "Retry");
      retry.type = "button";
      retry.addEventListener("click", () => initialiseTable(node));
      node.append(retry);
    }
  }

  function renderVisibleTables(scope) {
    scope.querySelectorAll(".data-table[data-component-id], .table[data-component-id]")
      .forEach((node) => {
        if (isVisible(node)) initialiseTable(node);
      });
  }

  function initialiseLegacyDownloads() {
    document.querySelectorAll("[data-table-download]").forEach((link) => {
      link.href = downloadUrl(link.dataset.tableDownload, "xlsx");
    });
  }

  function initialiseDeleteControls() {
    document.querySelectorAll("[data-delete-form]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        const name = form.dataset.deleteName || "this file";
        if (!window.confirm("Delete " + name + "? This cannot be undone.")) {
          event.preventDefault();
          return;
        }
        form.elements.confirmed.value = "yes";
      });
    });
  }

  function queueRender(scope) {
    requestAnimationFrame(() => {
      if (!active) return;
      renderVisiblePlotly(scope);
      renderVisibleTables(scope);
    });
  }

  function onHashChange() {
    const params = parseFragment().params;
    applyTabState(params);
    applyDetailsState(params);
    tableUrlAppliers.forEach((apply) => apply());
    const target = parseFragment().target;
    if (target) {
      const targetElement = document.getElementById(target);
      revealTarget({ detail: { target, element: targetElement, params } });
      targetElement?.scrollIntoView();
    }
    queueRender(document);
  }

  function unmount() {
    if (!active) return;
    active = false;
    requestControllers.forEach((controller) => controller.abort());
    requestControllers.clear();
    cleanups.forEach((cleanup) => cleanup());
    cleanups.clear();
    document.querySelectorAll(".plotly[data-component-id]").forEach((node) => {
      if (window.Plotly) Plotly.purge(node);
    });
    document.querySelector(".plot-dialog")?.remove();
    window.removeEventListener("polyptich:before-page-swap", unmount);
    window.removeEventListener("polyptich:report-reveal", revealTarget);
    window.removeEventListener("hashchange", onHashChange);
    window.removeEventListener("beforeprint", beforePrint);
    window.removeEventListener("afterprint", afterPrint);
  }

  window.addEventListener("polyptich:before-page-swap", unmount);
  window.addEventListener("polyptich:report-reveal", revealTarget);
  window.addEventListener("hashchange", onHashChange);
  window.addEventListener("beforeprint", beforePrint);
  window.addEventListener("afterprint", afterPrint);

  initialiseTabs();
  initialiseDetails();
  initialisePermalinks();
  initialiseAutoBreadcrumbs();
  initialiseReportTools();
  initialisePlotControls();
  initialiseLegacyDownloads();
  initialiseDeleteControls();
  queueRender(document);
})();
