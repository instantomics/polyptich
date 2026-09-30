# %%
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px

import polyptich as pp
import polyptich.www as www


page = www.Page(
    pp.paths.get_www() / "my_report",
    title="My Analysis",
    author="Analysis team",
    breadcrumbs=[("Examples", "/"), ("My Analysis", None)],
    provenance={"Dataset": "Example data", "Git commit": "development"},
    source_url="analysis.ipynb",
)

qc = page.section("QC")

qc.add_html(
    www.components.grid(
        www.components.card("300 cells passed filtering", title="Cells"),
        www.components.card("3 markers reviewed", title="Markers"),
        www.components.card(
            """
            <p>Any HTML is fine here, including lists:</p>
            <ul><li>QC passed</li><li>UMAP available</li></ul>
            """,
            title="Custom HTML",
        ),
        columns="3",
    ),
    title="Summary",
)
qc.add_html(
    www.components.grid(
        www.components.card(
            www.components.image(
                "https://placehold.co/640x360?text=QC+Preview",
                alt="QC preview",
                caption="Images can be remote URLs or relative assets next to the report.",
            ),
            title="Image Card",
        ),
        www.components.card(
            "Click this card to open another report, HTML file, or external page.",
            title="Linked Card",
            href="../another_report/",
        ),
        www.components.card(www.components.badge("Ready", tone="success"), title="Status"),
        columns="3",
    )
)
qc.add_html(
    www.components.grid(
        www.components.thumbnail_card(
            "PBMC overview",
            href="../another_report/",
            media="https://placehold.co/640x360?text=UMAP+Thumbnail",
            image_label="Example view",
            description="A manuscript-style linked card with thumbnail, description, and badges.",
            badges=["PBMC", "Doublets", "v1"],
        ),
        www.components.panel(
            www.components.key_value_table(
                {
                    "Cells": 12034,
                    "Genes": 3120,
                    "Batches": 4,
                }
            ),
            title="Summary",
        ),
        columns="2",
    )
)
qc.add_html(
    www.components.grid(
        www.components.progress_list(
            [
                {"label": "Singlets", "percent": 78, "value": "78%"},
                {"label": "Doublets", "percent": 12, "value": "12%"},
                {"label": "Unknown", "percent": 10, "value": "10%"},
            ],
            title="Composition",
            collapsible=True,
        ),
        www.components.matrix_table(
            values=[[1.0, 0.72, 0.28], [0.72, 1.0, 0.41], [0.28, 0.41, 1.0]],
            row_labels=["A", "B", "C"],
            col_labels=["A", "B", "C"],
            title="Marker Correlation",
        ),
        columns="2",
    )
)
qc.add_html(
    www.components.callout(
        "This report is generated as HTML. The manifest only stores metadata and asset references.",
        title="HTML-first reports",
    )
)
qc.add_button("Open project", href="https://github.com/saeyslab/polyptich", variant="secondary")

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [4, 5, 6])
plotly_fig = px.scatter(x=[1, 2, 3], y=[4, 5, 6])
df = pd.DataFrame({"Marker": ["A", "B", "C"] * 100, "Value": [10, 20, 30] * 100})

qc.add_matplotlib(
    fig,
    title="Overview",
    caption="A high-resolution figure displayed at its intended physical size.",
)
qc.add_plotly(
    plotly_fig,
    title="Interactive UMAP",
    caption="Use fullscreen mode or the Plotly toolbar for closer inspection.",
)
qc.add_table(
    df,
    title="Markers",
    options={
        "page_size": 25,
        "density": "compact",
        "pinned_columns": {"left": ["index"]},
    },
    column_options={
        "Marker": {"label": "Marker gene", "width": 180},
        "Value": {"align": "right", "format": ".1f", "width": 120},
    },
)

tabs = qc.tabs("Samples")

fig_a, ax_a = plt.subplots()
ax_a.plot([1, 2, 3], [4, 5, 6])
tabs.add_tab("Sample A").add_matplotlib(fig_a, title="Sample A QC")

fig_b, ax_b = plt.subplots()
ax_b.plot([1, 2, 3], [4, 5, 6])
tabs.add_tab("Sample B").add_matplotlib(fig_b, title="Sample B QC")
# %%
