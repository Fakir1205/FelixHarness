"""Regression tests for Daytona sandbox lifecycle handling."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from sandbox import manager


class FakeQuery:
    """Capture the sandbox list query."""

    def __init__(self, **kwargs: Any) -> None:
        """Store query arguments."""
        self.kwargs = kwargs


class FakeParams:
    """Capture sandbox creation parameters."""

    def __init__(self, **kwargs: Any) -> None:
        """Store creation arguments."""
        self.kwargs = kwargs


class FakeBackend:
    """Minimal LangChain sandbox backend double."""

    def __init__(self, sandbox: FakeSandbox) -> None:
        """Keep the wrapped sandbox."""
        self.sandbox = sandbox


class FakeSandbox:
    """Sandbox double used by the manager tests."""

    def __init__(self, state: str = "started") -> None:
        """Initialize the sandbox state."""
        self.state = state
        self.started = False

    def start(self) -> None:
        """Mark the sandbox as started."""
        self.started = True
        self.state = "started"

    def get_workspace_root_dir(self) -> str:
        """Return a stable work directory."""
        return "/home/daytona"


class FakeDaytona:
    """Daytona client double for list/create assertions."""

    def __init__(self, sandboxes: list[FakeSandbox], created: FakeSandbox | None = None) -> None:
        """Initialize list results and the sandbox returned by create."""
        self.sandboxes = sandboxes
        self.created = created or FakeSandbox()
        self.query: FakeQuery | None = None
        self.params: FakeParams | None = None
        self.create_calls = 0

    def list(self, query: FakeQuery) -> Iterator[FakeSandbox]:
        """Record the query and return matching sandboxes."""
        self.query = query
        return iter(self.sandboxes)

    def create(self, params: FakeParams) -> FakeSandbox:
        """Record creation parameters and return a sandbox."""
        self.params = params
        self.create_calls += 1
        return self.created


def install_fake_sdk(monkeypatch: pytest.MonkeyPatch, client: FakeDaytona) -> None:
    """Install minimal Daytona modules for the lazy imports in manager."""
    daytona = SimpleNamespace(
        Daytona=lambda config: client,
        DaytonaConfig=lambda: object(),
        ListSandboxesQuery=FakeQuery,
        CreateSandboxFromSnapshotParams=FakeParams,
    )
    langchain_daytona = SimpleNamespace(DaytonaSandbox=FakeBackend)
    monkeypatch.setitem(sys.modules, "daytona", daytona)
    monkeypatch.setitem(sys.modules, "langchain_daytona", langchain_daytona)
    monkeypatch.setattr(manager, "seed_project_into_sandbox", lambda backend, sandbox, root: "/home/daytona")


def test_get_or_create_creates_sandbox_with_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new sandbox should carry its thread label and auto-delete policy."""
    client = FakeDaytona([])
    install_fake_sdk(monkeypatch, client)

    _backend, sandbox, returned_client, workdir = manager.get_or_create_sandbox_backend("thread-1")

    assert sandbox is client.created
    assert returned_client is client
    assert workdir == "/home/daytona"
    assert client.query is not None
    assert client.query.kwargs["labels"] == {"thread_id": "thread-1"}
    assert client.params is not None
    assert client.params.kwargs["labels"] == {"thread_id": "thread-1"}
    assert client.params.kwargs["auto_delete_interval"] == 60


def test_get_or_create_restarts_stopped_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reused sandbox should be restarted instead of recreated."""
    sandbox = FakeSandbox(state="stopped")
    client = FakeDaytona([sandbox])
    install_fake_sdk(monkeypatch, client)

    _backend, returned_sandbox, _client, workdir = manager.get_or_create_sandbox_backend("thread-2")

    assert returned_sandbox is sandbox
    assert sandbox.started is True
    assert client.create_calls == 0
    assert workdir == "/home/daytona"
