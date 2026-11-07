"""channels/handler.py —— 渠道无关的消息处理核心

所有渠道把消息归一化成 InboundMessage 后，都调 handle_message。
这里不关心消息来自哪——这正是"渠道差异收敛在适配器、核心只认统一请求"的体现。
"""
import asyncio
import inspect

from channels.base import InboundMessage
from channels.session import thread_id_for
from agent.main import build_agent
from infra.logging import get_logger

logger = get_logger()


async def handle_message(msg: InboundMessage, checkpointer, store, tenant_id: str = "default") -> str:
    """处理一条归一化消息，返回 DevMate 的回复文本。

    checkpointer/store 由调用方（服务的 app.state）传入复用。
    本次消息创建的沙箱会在处理结束后回收，避免容器泄漏。
    """
    thread_id = thread_id_for(msg, tenant_id)   # (渠道,会话) → 稳定 thread_id
    logger.info("处理消息：channel={} user={} thread={}", msg.channel, msg.user_id, thread_id)

    agent, sandbox, _backend, _workdir = await build_agent(
        thread_id,
        checkpointer=checkpointer,
        store=store,
        user_id=msg.user_id,
        channel=msg.channel,
    )
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": msg.text}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        return result["messages"][-1].content if result.get("messages") else ""
    finally:
        stop = getattr(sandbox, "stop", None)
        if callable(stop):
            try:
                if inspect.iscoroutinefunction(stop):
                    await stop()
                else:
                    await asyncio.to_thread(stop)
            except Exception as exc:  # noqa: BLE001 回收失败不能覆盖主流程结果或原始异常
                logger.warning("沙箱回收失败（thread_id={}）：{}", thread_id, exc)