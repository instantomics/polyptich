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

  function setServiceState(indicator, state, label) {
    indicator.classList.remove("health-ok", "health-restarting", "health-offline");
    indicator.classList.add("health-" + state);
    indicator.textContent = label;
  }

  async function waitForService(button, indicator, status) {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      try {
        const response = await fetch("/healthz?restart=" + Date.now(), { cache: "no-store" });
        if (response.ok) {
          window.location.reload();
          return;
        }
      } catch (_error) {
        // Expected while the process is being replaced.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    setServiceState(indicator, "offline", "Service unavailable");
    status.textContent = "Service has not returned; reload manually.";
    button.disabled = false;
  }

  function initialiseServiceRestart() {
    const button = document.querySelector("[data-service-restart]");
    if (!button) return;
    const indicator = document.querySelector("[data-health-indicator]");
    const status = document.querySelector("[data-service-restart-status]");
    button.addEventListener("click", async () => {
      if (!window.confirm("Restart the Polyptich service? Active agent runs will continue.")) return;
      button.disabled = true;
      status.textContent = "Restarting...";
      setServiceState(indicator, "restarting", "Restarting service");
      try {
        const sessionResponse = await fetch(button.dataset.sessionUrl, { cache: "no-store" });
        const sessionPayload = await sessionResponse.json();
        if (!sessionResponse.ok) throw new Error("Could not authorize restart");
        const response = await fetch(button.dataset.restartUrl, {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "X-Iomix-CSRF": sessionPayload.data.csrf_token },
          body: "{}",
        });
        if (!response.ok) throw new Error("Restart request failed (" + response.status + ")");
        window.setTimeout(() => waitForService(button, indicator, status), 1200);
      } catch (error) {
        setServiceState(indicator, "offline", "Restart failed");
        status.textContent = error.message;
        button.disabled = false;
      }
    });
  }

  initialiseTabs();
  initialiseDownloads();
  initialiseServiceRestart();
  queueRender(document);
})();
