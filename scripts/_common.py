"""scripts/_common.py —— 试跑脚本共用工具

第 2 章：打印工具（原样保留）
第 4 章起追加：预算熔断运行、证据断言、有限重试 —— 压低测试 token、对冲模型随机性
"""
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langchain.messages import AIMessage

# ======================= 第 2 章原有内容（不变） =======================

# 任务状态 → 图标，让清单更直观
_STATUS_ICON = {"completed": "✅", "in_progress": "🔄", "pending": "⬜"}

# 金额误用 float 的典型写法：类型注解、返回注解、float() 转换（第 4、6 章共用）
FLOAT_MONEY = re.compile(r":\s*float\b|->\s*float\b|\bfloat\s*\(")

@asynccontextmanager
async def devmate_agent(
    thread_id: str,
    *,
    user_id: str = "anonymous",
    channel: str = "cli",
    max_model_calls: int | None = None,
) -> AsyncIterator[Any]:
    """Build DevMate and reclaim its sandbox when the block exits."""
    from agent.main import build_agent

    agent, sandbox, _backend, _workdir = await build_agent(
        thread_id,
        user_id=user_id,
        channel=channel,
        max_model_calls=max_model_calls,
    )
    try:
        yield agent
    finally:
        sandbox.stop()


def print_reply(result: dict[str, Any]) -> None:
    print("\n=== DevMate 最终回复 ===")
    msgs = result.get("messages") or []
    print(msgs[-1].content if msgs else "（没有 messages）")


def print_files(result: dict[str, Any]) -> None:
    print("\n=== DevMate 写入的文件 ===")
    files = result.get("files") or {}
    if not files:
        print("（本次没有写文件）")
        return
    for name, data in files.items():
        print(f"\n--- {name} ---")
        # StateBackend 里文件值可能是字符串，也可能是带 content 字段的 dict
        print(data.get("content", data) if isinstance(data, dict) else data)


def print_todos(result: dict[str, Any]) -> None:
    """打印任务清单。键名经官方确认是 'todos'；为空时明确提示，避免误以为是 bug。"""
    print("\n=== DevMate 的任务清单 ===")
    todos = result.get("todos") or []
    if not todos:
        print("（本次没列计划：任务较简单，DevMate 没调用 write_todos —— 这是正常的）")
        return
    for i, todo in enumerate(todos, 1):
        # 兼容 todo 是 dict 或对象两种形态
        if isinstance(todo, dict):
            content, status = todo.get("content", str(todo)), todo.get("status", "pending")
        else:
            content, status = getattr(todo, "content", str(todo)), getattr(todo, "status", "pending")
        print(f"  {i}. {_STATUS_ICON.get(status, '•')} [{status}] {content}")


def print_all(result: dict[str, Any]) -> None:
    print_reply(result)
    print_files(result)
    print_todos(result)


# ======================= 第 4 章起追加 =======================

