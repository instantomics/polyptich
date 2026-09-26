import importlib.util
from pathlib import Path


def load_components_module():
    path = Path(__file__).parents[1] / "src" / "polyptich" / "www" / "components.py"
    spec = importlib.util.spec_from_file_location("polyptich_www_components", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


components = load_components_module()


def test_thumbnail_card_renders_image_and_badges():
    html = components.thumbnail_card(
        "Dataset A",
        href="../dataset_a/",
        media="preview.png",
        image_label="Preview",
        description="Linked card",
        badges=["PBMC", "v1"],
    )

    assert (
        'class="component card shadow-sm www-scenario-card linked-card text-decoration-none"'
        in html
    )
    assert "badge rounded-pill text-bg-light" in html
    assert 'src="preview.png"' in html
    assert "Dataset A" in html
    assert "Linked card" in html
    assert "PBMC" in html


def test_panel_progress_and_matrix_helpers_render_expected_structure():
    progress = components.progress_list(
        [{"label": "A", "percent": 25, "value": "25%"}],
        title="Composition",
        collapsible=True,
    )
    matrix = components.matrix_table(
        values=[[1, 0.5], [0.5, 1]],
        row_labels=["A", "B"],
        col_labels=["A", "B"],
        title="Correlation",
    )

    assert "www-panel" in progress
    assert "card-header" in progress
    assert "www-bar-fill" in progress
    assert "Composition" in progress
    assert "www-matrix-table" in matrix
    assert "table table-sm" in matrix
    assert "Correlation" in matrix
