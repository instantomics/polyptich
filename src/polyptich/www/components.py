from html import escape


def attrs(**attributes):
    parts = []
    for key, value in attributes.items():
        if value is None or value is False:
            continue
        name = key.rstrip("_").replace("_", "-")
        if value is True:
            parts.append(name)
        else:
            parts.append(f'{name}="{escape(str(value), quote=True)}"')
    return "" if not parts else " " + " ".join(parts)


def tag(name, content="", **attributes):
    return f"<{name}{attrs(**attributes)}>{content}</{name}>"


def card(content="", title=None, href=None, class_=None):
    heading = (
        tag("h3", escape(str(title)), class_="component-title card-title") if title else ""
    )
    css = "component card shadow-sm" if class_ is None else f"component card shadow-sm {class_}"
    if href:
        return tag(
            "a",
            heading + str(content),
            href=href,
            class_=f"{css} linked-card text-decoration-none",
        )
    return tag("article", heading + str(content), class_=css)


def panel(content="", title=None, collapsible=False, open=True):
    header = (
        tag(
            "div",
            tag("span", escape(str(title or "")), class_="www-panel-title"),
            class_="www-panel-header card-header",
        )
        if title
        else ""
    )
    if collapsible:
        summary = tag(
            "summary",
            tag("span", escape(str(title or "")), class_="www-panel-title"),
            class_="www-panel-header card-header",
        )
        return tag(
            "section",
            tag("details", summary + str(content), open=open),
            class_="www-panel card",
        )
    return tag("section", header + str(content), class_="www-panel card")


def button(label, href=None, variant="primary", **attributes):
    bootstrap_variant = {"subtle": "light"}.get(variant, variant)
    css = f"www-button www-button-{variant} btn btn-{bootstrap_variant}"
    if href:
        return tag("a", escape(str(label)), href=href, class_=css, **attributes)
    return tag("button", escape(str(label)), type="button", class_=css, **attributes)


def link(label, href, **attributes):
    return tag("a", escape(str(label)), href=href, **attributes)


def image(src, alt="", caption=None, **attributes):
    img = f'<img src="{escape(str(src), quote=True)}" alt="{escape(str(alt), quote=True)}"{attrs(**attributes)}>'
    if caption is None:
        return img
    return tag("figure", img + tag("figcaption", escape(str(caption))), class_="www-figure")


def badge(label, tone="neutral"):
    bootstrap_tone = {"neutral": "light"}.get(tone, tone)
    return tag(
        "span",
        escape(str(label)),
        class_=f"www-badge www-badge-{tone} badge rounded-pill text-bg-{bootstrap_tone}",
    )


def badge_row(*badges):
    rendered = [item if isinstance(item, str) and "<" in item else badge(item) for item in badges]
    return tag("div", "".join(map(str, rendered)), class_="www-badge-row")


def callout(content, title=None, tone="info"):
    heading = tag("strong", escape(str(title))) if title else ""
    return tag(
        "div",
        heading + str(content),
        class_=f"www-callout www-callout-{tone} alert alert-{tone}",
    )


def grid(*items, columns="auto"):
    return tag("div", "".join(map(str, items)), class_=f"www-grid www-grid-{columns}")


def thumbnail_card(title, href=None, media=None, image_label=None, description=None, badges=None):
    parts = []
    if media is not None:
        if isinstance(media, str) and media.lstrip().startswith("<"):
            thumbnail = media
        else:
            thumbnail = image(media, alt=image_label or title)
        label = tag("span", escape(str(image_label)), class_="www-thumbnail-label") if image_label else ""
        parts.append(tag("div", label + thumbnail, class_="www-thumbnail-wrap"))
    parts.append(tag("span", escape(str(title)), class_="www-scenario-title"))
    if description:
        parts.append(tag("span", escape(str(description)), class_="www-scenario-description"))
    if badges:
        parts.append(badge_row(*badges))
    return card("".join(parts), href=href, class_="www-scenario-card")


def key_value_table(items):
    if isinstance(items, dict):
        items = items.items()
    rows = "".join(tag("tr", tag("th", escape(str(key))) + tag("td", escape(str(value)))) for key, value in items)
    return tag("table", tag("tbody", rows), class_="www-kv-table table table-sm")


def progress_list(items, title=None, collapsible=False, open=True):
    rows = []
    for item in items:
        label = escape(str(item["label"]))
        value = escape(str(item.get("value", "")))
        percent = max(0, min(100, float(item.get("percent", 0))))
        rows.append(
            tag(
                "div",
                tag("span", label)
                + tag("span", tag("span", "", class_="www-bar-fill", style=f"width: {percent}%"), class_="www-bar-track")
                + tag("span", value),
                class_="www-bar-row",
            )
        )
    body = "".join(rows) if rows else tag("div", "No values", class_="empty-note")
    return panel(body, title=title, collapsible=collapsible, open=open) if title else body


def matrix_table(values, row_labels, col_labels, title=None, precision=2):
    numeric = [float(value) for row in values for value in row]
    min_value = min(numeric) if numeric else 0
    max_value = max(numeric) if numeric else 1

    def color(value):
        if max_value == min_value:
            intensity = 0.5
        else:
            intensity = (float(value) - min_value) / (max_value - min_value)
        blue = int(255 - 45 * intensity)
        red = int(248 - 68 * intensity)
        green = int(250 - 124 * intensity)
        return f"rgb({red}, {green}, {blue})"

    header = tag("tr", tag("th", "") + "".join(tag("th", escape(str(label))) for label in col_labels))
    rows = []
    for row_label, row in zip(row_labels, values):
        cells = []
        for value in row:
            formatted = f"{float(value):.{precision}f}"
            cells.append(tag("td", formatted, class_="www-matrix-cell", style=f"background:{color(value)}", title=formatted))
        rows.append(tag("tr", tag("th", escape(str(row_label))) + "".join(cells)))
    table = tag(
        "div",
        tag(
            "table",
            tag("tbody", header + "".join(rows)),
            class_="www-matrix-table table table-sm",
        ),
        class_="www-matrix-wrap table-responsive",
    )
    return panel(table, title=title) if title else table
