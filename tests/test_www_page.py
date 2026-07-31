import importlib.util
import json
from pathlib import Path

import pytest


def load_page_class():
    path = Path(__file__).parents[1] / "src" / "polyptich" / "www" / "page.py"
    spec = importlib.util.spec_from_file_location("polyptich_www_page", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Page


Page = load_page_class()


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


def test_tabs_preserve_insertion_order(tmp_path):
    page = Page(tmp_path / "www" / "report")
    section = page.section("QC")
    tabs = section.tabs("Samples")
    tabs.add_tab("Sample A").add_html("a", title="Plot A")
    tabs.add_tab("Sample B").add_html("b", title="Plot B")

    html = (tmp_path / "www" / "report" / "index.html").read_text()
    assert html.index("Sample A") < html.index("Sample B")
    assert 'role="tab"' in html


def test_cards_can_contain_arbitrary_html_and_links(tmp_path):
    page = Page(tmp_path / "www" / "report")
    page.add_card('<img src="preview.png" alt="Preview"><p>open me</p>', title="Preview", href="../other/")

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
    assert (tmp_path / "www" / "report" / component["asset"]).exists()
    assert not (tmp_path / "www" / "report" / "assets").exists()
