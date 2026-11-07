import json

from fastapi import APIRouter, BackgroundTasks, Request
from starlette.responses import JSONResponse
from infra.idempotency import seen_before
from channels.base import InboundMessage
from gateway.limiter import limiter
from channels.feishu import FeishuChannel
from channels.handler import handle_message
from infra.logging import get_logger

logger = get_logger()
router = APIRouter(prefix="/webhook", tags=["webhook"])



@router.post("/feishu")
@limiter.limit("120/minute")
async def feishu_webhook(request: Request, background: BackgroundTasks) -> JSONResponse:
    """飞书 Webhook 回调模式入口：先 ACK，再把消息处理放到后台任务。"""
    body = await request.json()
    if body.get("type") == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    header = body.get("header", {})
    event_id = header.get("event_id")
    if event_id and await seen_before(request.app.state.redis, event_id, ttl_seconds=3600):
        return JSONResponse({"code": 0})  # 重复事件，直接确认

    if header.get("event_type") != "im.message.receive_v1":
        return JSONResponse({"code": 0})

    event = body.get("event", {})
    message = event.get("message", {})
    text = ""
    try:
        text = json.loads(message.get("content", "{}")).get("text", "").strip()
    except (TypeError, ValueError):
        pass
    if not text:
        return JSONResponse({"code": 0})  # 非文本消息，忽略

    chat_id = message.get("chat_id", "")
    open_id = event.get("sender", {}).get("sender_id", {}).get("open_id", "unknown")
    inbound = InboundMessage(
        channel="feishu", user_id=open_id, text=text,
        conversation_id=chat_id, raw=body,
    )
    checkpointer = request.app.state.checkpointer
    store = request.app.state.store

    async def _process() -> None:
        feishu = FeishuChannel()
        reply = await handle_message(inbound, checkpointer, store)
        await feishu.send(chat_id, reply)

    background.add_task(_process)
    return JSONResponse({"code": 0})


@router.post("/generic")
@limiter.limit("3/minute")
async def generic_webhook(request: Request) -> JSONResponse:
    """通用 Webhook 入口：同步处理并直接返回回复。"""
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"code": 1, "msg": "empty text"})
    inbound = InboundMessage(
        channel="webhook", user_id=body.get("source", "external"),
        text=text, conversation_id=body.get("conversation_id", "default"), raw=body,
    )
    reply = await handle_message(
        inbound, request.app.state.checkpointer, request.app.state.store
    )
    return JSONResponse({"code": 0, "reply": reply})