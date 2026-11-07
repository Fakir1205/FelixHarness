"""api/routes/issues.py —— 提交 Issue 的业务路由"""
from uuid import uuid4

from fastapi import APIRouter, Depends,Request
from gateway.auth import require_api_key
from gateway.limiter import limiter
from agent.main import build_agent
from api.schemas import IssueRequest, IssueResponse
from api.deps import get_checkpointer, get_store
from infra.logging import get_logger
from channels.base import InboundMessage
from channels.handler import handle_message
router = APIRouter(prefix="/issues", tags=["issues"])
logger = get_logger()


@router.post("", response_model=IssueResponse)
@limiter.limit("3/minute")
async def submit_issue(
    request: Request,
    req: IssueRequest,
    checkpointer=Depends(get_checkpointer),   # 注入 lifespan 建好的共享资源
    store=Depends(get_store),
) -> IssueResponse:
    """处理一次 Issue，并在请求结束时停止本次会话的沙箱。"""
    # thread_id：客户端传了就用它（续聊/断点续跑），没传就新建
    thread_id = req.thread_id or uuid4().hex

    # 构建 agent（轻组装），传入共享的持久化资源
    agent, sandbox, _backend, _workdir = await build_agent(
        thread_id,  # 必传
        checkpointer=checkpointer,
        store=store,
        user_id=req.user_id,
        channel=req.channel,
    )
    try:
        # 异步调用，带 thread_id —— 同一 thread_id 下次请求会带着历史上下文继续
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": req.issue}]},
            config={"configurable": {"thread_id": thread_id}},
        )

        reply = result["messages"][-1].content if result.get("messages") else ""
        return IssueResponse(thread_id=thread_id, reply=reply)
    finally:
        try:
            sandbox.stop()
            logger.info("沙箱已停止：thread_id={}", thread_id)
        except Exception as exc:  # noqa: BLE001 回收失败不能覆盖主流程结果或原始异常
            logger.warning("沙箱停止失败（thread_id={}）：{}", thread_id, exc)
@router.post("/secure")
@limiter.limit("5/minute")
async def submit_issue_secure(
    req: IssueRequest,
    request: Request,
    tenant_id: str = Depends(require_api_key),   # ← 鉴权返回租户 id
):
    """需要 X-API-Key 的端点；租户身份贯穿到会话隔离。"""
    inbound = InboundMessage(
        channel=req.channel, user_id=req.user_id,
        text=req.issue, conversation_id=req.thread_id or req.user_id,
    )
    reply = await handle_message(
        inbound,
        request.app.state.checkpointer,
        request.app.state.store,
        tenant_id=tenant_id,                     # ← 一路传到 thread 派生，按租户隔离
    )
    return {"reply": reply, "tenant": tenant_id}
