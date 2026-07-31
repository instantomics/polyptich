import importlib
import json
import sys
import types
from pathlib import Path


def load_examples_module():
    root = Path(__file__).parents[1]
    package = types.ModuleType("polyptich")
    package.__path__ = [str(root / "src" / "polyptich")]
    www_package = types.ModuleType("polyptich.www")
    www_package.__path__ = [str(root / "src" / "polyptich" / "www")]
    sys.modules.setdefault("polyptich", package)
    sys.modules.setdefault("polyptich.www", www_package)
    return importlib.import_module("polyptich.www.examples")


def test_write_examples_creates_static_and_dynamic_examples(tmp_path):
    examples = load_examples_module()

    root = examples.write_examples(tmp_path / "www" / "polyptich_examples")

    component_manifest = json.loads((root / "component_library" / "manifest.json").read_text())
    overview_manifest = json.loads((root / "dataset_overview" / "manifest.json").read_text())
    overview_items = json.loads((root / "dataset_overview" / "items.json").read_text())

    assert (root / "component_library" / "index.html").exists()
    assert component_manifest["schema"] == "polyptich.www.report"
    assert overview_manifest["schema"] == "polyptich.www.endpoint"
    assert overview_manifest["endpoint_id"] == "polyptich.overview-grid"
    assert len(overview_items) == 36
