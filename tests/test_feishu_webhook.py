"""Tests for the Feishu webhook entry point."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels import webhook


class FakeFeishu:
    """Capture replies instead of calling the Feishu API."""

    sent: list[tuple[str, str]] = []

    def __init__(self) -> None:
        """Reset captured replies for each test."""

    async def send(self, chat_id: str, text: str) -> None:
        """Record the outgoing message."""
        FakeFeishu.sent.append((chat_id, text))


def make_client() -> TestClient:
    """Build an app with the webhook router and fake persistence state."""
    app = FastAPI()
    app.include_router(webhook.router)
    app.state.checkpointer = object()
    app.state.store = object()
    return TestClient(app)


def feishu_payload(event_id: str, text: str = "你好") -> dict[str, Any]:
    """Build a minimal im.message.receive_v1 event."""
    return {
        "header": {"event_id": event_id, "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_test"}},
            "message": {"chat_id": "oc_test", "content": json.dumps({"text": text})},
        },
    }


def test_feishu_webhook_replies_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """A text message must trigger handle_message and send the reply back."""
    FakeFeishu.sent = []
    webhook._seen_event_ids.clear()
    handled: dict[str, object] = {}

    async def fake_handle(msg, checkpointer, store) -> str:
        """Return a fixed reply and record the inbound message."""
        handled["text"] = msg.text
        return "这是回复"

    monkeypatch.setattr(webhook, "handle_message", fake_handle)
    monkeypatch.setattr(webhook, "FeishuChannel", FakeFeishu)

    response = make_client().post("/webhook/feishu", json=feishu_payload("evt-1"))

    assert response.status_code == 200
    assert response.json() == {"code": 0}
    assert handled["text"] == "你好"
    assert FakeFeishu.sent == [("oc_test", "这是回复")]


def test_feishu_webhook_ignores_duplicate_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Duplicate event ids must be acknowledged without another reply."""
    FakeFeishu.sent = []
    webhook._seen_event_ids.clear()

    async def fake_handle(msg, checkpointer, store) -> str:
        """Return a fixed reply."""
        return "reply"

    monkeypatch.setattr(webhook, "handle_message", fake_handle)
    monkeypatch.setattr(webhook, "FeishuChannel", FakeFeishu)
    client = make_client()

    client.post("/webhook/feishu", json=feishu_payload("evt-dup"))
    client.post("/webhook/feishu", json=feishu_payload("evt-dup"))

    assert len(FakeFeishu.sent) == 1


def test_feishu_webhook_ignores_non_message_event() -> None:
    """Non-message events must not raise UnboundLocalError."""
    webhook._seen_event_ids.clear()
    response = make_client().post(
        "/webhook/feishu",
        json={"header": {"event_id": "evt-other", "event_type": "im.chat.updated_v1"}},
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}