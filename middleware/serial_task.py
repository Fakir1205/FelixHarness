"""middleware/serial_task.py —— 子代理委派串行化（确定性策略，不靠提示词）

下游子代理依赖上游产物：tester 要测 coder 写的代码，reviewer 要审两者的结果。
主 Agent 若在一轮里同时委派多个 task，它们会并行运行，对着还不存在的文件干活。
百炼等接口并不总遵守 parallel_tool_calls=False，所以在 Harness 层强制：
一轮模型输出里如果有多个 task 调用，只保留第一个，其余工具调用不受影响。
被丢弃的委派不会留下悬空的 tool_call，模型下一轮看到结果后会自己接着委派。
"""
from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import AIMessage

from infra.logging import get_logger

logger = get_logger()


class SerialTaskMiddleware(AgentMiddleware):
    """一轮最多委派一个子代理。"""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        response = await handler(request)
        # 若内层中间件返回 ExtendedModelResponse（如第 3 章的 CostMeter），取出其中的 ModelResponse
        inner = getattr(response, "model_response", response)
        msg = inner.result[-1] if inner.result else None
        if isinstance(msg, AIMessage):
            tasks = [tc for tc in msg.tool_calls if tc["name"] == "task"]
            if len(tasks) > 1:
                keep_id = tasks[0]["id"]
                inner.result[-1] = msg.model_copy(update={"tool_calls": [
                    tc for tc in msg.tool_calls if tc["name"] != "task" or tc["id"] == keep_id
                ]})
                logger.info("⏸ 本轮 {} 个委派只保留第一个：{}",
                            len(tasks), tasks[0]["args"].get("subagent_type"))
        return response