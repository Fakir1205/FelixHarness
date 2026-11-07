"""Regression tests for agent.dispatcher."""

import asyncio

import pytest

from agent import dispatcher
import sandbox.manager as sandbox_manager


class FakeSandbox:
    """Minimal sandbox double that records stop calls."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        """Mark the sandbox as reclaimed."""
        self.stopped = True


class FakeAgent:
    """Agent double that echoes the incoming messages."""

    async def ainvoke(self, payload: dict, config: dict) -> dict:
        """Return messages unchanged for assertions."""
        return {"messages": payload["messages"], "config": config}


def test_run_issue_awaits_build_agent_and_unpacks_four_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_issue should await build_agent and accept its four return values."""
    sandbox = FakeSandbox()
    calls: dict[str, object] = {}

    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FakeAgent, FakeSandbox, object, str]:
        """Mimic the current async build_agent contract."""
        calls["thread_id"] = thread_id
        calls["kwargs"] = kwargs
        return FakeAgent(), sandbox, object(), "/home/daytona"

    monkeypatch.setattr(dispatcher, "build_agent", fake_build_agent)

    result = asyncio.run(dispatcher.run_issue("hello", user_id="alice", channel="cli"))

    assert result["messages"][0]["content"] == "hello"
    assert calls["kwargs"]["user_id"] == "alice"
    assert sandbox.stopped is True


class FailingAgent:
    """Agent double that raises during invocation."""

    async def ainvoke(self, payload: dict, config: dict) -> dict:
        """Simulate an execution failure."""
        raise RuntimeError("boom")


def test_run_issue_stops_sandbox_when_agent_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_issue should still reclaim the sandbox when the agent fails."""
    sandbox = FakeSandbox()

    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FailingAgent, FakeSandbox, object, str]:
        """Return an agent that raises on invocation."""
        return FailingAgent(), sandbox, object(), "/home/daytona"

    monkeypatch.setattr(dispatcher, "build_agent", fake_build_agent)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(dispatcher.run_issue("hello"))

    assert sandbox.stopped is True


def test_run_issue_downloads_artifacts_with_returned_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_issue should download artifacts through the returned backend."""
    sandbox = FakeSandbox()
    backend = object()
    calls: dict[str, object] = {}

    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FakeAgent, FakeSandbox, object, str]:
        """Return the unified sandbox/backend contract."""
        return FakeAgent(), sandbox, backend, "/home/daytona"

    def fake_download_artifacts(current_backend: object, paths: list[str]) -> dict[str, bytes]:
        """Record the backend and requested paths."""
        calls["backend"] = current_backend
        calls["paths"] = paths
        return {paths[0]: b"artifact"}

    monkeypatch.setattr(dispatcher, "build_agent", fake_build_agent)
    monkeypatch.setattr(sandbox_manager, "download_artifacts", fake_download_artifacts)

    result = asyncio.run(dispatcher.run_issue("hello", fetch_paths=["/home/daytona/result.txt"]))

    assert calls["backend"] is backend
    assert calls["paths"] == ["/home/daytona/result.txt"]
    assert result["artifacts"] == {"/home/daytona/result.txt": b"artifact"}
    assert sandbox.stopped is True
