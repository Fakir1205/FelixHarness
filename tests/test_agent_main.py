"""Contract tests for ``agent.main.build_agent``."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import agent.main as main
import sandbox.docker_manager as docker_manager


class DummyMiddleware:
    """Middleware double that accepts any constructor arguments."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Ignore configuration passed by the real builder."""
        self.args = args
        self.kwargs = kwargs


class DummyMCPManager:
    """MCP manager double with no remote tools."""

    @classmethod
    def from_settings(cls) -> DummyMCPManager:
        """Return an empty manager without reading external configuration."""
        return cls()

    async def get_tools(self) -> list[object]:
        """Return no MCP tools."""
        return []


def test_build_agent_returns_workdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """The builder must return the workdir expected by dispatcher and scripts."""
    backend = object()
    sandbox = object()
    client = object()
    captured: dict[str, Any] = {}

    def fake_get_sandbox(thread_id: str) -> tuple[object, object, object, str]:
        """Return a fake backend, sandbox, client, and workdir."""
        captured["thread_id"] = thread_id
        return backend, sandbox, client, "/home/daytona"

    def fake_build_subagents(
        workdir: str,
        *,
        reviewer_backend: object | None = None,
    ) -> list[dict[str, Any]]:
        """Return no subagents and record the workdir and reviewer backend."""
        captured["subagent_workdir"] = workdir
        captured["reviewer_backend"] = reviewer_backend
        return []

    def fake_create_deep_agent(**kwargs: Any) -> object:
        """Capture the builder arguments and return a fake agent."""
        captured["agent_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(sandbox_provider="daytona"))
    monkeypatch.setattr(main, "get_or_create_sandbox_backend", fake_get_sandbox)
    monkeypatch.setattr(main, "MCPManager", DummyMCPManager)
    monkeypatch.setattr(main, "build_subagents", fake_build_subagents)
    monkeypatch.setattr(main, "build_model", lambda: object())
    monkeypatch.setattr(main, "build_summary_model", lambda: object())
    monkeypatch.setattr(main, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(main, "get_tools", lambda *names: [])
    for name in (
        "TodoListMiddleware",
        "RequestContextMiddleware",
        "ToolAuditMiddleware",
        "CostMeterMiddleware",
        "SerialTaskMiddleware",
        "SummarizationMiddleware",
        "ModelCallLimitMiddleware",
    ):
        monkeypatch.setattr(main, name, DummyMiddleware)

    result = asyncio.run(main.build_agent("test-thread", user_id="alice", channel="cli"))

    assert len(result) == 4
    assert result[1] is sandbox
    assert result[2] is backend
    assert result[3] == "/home/daytona"
    assert captured["thread_id"] == "test-thread"
    assert captured["agent_kwargs"]["backend"] is backend
    assert captured["subagent_workdir"] == "/home/daytona"
    assert captured["reviewer_backend"] is None
    assert captured["agent_kwargs"]["skills"] == ["/home/daytona/skills"]
    assert captured["agent_kwargs"]["memory"] == ["/home/daytona/AGENTS.md"]


class FakeDockerSandbox:
    """Docker backend double that also carries runtime identity."""

    workdir = "/home/agent"


def test_build_agent_returns_docker_sandbox_as_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Docker should return the same object as both sandbox and backend."""
    sandbox = FakeDockerSandbox()
    reviewer_sandbox = object()
    captured: dict[str, Any] = {}

    async def fake_create_sandbox() -> FakeDockerSandbox:
        """Return a fake Docker backend."""
        return sandbox

    async def fake_seed_project(current: FakeDockerSandbox) -> None:
        """Record that the Docker sandbox was seeded."""
        captured["seeded"] = current

    async def fake_create_readonly_sandbox(source: FakeDockerSandbox) -> object:
        """Return a distinct readonly backend and record its source."""
        captured["readonly_source"] = source
        return reviewer_sandbox

    def fake_build_subagents(
        workdir: str,
        *,
        reviewer_backend: object | None = None,
    ) -> list[dict[str, Any]]:
        """Return no subagents and record the reviewer backend."""
        captured["reviewer_backend"] = reviewer_backend
        return []

    def fake_create_deep_agent(**kwargs: Any) -> object:
        """Capture the builder arguments and return a fake agent."""
        captured["agent_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(sandbox_provider="docker", sandbox_workdir="/home/agent"),
    )
    monkeypatch.setattr(docker_manager, "create_one_sandbox", fake_create_sandbox)
    monkeypatch.setattr(docker_manager, "seed_project", fake_seed_project)
    monkeypatch.setattr(docker_manager, "create_readonly_sandbox", fake_create_readonly_sandbox)
    monkeypatch.setattr(main, "MCPManager", DummyMCPManager)
    monkeypatch.setattr(main, "build_subagents", fake_build_subagents)
    monkeypatch.setattr(main, "build_model", lambda: object())
    monkeypatch.setattr(main, "build_summary_model", lambda: object())
    monkeypatch.setattr(main, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(main, "get_tools", lambda *names: [])
    for name in (
        "TodoListMiddleware",
        "RequestContextMiddleware",
        "ToolAuditMiddleware",
        "CostMeterMiddleware",
        "SerialTaskMiddleware",
        "SummarizationMiddleware",
        "ModelCallLimitMiddleware",
    ):
        monkeypatch.setattr(main, name, DummyMiddleware)

    _agent, returned_sandbox, returned_backend, workdir = asyncio.run(
        main.build_agent("docker-thread", user_id="alice", channel="cli")
    )

    assert returned_sandbox is sandbox
    assert returned_backend is sandbox
    assert workdir == "/home/agent"
    assert captured["seeded"] is sandbox
    assert captured["readonly_source"] is sandbox
    assert captured["reviewer_backend"] is reviewer_sandbox
    assert captured["agent_kwargs"]["backend"] is sandbox
