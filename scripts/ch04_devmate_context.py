"""scripts/ch04_devmate_context.py —— 第 4 章：验证 Skills / Memory / FilesystemBackend（精简版）

运行（项目根目录）：uv run python -m scripts.ch04_devmate_context
"""
import os

os.environ.setdefault("SYC_MAX_RETRIES", "2")   # .env 中为 12：每次重试都要重发整段 input
os.environ.setdefault("SYC_TIMEOUT", "180")     # .env 中为 60：一轮写多个文件可能超时，进而触发重试

import asyncio  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from agent.main import PROJECT_ROOT  # noqa: E402
from scripts._common import (  # noqa: E402
    FLOAT_MONEY, Check, called, devmate_agent, first_turn, print_run, report, run_attempts, run_with_budget, written_paths,
)

MAX_ATTEMPTS = 2
MAX_INPUT_TOKENS = 40_000   # 正常约 26k（3 轮 × 8~9k），留一轮余量
TARGETS = [PROJECT_ROOT / "app" / "quote.py", PROJECT_ROOT / "tests" / "test_quote.py"]

TASK = (
    "在 app/quote.py 中新增一个订单接口：POST /orders/quote，"
    "接收一组商品（单价、数量），返回订单总价。"
    "请遵循团队的接口规范，并遵守团队的各项约定（如金额处理）。\n"
    "执行约束：\n"
    "1. 不要用 ls / glob / grep 浏览或搜索项目代码；\n"
    "2. 无需使用 write_todos；\n"
    "3. 先阅读适用的团队规范，读完之后再写文件；需要写的所有文件在同一轮里用 write_file 一次写完整；\n"
    "4. 写完不必读回确认，也不要再用 edit_file 修补；\n"
    "5. 完成后用一两句话汇报即可，不要在回复里复述代码。"
)


def backup_targets() -> None:
    """write_file 不覆盖已存在文件：同名旧文件先移到 logs/（不删除），保证每次都是新建。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for p in TARGETS:
        if p.exists():
            dst = PROJECT_ROOT / "logs" / "ch04_backup" / stamp / p.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(p, dst)


def check(state, budget_hit) -> list[Check]:
    written = [PROJECT_ROOT / p.lstrip("/") for p in written_paths(state)]   # 虚拟路径 → 磁盘路径
    app_files = [p for p in written if p.parent.name == "app" and p.suffix == ".py" and p.exists()]
    test_files = [p for p in written if p.name.startswith("test_") and p.exists()]
    code = "\n".join(p.read_text(encoding="utf-8") for p in app_files)
    float_hit = FLOAT_MONEY.search(code)
    skill_turn = first_turn(state, ("read_file",), "fastapi-endpoint")
    write_turn = first_turn(state, ("write_file", "edit_file"), "/app/")
    return [
        Check("Skills 命中：读取了 fastapi-endpoint/SKILL.md", called(state, "read_file", "fastapi-endpoint")),
        Check("Skills 先读后用：读完规范才写 app/ 代码",
              skill_turn is not None and write_turn is not None and skill_turn < write_turn,
              f"读规范第 {skill_turn} 轮，写代码第 {write_turn} 轮"),
        Check("FilesystemBackend：接口代码已落盘到 app/", bool(app_files)),
        Check("Memory 铁律：金额使用 Decimal", "Decimal" in code),
        Check("Memory 铁律：金额未使用 float", bool(code) and not float_hit,
              f"发现 {float_hit.group(0)!r}" if float_hit else ""),
        Check("Memory 铁律：附带了 pytest 测试文件", bool(test_files)),
        Check("规范落地：APIRouter + response_model + Pydantic 模型",
              all(k in code for k in ("APIRouter", "response_model", "BaseModel")), hard=False),
        Check("未触发预算熔断", not budget_hit, hard=False),
    ]


async def main() -> int:
    async with devmate_agent(thread_id='ch04-context', user_id='alice', channel='cli') as agent:

        async def one_attempt(i: int) -> tuple[bool, int]:
            backup_targets()
            state, budget_hit = await run_with_budget(agent, TASK, max_input_tokens=MAX_INPUT_TOKENS)
            print_run(state, budget_hit, MAX_INPUT_TOKENS)
            return report(check(state, budget_hit)), int(state.get("total_input_tokens") or 0)

        return 0 if await run_attempts(one_attempt, MAX_ATTEMPTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
