import json
from pathlib import Path

import pytest

from polyptich.www.page import Page


def read_manifest(path):
    return json.loads((path / "manifest.json").read_text())


def test_page_writes_manifest_immediately(tmp_path):
    page = Page(tmp_path / "www" / "report", title="Analysis")
    section = page.section("QC")
    section.add_html("<strong>ok</strong>", title="Summary")

    report = tmp_path / "www" / "report"
    manifest = read_manifest(report)
    assert manifest["schema"] == "polyptich.www.report"
    assert manifest["schema_version"] == 1
    assert manifest["title"] == "Analysis"
    assert "components" not in manifest
    html = (report / "index.html").read_text()
    assert 'id="qc"' in html
    assert "<strong>ok</strong>" in html
    assert html.count("data-polyptich-navigation-shell") == 1
    assert "/static/polyptich-navigation.css" in html
    assert "/static/polyptich-navigation.js" in html
    assert '<aside class="toc">' not in html


def test_overwrite_deletes_existing_folder(tmp_path):
    report = tmp_path / "www" / "report"
    report.mkdir(parents=True)
    (report / "unknown.txt").write_text("delete me")

    Page(report, title="Fresh", overwrite=True)

    assert not (report / "unknown.txt").exists()
    assert read_manifest(report)["title"] == "Fresh"


def test_index_html_is_rewritten_when_components_are_added(tmp_path):
    report = tmp_path / "www" / "report"
    page = Page(report, title="First")
    page.add_html("one", title="One")
    page.add_html("two", title="Two")

    html = (report / "index.html").read_text()
    assert html.index("one") < html.index("two")
    assert read_manifest(report)["assets"] == {}


def test_untitled_html_is_unboxed_and_has_no_toc_heading(tmp_path):
    page = Page(tmp_path / "www" / "report", title="Report")
    section = page.section("QC")
    section.add_html("untitled content")

    html = (tmp_path / "www" / "report" / "index.html").read_text()
    assert 'class="component component-html"' in html
    assert '<h3 class="component-title">html</h3>' not in html


def test_buttons_are_not_wrapped_in_cards(tmp_path):
    page = Page(tmp_path / "www" / "report")
    page.add_button("Open", href="target/")

    html = (tmp_path / "www" / "report" / "index.html").read_text()
    assert 'class="component component-button"' in html
    assert '<article class="component card" id="button"' not in html


def test_tabs_preserve_insertion_order(tmp_path):
    page = Page(tmp_path / "www" / "report")
    section = page.section("QC")
    tabs = section.tabs("Samples")
    tabs.add_tab("Sample A").add_html("a", title="Plot A")
    tabs.add_tab("Sample B").add_html("b", title="Plot B")

    html = (tmp_path / "www" / "report" / "index.html").read_text()
    assert html.index("Sample A") < html.index("Sample B")
    assert 'role="tab"' in html
    assert (
        'id="sample-a-tab" type="button" role="tab" aria-selected="true" '
        'aria-controls="sample-a" tabindex="0" data-tab="sample-a"'
    ) in html
    assert (
        'id="sample-b-tab" type="button" role="tab" aria-selected="false" '
        'aria-controls="sample-b" tabindex="-1" data-tab="sample-b"'
    ) in html
    assert (
        'class="tab-panel active" id="sample-a" role="tabpanel" '
        'aria-labelledby="sample-a-tab" tabindex="0"'
    ) in html
    assert (
        'class="tab-panel" id="sample-b" role="tabpanel" '
        'aria-labelledby="sample-b-tab" tabindex="0" hidden'
    ) in html


def test_tab_script_supports_roving_keyboard_navigation_and_persisted_selection():
    script = (
        Path(__file__).parents[1]
        / "src"
        / "polyptich"
        / "www"
        / "static"
        / "polyptich-www.js"
    ).read_text()

    for key in ["ArrowLeft", "ArrowRight", "Home", "End"]:
        assert f'"{key}"' in script
    assert "button.tabIndex = selected ? 0 : -1" in script
    assert "panel.hidden = !selected" in script
    assert "history.replaceState(history.state" in script


def test_cards_can_contain_arbitrary_html_and_links(tmp_path):
    page = Page(tmp_path / "www" / "report")
    page.add_card(
        '<img src="preview.png" alt="Preview"><p>open me</p>', title="Preview", href="../other/"
    )

    html = (tmp_path / "www" / "report" / "index.html").read_text()
    assert '<a class="component card linked-card"' in html
    assert 'href="../other/"' in html
    assert '<img src="preview.png" alt="Preview">' in html


