"""Tests for channel message handling and sandbox cleanup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from channels import handler
from channels.base import InboundMessage


class FakeSandbox:
    """Record whether the sandbox was stopped."""

    def __init__(self) -> None:
        """Initialize the stop flag."""
        self.stopped = False

    def stop(self) -> None:
        """Mark the sandbox as reclaimed."""
        self.stopped = True


class FakeAgent:
    """Return a fixed final message."""

    def __init__(self, reply: str = "reply") -> None:
        """Store the reply text."""
        self.reply = reply

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Return a state with one assistant message."""
        return {"messages": [SimpleNamespace(content=self.reply)]}


def test_handle_message_stops_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every handled message must reclaim its sandbox."""
    sandbox = FakeSandbox()

    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FakeAgent, FakeSandbox, object, str]:
        """Return fakes instead of building a real agent."""
        return FakeAgent(), sandbox, object(), "/home/agent"

    monkeypatch.setattr(handler, "build_agent", fake_build_agent)

    reply = asyncio.run(handler.handle_message(InboundMessage(
        channel="feishu", user_id="ou_test", text="hi", conversation_id="oc_test",
    ), None, None))

    assert reply == "reply"
    assert sandbox.stopped is True


def test_handle_message_stops_sandbox_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox cleanup must run even when the agent raises."""
    sandbox = FakeSandbox()

    class FailingAgent:
        """Agent double that always raises."""

        async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            """Raise to exercise the cleanup path."""
            raise RuntimeError("boom")

    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FailingAgent, FakeSandbox, object, str]:
        """Return the failing agent and sandbox double."""
        return FailingAgent(), sandbox, object(), "/home/agent"

    monkeypatch.setattr(handler, "build_agent", fake_build_agent)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(handler.handle_message(InboundMessage(
            channel="feishu", user_id="ou_test", text="hi", conversation_id="oc_test",
        ), None, None))

    assert sandbox.stopped is True