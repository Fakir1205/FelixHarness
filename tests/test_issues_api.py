"""Regression tests for the issues API route."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.routes.issues as issues
from api.app import app
from api.deps import get_checkpointer, get_store


class FakeSandbox:
    """Sandbox double that records whether stop was called."""

    def __init__(self) -> None:
        """Initialize the sandbox as running."""
        self.stopped = False

    def stop(self) -> None:
        """Mark the sandbox as stopped."""
        self.stopped = True


class FakeAgent:
    """Agent double that returns a fixed reply."""

    async def ainvoke(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Return one assistant message."""
        return {"messages": [SimpleNamespace(content="done")]}


class FailingAgent:
    """Agent double that raises during invocation."""

    async def ainvoke(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Simulate an execution failure."""
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def override_shared_dependencies() -> Iterator[None]:
    """Replace lifespan-backed dependencies for isolated route tests."""
    app.dependency_overrides[get_checkpointer] = lambda: "checkpointer"
    app.dependency_overrides[get_store] = lambda: "store"
    yield
    app.dependency_overrides.clear()


def test_submit_issue_stops_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route should stop the sandbox after a successful request."""
    sandbox = FakeSandbox()
    captured: dict[str, Any] = {}

    async def fake_build_agent(thread_id: str, **kwargs: Any) -> tuple[FakeAgent, FakeSandbox, object, str]:
        """Return a fake agent and record the lifecycle arguments."""
        captured["thread_id"] = thread_id
        captured["kwargs"] = kwargs
        return FakeAgent(), sandbox, object(), "/home/daytona"

    monkeypatch.setattr(issues, "build_agent", fake_build_agent)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/issues",
        json={"issue": "hello", "thread_id": "thread-1", "user_id": "alice"},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "done"
    assert captured["thread_id"] == "thread-1"
    assert captured["kwargs"]["user_id"] == "alice"
    assert sandbox.stopped is True


def test_submit_issue_stops_sandbox_when_agent_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route should stop the sandbox even when agent invocation fails."""
    sandbox = FakeSandbox()

    async def fake_build_agent(thread_id: str, **kwargs: Any) -> tuple[FailingAgent, FakeSandbox, object, str]:
        """Return an agent that raises during invocation."""
        return FailingAgent(), sandbox, object(), "/home/daytona"

    monkeypatch.setattr(issues, "build_agent", fake_build_agent)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/issues", json={"issue": "hello"})

    assert response.status_code == 500
    assert sandbox.stopped is True