def test_dataframe_table_writes_parquet_with_index_columns(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    df = pd.DataFrame({"value": [1, 2]}, index=pd.Index(["a", "b"], name="cell"))
    Page(tmp_path / "www" / "report").add_table(df, title="Cells")

    manifest = read_manifest(tmp_path / "www" / "report")
    component = manifest["assets"]["cells"]
    assert component["type"] == "table"
    assert component["columns"] == ["cell", "value"]
    assert component["row_count"] == 2
    assert component["uncompressed_bytes"] > 0
    assert component["column_types"] == {"cell": "string", "value": "integer"}
    assert (tmp_path / "www" / "report" / component["asset"]).exists()
    assert not (tmp_path / "www" / "report" / "assets").exists()


def test_dataframe_table_writes_tanstack_configuration(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    page = Page(tmp_path / "www" / "report")
    page.add_table(
        pd.DataFrame({"cell": ["a"], "score": [1.5]}),
        visible_columns=["cell"],
        options={"page_size": 10, "searchable": False},
        column_options={"score": {"label": "Score", "align": "right"}},
    )

    report = tmp_path / "www" / "report"
    component = read_manifest(report)["assets"]["table"]
    assert component["options"] == {"page_size": 10, "searchable": False}
    assert component["column_options"] == {
        "score": {"label": "Score", "align": "right"}
    }
    html = (report / "index.html").read_text()
    assert "@tanstack/table-core@8.21.3" in html
    assert "tabulator" not in html.lower()
    assert 'class="data-table"' in html
    assert 'data-options="{&quot;page_size&quot;: 10, &quot;searchable&quot;: false}"' in html


def test_matplotlib_defaults_to_tight_bounds(tmp_path):
    class Figure:
        def __init__(self):
            self.kwargs = None

        def savefig(self, _path, **kwargs):
            self.kwargs = kwargs

    figure = Figure()
    Page(tmp_path / "www" / "report").add_matplotlib(figure, close=False)

    assert figure.kwargs["bbox_inches"] == "tight"
    assert figure.kwargs["transparent"] is True


def test_matplotlib_tight_bounds_can_be_overridden(tmp_path):
    class Figure:
        def __init__(self):
            self.kwargs = None

        def savefig(self, _path, **kwargs):
            self.kwargs = kwargs

    figure = Figure()
    Page(tmp_path / "www" / "report").add_matplotlib(
        figure, close=False, bbox_inches=None
    )

    assert figure.kwargs["bbox_inches"] is None


def test_table_script_upgrades_persisted_tabulator_placeholders():
    script = (
        Path(__file__).parents[1]
        / "src"
        / "polyptich"
        / "www"
        / "static"
        / "polyptich-www.js"
    ).read_text()

    assert '".data-table[data-component-id], .table[data-component-id]"' in script
    assert 'node.classList.remove("table")' in script
    assert "function loadTableCore()" in script


def test_report_renders_navigation_provenance_and_permalinks(tmp_path):
    page = Page(
        tmp_path / "www" / "report",
        title="Analysis",
        author="Ada",
        breadcrumbs=[("Project", "/project"), ("Analysis", None)],
        provenance={"Git commit": "abc123"},
        source_url="analysis.ipynb",
        previous={"label": "QC", "href": "../qc/"},
        next={"label": "Markers", "href": "../markers/"},
    )
    page.section("Results").add_html("ok", title="Summary")

    html = (tmp_path / "www" / "report" / "index.html").read_text()
    assert '<nav class="report-breadcrumbs" aria-label="Breadcrumb">' in html
    assert '<header class="report-header" id="report-title">' in html
    assert 'class="anchor-link" href="#results"' in html
    assert 'aria-label="Report tools"' in html
    assert 'class="report-previous" href="../qc/">QC</a>' in html
    assert 'class="report-next" href="../markers/">Markers</a>' in html
    assert 'class="report-source" href="analysis.ipynb">Source</a>' in html
    assert "Report provenance" in html
    assert "Git commit</dt><dd>abc123" in html
    assert '<a href="manifest.json">manifest.json</a>' in html


def test_matplotlib_stores_dpi_independent_display_dimensions(tmp_path):
    pyplot = pytest.importorskip("matplotlib.pyplot")
    figure, axis = pyplot.subplots(figsize=(4, 2))
    axis.plot([0, 1], [0, 1])

    page = Page(tmp_path / "www" / "report")
    component = page.add_matplotlib(
        figure,
        title="Small plot",
        format="png",
        dpi=200,
        caption="A caption",
    )

    display = component["display"]
    assert display["mode"] == "intrinsic"
    assert display["pixel_width"] > display["width_css_px"]
    assert display["width_css_px"] == pytest.approx(
        display["pixel_width"] / 200 * 96,
        abs=0.01,
    )
    manifest_component = read_manifest(tmp_path / "www" / "report")["assets"]["small-plot"]
    assert manifest_component["caption"] == "A caption"
    assert manifest_component["downloads"][0]["format"] == "png"
    html = (tmp_path / "www" / "report" / "index.html").read_text()
    assert 'data-plot-display="intrinsic"' in html
    assert "Fullscreen" in html
    assert "Download PNG" in html
    assert "<figcaption>A caption</figcaption>" in html


def test_table_rejects_unknown_configuration_columns(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    page = Page(tmp_path / "www" / "report")

    with pytest.raises(ValueError, match="Unknown visible table columns"):
        page.add_table(pd.DataFrame({"value": [1]}), visible_columns=["missing"])


def test_table_normalizes_legacy_large_page_sizes(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    page = Page(tmp_path / "www" / "report")
    page.add_table(pd.DataFrame({"value": [1]}), options={"page_size": 5000})

    component = read_manifest(tmp_path / "www" / "report")["assets"]["table"]
    assert component["options"]["page_size"] == 1000


def test_plot_display_mode_is_validated(tmp_path):
    class Figure:
        dpi = 100

        def savefig(self, path, **_kwargs):
            Path(path).write_text('<svg width="72pt" height="72pt"></svg>')

    with pytest.raises(ValueError, match="Plot display"):
        Page(tmp_path / "www" / "report").add_matplotlib(
            Figure(), close=False, display="huge"
        )


def test_report_script_preserves_combined_fragment_state_and_prefixes():
    script = (
        Path(__file__).parents[1]
        / "src"
        / "polyptich"
        / "www"
        / "static"
        / "polyptich-www.js"
    ).read_text()

    assert 'const reportScriptUrl = document.currentScript?.src || ""' in script
    assert 'const suffix = "/static/polyptich-www.js"' in script
    assert 'params.set("open", ids.join(","))' in script
    assert 'window.addEventListener("polyptich:report-reveal", revealTarget)' in script
    assert "tableUrlAppliers.forEach((apply) => apply())" in script
    assert 'filterFn: "polyptich"' in script
