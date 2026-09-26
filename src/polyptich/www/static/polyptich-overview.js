(function () {
  let active = true;
  const requestControllers = new Set();
  const config = JSON.parse(document.getElementById("polyptich-overview-config").textContent);
  const controls = document.getElementById("overview-controls");
  const grid = document.getElementById("overview-grid");
  const summary = document.getElementById("overview-summary");
  const loadButton = document.getElementById("overview-load");
  const state = { offset: 0, limit: config.pageSize || 24, total: 0 };

  function unmount() {
    active = false;
    window.removeEventListener("polyptich:before-page-swap", unmount);
    requestControllers.forEach((controller) => controller.abort());
    requestControllers.clear();
  }

  window.addEventListener("polyptich:before-page-swap", unmount);

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null) continue;
      if (key === "class") node.className = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) node.append(child);
    return node;
  }

  function endpointUrl(reset) {
    const url = new URL("items", window.location.href);
    const form = new FormData(document.getElementById("overview-form"));
    for (const [key, value] of form.entries()) {
      if (value !== "") url.searchParams.set(key, value);
    }
    url.searchParams.set("offset", reset ? 0 : state.offset);
    url.searchParams.set("limit", state.limit);
    return url;
  }

  function renderControls() {
    const fields = [
      el("label", { class: "overview-field" }, [
        el("span", {}, ["Search"]),
        el("input", { name: "q", type: "search", placeholder: "Search cards" }),
      ]),
    ];
    for (const filter of config.filters || []) {
      if (filter.type === "range") {
        fields.push(el("label", { class: "overview-field" }, [el("span", {}, [filter.label || filter.key]), el("input", { name: "min_" + filter.key, type: "number", placeholder: "Min" })]));
        fields.push(el("label", { class: "overview-field" }, [el("span", {}, [filter.label || filter.key]), el("input", { name: "max_" + filter.key, type: "number", placeholder: "Max" })]));
      } else {
        const select = el("select", { name: "f_" + filter.key }, [el("option", { value: "" }, ["Any"])]);
        for (const option of filter.options || []) select.append(el("option", { value: option }, [option]));
        fields.push(el("label", { class: "overview-field" }, [el("span", {}, [filter.label || filter.key]), select]));
      }
    }
    if ((config.sorts || []).length) {
      const sort = el("select", { name: "sort" }, [el("option", { value: "" }, ["Default"])]);
      for (const option of config.sorts) sort.append(el("option", { value: option.key }, [option.label || option.key]));
      fields.push(el("label", { class: "overview-field" }, [el("span", {}, ["Sort"]), sort]));
      fields.push(el("label", { class: "overview-field" }, [el("span", {}, ["Order"]), el("select", { name: "order" }, [el("option", { value: "asc" }, ["Ascending"]), el("option", { value: "desc" }, ["Descending"])])]));
    }
    const form = el("form", { id: "overview-form", class: "overview-form" }, fields);
    form.addEventListener("input", () => load(true));
    form.addEventListener("change", () => load(true));
    controls.append(form);
  }

  function renderItem(item) {
    const link = el("a", { class: "component card www-scenario-card linked-card", href: item.href || "#" });
    if (item.media) {
      const wrap = el("div", { class: "www-thumbnail-wrap" });
      wrap.append(el("img", { src: item.media, alt: item.title || "Preview" }));
      link.append(wrap);
    }
    link.append(el("span", { class: "www-scenario-title" }, [item.title || "Untitled"]));
    if (item.description) link.append(el("span", { class: "www-scenario-description" }, [item.description]));
    if ((item.badges || []).length) {
      link.append(el("div", { class: "www-badge-row" }, item.badges.map((badge) => el("span", { class: "www-badge www-badge-neutral" }, [badge]))));
    }
    return link;
  }

  function load(reset) {
    if (!active) return;
    if (reset) {
      state.offset = 0;
      grid.innerHTML = "";
    }
    const controller = new AbortController();
    requestControllers.add(controller);
    fetch(endpointUrl(reset), {signal: controller.signal}).then((response) => response.json()).then((payload) => {
      if (!active) return;
      state.total = payload.total;
      state.offset = payload.offset + payload.items.length;
      for (const item of payload.items) grid.append(renderItem(item));
      summary.textContent = `${Math.min(state.offset, state.total)} of ${state.total} item${state.total === 1 ? "" : "s"}`;
      loadButton.hidden = state.offset >= state.total;
    }).catch((error) => {
      if (error.name !== "AbortError") summary.textContent = "Overview is temporarily unavailable";
    }).finally(() => requestControllers.delete(controller));
  }

  renderControls();
  loadButton.addEventListener("click", () => load(false));
  load(true);
})();
