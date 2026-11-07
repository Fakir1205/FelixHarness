"""Contract tests for subagent backend isolation."""

from __future__ import annotations

import pytest

import subagents.profiles as profiles


def test_reviewer_uses_readonly_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only reviewer should receive the dedicated read-only filesystem backend."""
    readonly_backend = object()
    monkeypatch.setattr(profiles, "get_model_for_role", lambda role: object())

    subagents = profiles.build_subagents(
        "/home/agent",
        reviewer_backend=readonly_backend,
    )

    reviewer = next(spec for spec in subagents if spec["name"] == "reviewer")
    filesystem_middleware = reviewer["middleware"][0]
    assert filesystem_middleware.backend is readonly_backend
    assert all(
        "middleware" not in spec
        for spec in subagents
        if spec["name"] != "reviewer"
    )