async def run_with_budget(
        agent: Any, task: str, *, max_input_tokens: int
) -> tuple[dict[str, Any], bool]:
    """流式跑一次任务；累计 input token（来自第 3 章 CostMeterMiddleware）超预算就立即中止。

    返回 (最后一次的完整状态, 是否触发熔断)。
    每次调用都用全新 thread_id，重试时不会把上一次的历史带进上下文。
    """
    last: dict[str, Any] = {}
    async with aclosing(
            agent.astream(
                {"messages": [{"role": "user", "content": task}]},
                config={"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}},
                stream_mode="values",   # 每步给出完整状态，便于读取累计 token
            )
    ) as stream:
        async for state in stream:
            last = state
            if (state.get("total_input_tokens") or 0) > max_input_tokens:
                return last, True   # aclosing 负责关闭流，后续模型调用随之取消
    return last, False


def tool_calls(state: dict[str, Any]) -> list[dict[str, Any]]:
    """按顺序取出本次运行中模型发起的所有工具调用。"""
    return [
        tc
        for m in state.get("messages", [])
        if isinstance(m, AIMessage)
        for tc in (m.tool_calls or [])
    ]


def called(state: dict[str, Any], name: str, contains: str | None = None) -> bool:
    """是否调用过某工具；contains 不为空时，还要求参数里包含该字符串。"""
    return any(
        tc["name"] == name and (contains is None or contains in str(tc.get("args", {})))
        for tc in tool_calls(state)
    )


def written_paths(state: dict[str, Any]) -> list[str]:
    """本次通过 write_file / edit_file 写过的路径（去重、保序）。"""
    paths: list[str] = []
    for tc in tool_calls(state):
        if tc["name"] in ("write_file", "edit_file"):
            args = tc.get("args") or {}
            p = args.get("file_path") or args.get("path")
            if p and p not in paths:
                paths.append(p)
    return paths


def first_turn(state: dict[str, Any], names: tuple[str, ...], contains: str) -> int | None:
    """某类工具调用第一次出现在第几轮模型输出（从 1 开始）；没出现返回 None。
    同一轮里并行发出的调用算同一轮 —— 用来判断"是否读完规范才动手写代码"。"""
    turn = 0
    for m in state.get("messages", []):
        if isinstance(m, AIMessage):
            turn += 1
            for tc in m.tool_calls or []:
                if tc["name"] in names and contains in str(tc.get("args", {})):
                    return turn
    return None


def model_call_count(state: dict[str, Any]) -> int:
    return sum(isinstance(m, AIMessage) for m in state.get("messages", []))


def final_reply(state: dict[str, Any]) -> str:
    msgs = state.get("messages") or []
    return str(msgs[-1].content) if msgs else ""


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    hard: bool = True   # 硬性检查决定是否通过；参考项只提示、不影响结果


def _short(args: Any, limit: int = 70) -> str:
    s = ", ".join(f"{k}={v!r}" for k, v in args.items()) if isinstance(args, dict) else str(args)
    s = s.replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def print_run(state: dict[str, Any], budget_hit: bool, max_input_tokens: int) -> None:
    print("\n--- 工具调用轨迹 ---")
    calls = tool_calls(state)
    if not calls:
        print("  （无工具调用）")
    for i, tc in enumerate(calls, 1):
        print(f"  {i}. {tc['name']}({_short(tc.get('args'))})")
    print("\n--- 最终回复（截断 500 字） ---")
    print(final_reply(state)[:500])
    print("\n--- 用量 ---")
    print(
        f"  模型调用 {model_call_count(state)} 次 | "
        f"input={state.get('total_input_tokens', 0)} output={state.get('total_output_tokens', 0)}"
    )
    if budget_hit:
        print(f"  ⛔ 累计 input 超过预算 {max_input_tokens}，已熔断中止")


def report(checks: list[Check]) -> bool:
    print("\n--- 断言结果 ---")
    for c in checks:
        icon = "✅" if c.passed else ("❌" if c.hard else "⚠️")
        tag = "硬性" if c.hard else "参考"
        print(f"  {icon} [{tag}] {c.name}" + (f" —— {c.detail}" if c.detail else ""))
    ok = all(c.passed for c in checks if c.hard)
    print(f"  => 本次{'通过' if ok else '未通过'}（仅硬性检查决定结果）")
    return ok


async def run_attempts(
        one_attempt: Callable[[int], Awaitable[tuple[bool, int]]], max_attempts: int
) -> bool:
    """最多尝试 max_attempts 次，首次通过即停。one_attempt 返回 (是否通过, 本次 input token)。"""
    total_in = 0
    for i in range(1, max_attempts + 1):
        print(f"\n========== 第 {i}/{max_attempts} 次尝试 ==========")
        passed, used = await one_attempt(i)
        total_in += used
        if passed:
            print(f"\n🎉 测试目标达成（第 {i} 次尝试），累计 input token：{total_in}")
            return True
        if i < max_attempts:
            print("\n↻ 硬性检查未通过：清理产物、换新 thread 后重试一次（对冲模型随机性）")
    print(
        f"\n❌ {max_attempts} 次尝试均未达成测试目标，累计 input token：{total_in}。\n"
        "   连续失败通常不是随机性，而是规范描述 / 提示词 / 环境本身有问题，请对照轨迹排查。"
    )
    return False
