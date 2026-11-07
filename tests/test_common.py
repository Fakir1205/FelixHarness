"""Regression tests for scripts._common."""

import asyncio

import pytest

import agent.main
from scripts._common import devmate_agent


class FakeSandbox:
    """Minimal sandbox double that records stop calls."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        """Mark the sandbox as reclaimed."""
        self.stopped = True


class FakeAgent:
    """Minimal agent double."""


def test_devmate_agent_passes_arguments_and_reclaims_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper should forward arguments and stop the sandbox on exit."""
    sandbox = FakeSandbox()
    calls: dict[str, object] = {}

    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FakeAgent, FakeSandbox, object, str]:
        """Mimic the current build_agent contract."""
        calls["thread_id"] = thread_id
        calls["kwargs"] = kwargs
        return FakeAgent(), sandbox, object(), "/home/daytona"

    monkeypatch.setattr(agent.main, "build_agent", fake_build_agent)

    async def run() -> None:
        async with devmate_agent("test-thread", user_id="alice", channel="cli") as current:
            assert isinstance(current, FakeAgent)

    asyncio.run(run())

    assert calls["thread_id"] == "test-thread"
    assert calls["kwargs"]["user_id"] == "alice"
    assert calls["kwargs"]["channel"] == "cli"
    assert sandbox.stopped is True


def test_devmate_agent_reclaims_sandbox_when_body_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper should reclaim the sandbox even when the body raises."""
    sandbox = FakeSandbox()

    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FakeAgent, FakeSandbox, object, str]:
        """Return the sandbox double used by the test."""
        return FakeAgent(), sandbox, object(), "/home/daytona"

    monkeypatch.setattr(agent.main, "build_agent", fake_build_agent)

    async def run() -> None:
        async with devmate_agent("test-thread"):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run())

    assert sandbox.stopped is True
