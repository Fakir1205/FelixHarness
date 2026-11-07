"""Regression tests for the web branding text."""

from pathlib import Path

INDEX_HTML = Path(__file__).resolve().parents[1] / "web" / "index.html"


def test_web_branding_uses_felix_harness() -> None:
    """The page title and header brand should read Felix Harness."""
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "FelixHarness" in html
    assert "ShanYang" not in html
    assert "Claw" not in html
