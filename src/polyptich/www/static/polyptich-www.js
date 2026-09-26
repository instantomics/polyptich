(function () {
  const renderedPlotly = new Set();
  const renderedTables = new Set();
  const tableCleanups = new Set();
  const requestControllers = new Set();
  let active = true;

  function unmount() {
    if (!active) return;
    active = false;
    window.removeEventListener("polyptich:before-page-swap", unmount);
    requestControllers.forEach((controller) => controller.abort());
    requestControllers.clear();
    tableCleanups.forEach((cleanup) => cleanup());
    tableCleanups.clear();
    document.querySelectorAll(".plotly[data-component-id]").forEach((node) => {
      if (window.Plotly) Plotly.purge(node);
    });
  }

  window.addEventListener("polyptich:before-page-swap", unmount);

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

  function fetchJson(url) {
    const controller = new AbortController();
    requestControllers.add(controller);
    return fetch(url, {signal: controller.signal})
      .then((response) => response.json())
      .finally(() => requestControllers.delete(controller));
  }

  function activeTabId(groupId, tabs) {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    const value = params.get("tab-" + groupId);
    return tabs.some((tab) => tab.id === value) ? value : null;
  }

  function activateTab(wrapper, groupId, tabId, focus = false) {
    let activeButton = null;
    wrapper.querySelectorAll(":scope > .tab-buttons > .tab-button").forEach((button) => {
      const active = button.dataset.tab === tabId;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
      button.tabIndex = active ? 0 : -1;
      if (active) activeButton = button;
    });
    wrapper.querySelectorAll(":scope > .tab-panels > .tab-panel").forEach((panel) => {
      const active = panel.id === tabId;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    params.set("tab-" + groupId, tabId);
    history.replaceState(history.state, "", "#" + params.toString());
    if (focus) activeButton?.focus();
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
        button.tabIndex = active ? 0 : -1;
        button.addEventListener("click", () => activateTab(wrapper, wrapper.id, button.dataset.tab));
        button.addEventListener("keydown", (event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          let targetIndex;
          if (event.key === "Home") targetIndex = 0;
          else if (event.key === "End") targetIndex = buttons.length - 1;
          else {
            const offset = event.key === "ArrowRight" ? 1 : -1;
            targetIndex = (buttons.indexOf(button) + offset + buttons.length) % buttons.length;
          }
          const target = buttons[targetIndex];
          if (target) activateTab(wrapper, wrapper.id, target.dataset.tab, true);
        });
      });
      wrapper.querySelectorAll(":scope > .tab-panels > .tab-panel").forEach((panel, index) => {
        const active = selected ? panel.id === selected : index === 0;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
    });
  }

  function renderVisiblePlotly(scope) {
    if (!window.Plotly) return;
    scope.querySelectorAll(".plotly[data-component-id]").forEach((node) => {
      const id = node.dataset.componentId;
      if (renderedPlotly.has(id) || !isVisible(node)) return;
      renderedPlotly.add(id);
      fetchJson(node.dataset.asset || dataUrl(id)).then((figure) => {
        if (!active) return;
        const config = Object.assign({ displaylogo: false, responsive: true }, parseJson(node.dataset.config, {}));
        const layout = figure.layout || {};
        const width = Number(layout.width) || 700;
        const height = Number(layout.height) || 450;
        node.style.width = width + "px";
        node.style.height = height + "px";
        Plotly.newPlot(node, figure.data || [], layout, config);
      }).catch((error) => {
        if (error.name !== "AbortError" && active) node.textContent = "Plot is temporarily unavailable";
      });
    });
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function displayValue(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "object") {
      try {
        return JSON.stringify(value);
      } catch (_error) {
        return String(value);
      }
    }
    return String(value);
  }

  function normaliseTableOptions(node) {
    const configured = parseJson(node.dataset.options, {});
    const pageSizeOptions = Array.isArray(configured.page_size_options)
      ? configured.page_size_options.filter((value) => Number.isInteger(value) && value > 0)
      : [10, 25, 50, 100];
    const pageSize = Number.isInteger(configured.page_size) && configured.page_size > 0
      ? configured.page_size
      : 25;
    if (!pageSizeOptions.includes(pageSize)) pageSizeOptions.push(pageSize);
    pageSizeOptions.sort((left, right) => left - right);
    return {
      pagination: configured.pagination !== false,
      pageSize,
      pageSizeOptions,
      searchable: configured.searchable !== false,
      sortable: configured.sortable !== false,
      columnFilters: configured.column_filters !== false,
      columnVisibility: configured.column_visibility !== false,
    };
  }

  function createTableView(node, rows) {
    const core = window.TableCore;
    const options = normaliseTableOptions(node);
    const configuredColumns = parseJson(node.dataset.columns, []);
    const sourceColumns = configuredColumns.length ? configuredColumns : Object.keys(rows[0] || {});
    const visibleColumns = parseJson(node.dataset.visibleColumns, null);
    const configuredColumnOptions = parseJson(node.dataset.columnOptions, {});
    const columnOptions = configuredColumnOptions && typeof configuredColumnOptions === "object"
      ? configuredColumnOptions
      : {};
    const columns = sourceColumns.map((name) => {
      const configured = columnOptions[name] || {};
      return {
        id: name,
        accessorKey: name,
        header: configured.label || name,
        enableSorting: options.sortable && configured.sortable !== false,
        enableColumnFilter: options.columnFilters && configured.filterable !== false,
        filterFn: "includesString",
        meta: { align: ["left", "center", "right"].includes(configured.align) ? configured.align : "left" },
      };
    });
    let state = {
      sorting: [],
      columnFilters: [],
      globalFilter: "",
      pagination: { pageIndex: 0, pageSize: options.pageSize },
      columnPinning: { left: [], right: [] },
      columnVisibility: Object.fromEntries(
        sourceColumns.map((name) => [name, !visibleColumns || visibleColumns.includes(name)])
      ),
    };
    let table;
    const tableOptions = {
      data: rows,
      columns,
      state,
      enableSorting: options.sortable,
      enableFilters: options.columnFilters || options.searchable,
      enableColumnFilters: options.columnFilters,
      globalFilterFn: "includesString",
      getCoreRowModel: core.getCoreRowModel(),
      getFilteredRowModel: core.getFilteredRowModel(),
      getSortedRowModel: core.getSortedRowModel(),
      onStateChange: (updater) => {
        state = typeof updater === "function" ? updater(state) : updater;
        table.setOptions((current) => Object.assign({}, current, { state }));
        render();
      },
    };
    if (options.pagination) tableOptions.getPaginationRowModel = core.getPaginationRowModel();
    table = core.createTable(tableOptions);

    const toolbar = element("div", "data-table-toolbar");
    if (options.searchable) {
      const search = element("input", "data-table-search");
      search.type = "search";
      search.placeholder = "Search all columns";
      search.setAttribute("aria-label", "Search all columns");
      search.addEventListener("input", () => table.setGlobalFilter(search.value));
      toolbar.append(search);
    }
    if (options.columnVisibility) {
      const chooser = element("details", "data-table-columns");
      chooser.append(element("summary", "", "Columns"));
      const menu = element("div", "data-table-columns-menu");
      table.getAllLeafColumns().forEach((column) => {
        const label = element("label");
        const checkbox = element("input");
        checkbox.type = "checkbox";
        checkbox.checked = column.getIsVisible();
        checkbox.addEventListener("change", () => column.toggleVisibility(checkbox.checked));
        label.append(checkbox, document.createTextNode(String(column.columnDef.header)));
        menu.append(label);
      });
      chooser.append(menu);
      toolbar.append(chooser);
    }

    const scroll = element("div", "data-table-scroll");
    const tableElement = element("table");
    const head = element("thead");
    const body = element("tbody");
    tableElement.append(head, body);
    scroll.append(tableElement);

    const pagination = element("div", "data-table-pagination");
    const count = element("span", "data-table-count");
    const first = element("button", "", "First");
    const previous = element("button", "", "Previous");
    const page = element("span");
    const next = element("button", "", "Next");
    const last = element("button", "", "Last");
    const pageSize = element("select");
    first.type = previous.type = next.type = last.type = "button";
    first.addEventListener("click", () => table.firstPage());
    previous.addEventListener("click", () => table.previousPage());
    next.addEventListener("click", () => table.nextPage());
    last.addEventListener("click", () => table.lastPage());
    options.pageSizeOptions.forEach((size) => {
      const option = element("option", "", String(size) + " rows");
      option.value = String(size);
      option.selected = size === options.pageSize;
      pageSize.append(option);
    });
    pageSize.setAttribute("aria-label", "Rows per page");
    pageSize.addEventListener("change", () => table.setPageSize(Number(pageSize.value)));
    pagination.append(count, first, previous, page, next, last, pageSize);

    function render() {
      const headerRows = table.getHeaderGroups().map((headerGroup) => {
        const row = element("tr");
        headerGroup.headers.forEach((header) => {
          const th = element("th");
          const column = header.column;
          const align = column.columnDef.meta?.align || "left";
          th.classList.add("data-table-align-" + align);
          const direction = column.getIsSorted();
          th.setAttribute("aria-sort", direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none");
          const sort = element("button", "data-table-sort");
          sort.type = "button";
          sort.disabled = !column.getCanSort();
          sort.append(
            document.createTextNode(String(column.columnDef.header)),
            document.createTextNode(direction === "asc" ? " (asc)" : direction === "desc" ? " (desc)" : "")
          );
          if (column.getCanSort()) sort.addEventListener("click", column.getToggleSortingHandler());
          th.append(sort);
          if (column.getCanFilter()) {
            const filter = element("input", "data-table-filter");
            filter.type = "search";
            filter.value = column.getFilterValue() || "";
            filter.placeholder = "Filter";
            filter.setAttribute("aria-label", "Filter " + column.columnDef.header);
            filter.addEventListener("change", () => column.setFilterValue(filter.value));
            filter.addEventListener("click", (event) => event.stopPropagation());
            th.append(filter);
          }
          row.append(th);
        });
        return row;
      });
      head.replaceChildren(...headerRows);

      const model = table.getRowModel();
      const bodyRows = model.rows.map((rowModel) => {
        const row = element("tr");
        rowModel.getVisibleCells().forEach((cell) => {
          const td = element("td", "data-table-align-" + (cell.column.columnDef.meta?.align || "left"));
          td.textContent = displayValue(cell.getValue());
          row.append(td);
        });
        return row;
      });
      if (!bodyRows.length) {
        const row = element("tr");
        const cell = element("td", "data-table-empty", "No matching rows");
        cell.colSpan = Math.max(1, table.getVisibleLeafColumns().length);
        row.append(cell);
        bodyRows.push(row);
      }
      body.replaceChildren(...bodyRows);

      const filteredCount = table.getFilteredRowModel().rows.length;
      count.textContent = filteredCount + (filteredCount === 1 ? " row" : " rows");
      if (options.pagination) {
        const pageCount = Math.max(1, table.getPageCount());
        page.textContent = "Page " + (table.getState().pagination.pageIndex + 1) + " of " + pageCount;
        first.disabled = previous.disabled = !table.getCanPreviousPage();
        next.disabled = last.disabled = !table.getCanNextPage();
      }
    }

    node.replaceChildren(toolbar, scroll);
    if (options.pagination) node.append(pagination);
    render();
    return () => node.replaceChildren();
  }

  function renderVisibleTables(scope) {
    if (!window.TableCore) return;
    scope.querySelectorAll(".data-table[data-component-id]").forEach((node) => {
      const id = node.dataset.componentId;
      if (renderedTables.has(id) || !isVisible(node)) return;
      renderedTables.add(id);
      fetchJson(dataUrl(id)).then((rows) => {
        if (!active) return;
        tableCleanups.add(createTableView(node, rows));
      }).catch((error) => {
        if (error.name !== "AbortError" && active) node.textContent = "Table is temporarily unavailable";
      });
    });
  }

  function initialiseDownloads() {
    document.querySelectorAll("[data-table-download]").forEach((link) => {
      link.href = downloadUrl(link.dataset.tableDownload);
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
      renderVisiblePlotly(scope);
      renderVisibleTables(scope);
    });
  }

  initialiseTabs();
  initialiseDownloads();
  initialiseDeleteControls();
  queueRender(document);
})();
