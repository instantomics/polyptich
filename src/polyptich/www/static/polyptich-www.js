(function () {
  const renderedPlotly = new Set();
  const renderedTables = new Set();

  function reportPath() {
    const match = window.location.pathname.match(/^\/report\/(.*)$/);
    return match ? decodeURIComponent(match[1]).replace(/\/$/, "") : "";
  }

  function dataUrl(id) {
    return "/report-data/" + encodeURIComponent(reportPath()).replace(/%2F/g, "/") + "/" + encodeURIComponent(id);
  }

  function downloadUrl(id) {
    return "/report-download/" + encodeURIComponent(reportPath()).replace(/%2F/g, "/") + "/" + encodeURIComponent(id) + ".xlsx";
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

  function activeTabId(groupId, tabs) {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    const value = params.get("tab-" + groupId);
    return tabs.some((tab) => tab.id === value) ? value : null;
  }

  function activateTab(wrapper, groupId, tabId) {
    wrapper.querySelectorAll(".tab-button").forEach((button) => {
      const active = button.dataset.tab === tabId;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    wrapper.querySelectorAll(":scope > .tab-panels > .tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === tabId));
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    params.set("tab-" + groupId, tabId);
    history.replaceState(null, "", "#" + params.toString());
    queueRender(wrapper);
  }

  function initialiseTabs() {
    document.querySelectorAll(".tabs").forEach((wrapper) => {
      const buttons = Array.from(wrapper.querySelectorAll(":scope > .tab-buttons > .tab-button"));
      const selected = activeTabId(wrapper.id, buttons.map((button) => ({ id: button.dataset.tab })));
      buttons.forEach((button, index) => {
        const active = selected ? button.dataset.tab === selected : index === 0;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.addEventListener("click", () => activateTab(wrapper, wrapper.id, button.dataset.tab));
      });
      wrapper.querySelectorAll(":scope > .tab-panels > .tab-panel").forEach((panel, index) => {
        const active = selected ? panel.id === selected : index === 0;
        panel.classList.toggle("active", active);
      });
    });
  }

  function renderVisiblePlotly(scope) {
    if (!window.Plotly) return;
    scope.querySelectorAll(".plotly[data-component-id]").forEach((node) => {
      const id = node.dataset.componentId;
      if (renderedPlotly.has(id) || !isVisible(node)) return;
      renderedPlotly.add(id);
      fetch(node.dataset.asset || dataUrl(id)).then((r) => r.json()).then((figure) => {
        const config = Object.assign({ displaylogo: false, responsive: true }, parseJson(node.dataset.config, {}));
        Plotly.newPlot(node, figure.data || [], figure.layout || {}, config);
      });
    });
  }

  function renderVisibleTables(scope) {
    if (!window.Tabulator) return;
    scope.querySelectorAll(".table[data-component-id]").forEach((node) => {
      const id = node.dataset.componentId;
      if (renderedTables.has(id) || !isVisible(node)) return;
      renderedTables.add(id);
      fetch(dataUrl(id)).then((r) => r.json()).then((rows) => {
        const visible = parseJson(node.dataset.visibleColumns, null);
        const configured = parseJson(node.dataset.columns, []);
        const sourceColumns = configured.length ? configured : Object.keys(rows[0] || {});
        const columns = sourceColumns
          .filter((column) => !visible || visible.includes(column))
          .map((column) => ({ title: column, field: column, headerFilter: true }));
        new Tabulator(node, { data: rows, columns, layout: "fitDataStretch", pagination: true, paginationSize: 25 });
      });
    });
  }

  function initialiseDownloads() {
    document.querySelectorAll("[data-table-download]").forEach((link) => {
      link.href = downloadUrl(link.dataset.tableDownload);
    });
  }

  function queueRender(scope) {
    requestAnimationFrame(() => {
      renderVisiblePlotly(scope);
      renderVisibleTables(scope);
    });
  }

  initialiseTabs();
  initialiseDownloads();
  queueRender(document);
})();
