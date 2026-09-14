"""Regression checks for the Display Compliance hub integration."""

from pathlib import Path
import subprocess
import sys

from streamlit.testing.v1 import AppTest

from display_compliance.storage import LocalBaselineStorage


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_storage_and_imports_from_another_working_directory(tmp_path):
    script = """
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import streamlit as st
with patch.object(st, 'title', side_effect=AssertionError('UI at import')), \
     patch.object(st, 'set_page_config', side_effect=AssertionError('Config at import')):
    import display_compliance
    import display_compliance.page
    import shelf_audit
    import shelf_audit.page
from display_compliance.baseline import create_baseline
from display_compliance.storage import LocalBaselineStorage
assert LocalBaselineStorage().root == Path(sys.argv[1]) / 'data/display_compliance/baselines'
assert 'torch' not in sys.modules and 'sam2' not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-B", "-c", script, str(PROJECT_ROOT)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert LocalBaselineStorage(root=tmp_path).root == tmp_path


def test_hub_module_navigation_and_invalid_route(monkeypatch, tmp_path):
    from display_compliance import page

    monkeypatch.setattr(page, "LocalBaselineStorage", lambda: LocalBaselineStorage(tmp_path))
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run()
    assert not app.exception
    assert app.session_state["hub_route"] == "home"
    for route in ("shelf_audit", "display_compliance", "shelf_audit"):
        app.button(key=f"hub_open_{route}").click().run()
        assert not app.exception
        assert app.session_state["hub_route"] == route
        if route == "display_compliance":
            assert app.text_input(key="display_compliance_baseline_name") is not None
        else:
            assert app.radio(key="shelf_audit_mode") is not None
        app.button(key="hub_home").click().run()
        assert not app.exception
        assert app.session_state["hub_route"] == "home"
    app.session_state["hub_route"] = "invalid"
    app.run()
    assert not app.exception
    assert app.session_state["hub_route"] == "home"
