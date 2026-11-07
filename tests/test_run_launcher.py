"""Tests for the API server launcher."""

from __future__ import annotations

import pytest

import run


def test_get_loop_factory_uses_selector_on_windows() -> None:
    """Windows must use SelectorEventLoop because psycopg async rejects Proactor."""
    assert run.get_loop_factory("win32") == "asyncio:SelectorEventLoop"


def test_get_loop_factory_uses_auto_elsewhere() -> None:
    """Other platforms can keep uvicorn's automatic loop selection."""
    assert run.get_loop_factory("linux") == "auto"


def test_main_passes_compatible_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The launcher must forward the compatible loop factory to uvicorn."""
    captured: dict[str, object] = {}

    def fake_run(app_path: str, **kwargs: object) -> None:
        """Record uvicorn arguments without starting a server."""
        captured["app_path"] = app_path
        captured.update(kwargs)

    monkeypatch.setattr(run.uvicorn, "run", fake_run)
    monkeypatch.setattr(run, "get_loop_factory", lambda: "asyncio:SelectorEventLoop")

    run.main(port=8123)

    assert captured["app_path"] == "api.app:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert captured["loop"] == "asyncio:SelectorEventLoop"