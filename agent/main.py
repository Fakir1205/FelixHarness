"""agent/main.py —— DevMate 主 Agent（第 4 章：接入 FilesystemBackend + Skills + Memory）

⚠️ 安全：本章用 FilesystemBackend 仅适用于本地开发/教学。
   生产/Web 服务请改用 StateBackend + 沙箱（第 8、11 章）。
"""
from pathlib import Path
from tools.registry import get_tools
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver
from tools.mcp import MCPManager
from infra.settings import get_settings
from infra.logging import get_logger
from middleware.audit import ToolAuditMiddleware
from middleware.cost import CostMeterMiddleware
from middleware.context import RequestContextMiddleware
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware import SummarizationMiddleware
from middleware.serial_task import SerialTaskMiddleware
from subagents.profiles import build_subagents
from sandbox.manager import get_or_create_sandbox_backend
from middleware.concurrency import LLMConcurrencyMiddleware
from infra.fallback import build_fallback_middleware
logger = get_logger()

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # shanyang-claw/
SKILLS_SOURCES = ["/skills/"]
MEMORY_SOURCES = ["/AGENTS.md"]


DEVMATE_SYSTEM_PROMPT = """你是 DevMate，一个严谨的研发助手，服务于一个 Python / FastAPI 订单微服务团队。

工作准则：
- 动手前先用 write_todos 写出清晰的任务清单，并随进展更新它。
- 写代码遵循团队规范（见你已加载的 skills 与 AGENTS.md），不臆测，信息不足先读相关文件。
- 每次改动后，用一两句话说明"改了什么、为什么这么改"。
"""

def build_model():
    """按第 1 章的配置构建模型。换模型只改 .env，不改这里。"""
    s = get_settings()

    extra: dict = {}
    # 并行工具调用：百炼 OpenAI 兼容接口默认一轮只返回一个工具调用；
    # 打开后模型能在同一轮里读两个 skill、写两个文件，直接少跑几轮。
    # 其它 provider 不一定认这个参数（比如 Anthropic 会直接报错），所以按 provider 自动判断，
    # 保住"换模型只改 .env"的约定。这类"只对某个模型生效的调参"，第 7 章会收进 Harness Profile。
    if s.model_provider == "openai":
        extra["model_kwargs"] = {"parallel_tool_calls": True}

    return init_chat_model(
        model=s.model_name,
        model_provider=s.model_provider,
        api_key=s.api_key.get_secret_value(),
        base_url=s.base_url,
        temperature=0,
        max_retries=s.max_retries,
        timeout=s.timeout,
        **extra,
    )
def build_summary_model():
    """专门用来做上下文摘要的便宜模型"""
    s = get_settings()
    return init_chat_model(
        model="qwen-turbo",  # 换成便宜的小模型
        model_provider=s.model_provider,
        api_key=s.api_key.get_secret_value(),
        base_url=s.base_url,
        temperature=0,
    )

