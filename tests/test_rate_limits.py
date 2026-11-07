"""Tests for per-route rate limits."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.routes import issues, jobs
from channels import webhook
from gateway.limiter import limiter
from tasks import queue as task_queue


def make_app(router: Any, **state: Any) -> FastAPI:
    """Build a small app that carries the limiter error handler."""
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    for name, value in state.items():
        setattr(app.state, name, value)
    return app


class FakeSandbox:
    """Sandbox double with a no-op stop."""

    def stop(self) -> None:
        """Do nothing."""


class FakeAgent:
    """Agent double returning a fixed reply."""

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Return one assistant message."""
        return {"messages": [SimpleNamespace(content="ok")]}


def test_issues_is_limited_per_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """The expensive /issues route should allow three calls per minute."""
    async def fake_build_agent(thread_id: str, **kwargs: object) -> tuple[FakeAgent, FakeSandbox, object, str]:
        """Avoid creating a real sandbox or model."""
        return FakeAgent(), FakeSandbox(), object(), "/home/agent"

    monkeypatch.setattr(issues, "build_agent", fake_build_agent)
    app = make_app(issues.router)
    app.dependency_overrides[issues.get_checkpointer] = lambda: object()
    app.dependency_overrides[issues.get_store] = lambda: object()
    client = TestClient(app)
    headers = {"X-API-Key": "key-tenant-a"}
    payload = {"issue": "hello"}

    assert [client.post("/issues", json=payload, headers=headers).status_code for _ in range(3)] == [200, 200, 200]
    assert client.post("/issues", json=payload, headers=headers).status_code == 429


def test_secure_issues_is_limited_per_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """The authenticated issue route should allow five calls per minute."""
    async def fake_handle(msg: object, checkpointer: object, store: object, tenant_id: str = "default") -> str:
        """Avoid building an agent."""
        return "ok"

    monkeypatch.setattr(issues, "handle_message", fake_handle)
    app = make_app(issues.router, checkpointer=object(), store=object())
    client = TestClient(app)
    headers = {"X-API-Key": "key-tenant-a"}
    payload = {"issue": "hello"}

    assert [client.post("/issues/secure", json=payload, headers=headers).status_code for _ in range(5)] == [200] * 5
    assert client.post("/issues/secure", json=payload, headers=headers).status_code == 429


def test_generic_webhook_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public generic webhook should allow three calls per minute."""
    async def fake_handle(msg: object, checkpointer: object, store: object) -> str:
        """Avoid building an agent."""
        return "ok"

    monkeypatch.setattr(webhook, "handle_message", fake_handle)
    app = make_app(webhook.router, checkpointer=object(), store=object())
    client = TestClient(app)
    headers = {"X-API-Key": "key-tenant-a"}
    payload = {"text": "hello", "source": "test", "conversation_id": "rate-test"}

    assert [client.post("/webhook/generic", json=payload, headers=headers).status_code for _ in range(3)] == [200, 200, 200]
    assert client.post("/webhook/generic", json=payload, headers=headers).status_code == 429


def test_jobs_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """The enqueue route should allow ten calls per minute."""
    async def fake_enqueue(redis: object, payload: dict[str, Any], job_id: str | None = None) -> str:
        """Return a fake job id."""
        return "job-1"

    monkeypatch.setattr(task_queue, "enqueue_issue", fake_enqueue)
    app = make_app(jobs.router, arq_redis=object())
    client = TestClient(app)
    headers = {"X-API-Key": "key-tenant-a"}
    payload = {"text": "hello"}

    assert [client.post("/jobs", json=payload, headers=headers).status_code for _ in range(10)] == [200] * 10
    assert client.post("/jobs", json=payload, headers=headers).status_code == 429