async def build_agent(
        thread_id: str,
        user_id: str = "anonymous",
        channel: str = "cli",
        max_model_calls: int | None = None,
        checkpointer=None,
        store=None,
):
    """第 6 章：五子代理团队 + 沙箱后端（已 seed 项目到沙箱工作目录）。

    - backend 用沙箱（自动提供文件工具 + execute），取代第 4 章的 FilesystemBackend；
    - 沙箱在新建时已被 seed 进 app/ tests/ skills/ AGENTS.md（见 sandbox/manager.py）；
    - skills/memory 指向沙箱工作目录下 seed 后的真实路径（workdir/skills 等）；
    - subagents 注入五个专职子代理，并补挂审计中间件；
    - SerialTaskMiddleware 保证一轮最多委派一个子代理；
    - max_model_calls：主 Agent 单次运行的模型调用上限，到上限平稳结束；默认 None 不限制；
    - 密钥（API key）只在主进程的 build_model() 里用，绝不传进沙箱。
    返回 (agent, sandbox, backend, workdir)：sandbox 用于 stop()，backend 用于文件下载。
    """
    # workdir 是沙箱工作目录（Daytona 默认 /home/daytona），项目就 seed 在它下面
    reviewer_backend = None

    async def build_sandbox_backend():
        nonlocal reviewer_backend
        s = get_settings()
        if s.sandbox_provider == "docker":
            from sandbox.docker_manager import (
                create_one_sandbox,
                create_readonly_sandbox,
                seed_project,
            )
            sb = await create_one_sandbox()
            await seed_project(sb)
            reviewer_backend = await create_readonly_sandbox(sb)
            return sb, sb, s.sandbox_workdir
        else:  # daytona —— 第 6 章那套
            backend, sandbox, _client, workdir = get_or_create_sandbox_backend(thread_id)
            return backend, sandbox, workdir

    backend, sandbox, workdir = await build_sandbox_backend()
    mcp_tools = await MCPManager.from_settings().get_tools()
    # 子代理不继承中间件。补挂无状态的审计中间件，让子代理内部的工具调用也出现在日志里。
    # 只挂审计，不挂 CostMeter：CostMeter 有自己的状态字段，子代理结束时会覆盖回主 Agent 的状态，统计会出错。
    subagents = build_subagents(workdir, reviewer_backend=reviewer_backend)
    for sa in subagents:
        sa.setdefault("middleware", []).append(ToolAuditMiddleware())

    middleware = [
        TodoListMiddleware(),
        RequestContextMiddleware(user_id=user_id, channel=channel),
        ToolAuditMiddleware(),
        CostMeterMiddleware(),
        LLMConcurrencyMiddleware(),
        SerialTaskMiddleware(),         # ← 委派串行化（放在 CostMeter 之后 = 更内层，直接拿到模型原始输出）
        SummarizationMiddleware(build_summary_model()),
        build_fallback_middleware()
    ]

    if max_model_calls:   # 与第 4 章 build_agent 相同的可选封顶
        middleware.append(ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="end"))

    agent = create_deep_agent(
        model=build_model(),
        system_prompt=DEVMATE_SYSTEM_PROMPT + (
            f"\n\n【执行环境与路径规则——必须严格遵守】"
            f"\n你运行在一个沙箱里，项目代码已位于 `{workdir}/` 下（含 `{workdir}/app/`、`{workdir}/tests/`）。"
            f"\n⚠️ 所有文件操作（write_file/edit_file/read_file）和命令（execute）都【必须】使用以 `{workdir}/` 开头的【绝对路径】。"
            f"\n✅ 正确：写测试到 `{workdir}/tests/test_pricing.py`、改代码 `{workdir}/app/pricing.py`、"
            f"跑测试 `cd {workdir} && python -m pytest -q`。"
            f"\n❌ 错误（会因权限被拒绝，绝不要这样）：`/test_pricing.py`、`test_pricing.py`、`/app/pricing.py` 这类根路径或相对路径。"
            f"\n如果你不确定某文件在哪，先用 `ls {workdir}` 查看，再用绝对路径操作。"
            "\n\n你是团队负责人：对复杂 Issue，先用 task() 委派给 planner 规划，"
            "再依次委派 researcher/coder/tester/reviewer。你只做协调，不亲自写大量代码。"
            "委派时，把上面的【绝对路径规则】一并转达给子代理。"
        ),
        backend=backend,                       # ← 沙箱后端：自动带 execute
        subagents=subagents,                           # ← 五个专职子代理（已补挂审计中间件）
        skills=[f"{workdir}/skills"],                  # ← seed 后的真实路径（不再是空的 /skills/）
        memory=[f"{workdir}/AGENTS.md"],               # ← 同上
        middleware=middleware,
        checkpointer=checkpointer,
        store=store,
        tools=get_tools("git", "search", "test") + mcp_tools,
    )
    logger.info("DevMate 团队版构建完成：5 子代理 + 沙箱后端（项目已 seed 到 {}）", workdir)
    return agent, sandbox, backend, workdir
