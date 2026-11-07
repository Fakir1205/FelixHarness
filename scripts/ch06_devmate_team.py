"""scripts/ch06_devmate_team.py —— 第 6 章：子代理团队 + 沙箱端到端（省 token 版）

运行（项目根目录，需先 uv sync --extra sandbox 并配好沙箱 provider 凭据）：
    uv run python -m scripts.ch06_devmate_team

硬性检查：按序委派且主 Agent 只协调｜沙箱内 pytest 真实通过｜产物真实写入｜reviewer 结构化结论 approved
"""
import os

os.environ.setdefault("SYC_MAX_RETRIES", "2")   # 同第 4 章：少重试、放宽超时，避免整段上下文重发
os.environ.setdefault("SYC_TIMEOUT", "180")

import asyncio  # noqa: E402
import sys  # noqa: E402

from langchain.messages import ToolMessage  # noqa: E402

from agent.dispatcher import run_issue  # noqa: E402
from agent.main import PROJECT_ROOT  # noqa: E402
from scripts._common import (  # noqa: E402
    FLOAT_MONEY, Check, called, print_run, report, run_attempts, tool_calls,
)
from subagents.schemas import ReviewResult  # noqa: E402

# 需求已完全给定，默认跳过 planner/researcher；课堂演示五人全流程时在前面加上这两个名字即可
PIPELINE = ["coder", "tester", "reviewer"]
MAX_MODEL_CALLS = len(PIPELINE) + 3   # 主 Agent：每个角色委派一次 + 总结，余量 2
# 实测成功轮约 180~200s；420s 留出约 2 倍余量，同时限制失控重试。
TIMEOUT_S = 420                       # 兜底：子代理不受上面的封顶约束
MAX_ATTEMPTS = 2

W = "/home/daytona"
PRICING, TESTS, RESULT = f"{W}/app/pricing.py", f"{W}/tests/test_pricing.py", f"{W}/pytest_result.txt"
# 一条命令：缺 pytest 就静默安装；只跑本 Issue 的测试；安装和测试都设超时，防止挂住；输出截尾并落盘，供脚本取回核验
PYTEST = (
    f"cd {W} && (python -m pytest --version >/dev/null 2>&1 || timeout 90 pip install -q pytest >/dev/null 2>&1); "
    f"timeout 60 python -m pytest -q tests/test_pricing.py 2>&1 | tail -15 | tee {RESULT}"
)

ISSUE = (
    "订单服务需要一个促销金额计算函数 calc_discounted_total(items, coupon)：\n"
    "- items 形如 [{'price': '10.00', 'qty': 2}, ...]；\n"
    "- coupon 支持 {'type':'amount','value':'5.00'}（满减）和 {'type':'percent','value':'10'}（打折）；\n"
    f"- 代码写到 {PRICING}（金额用 Decimal，带类型注解和 docstring）；\n"
    f"- 测试写到 {TESTS}（覆盖正常/边界/无效优惠券，不超过 6 条）；\n"
    f"- 测试命令（原样执行，不要改）：{PYTEST}\n\n"
    "你是协调者，只负责委派：写文件、读文件、跑命令全部通过 task 交给子代理，"
    "你自己不要调用 write_file / edit_file / read_file / execute。\n"
    f"按 {' → '.join(PIPELINE)} 的顺序，每轮只调用一次 task，并把上面与该角色相关的要求原样转给它：\n"
    "- coder：一次 write_file 写完代码就汇报；\n"
    "- tester：一次 write_file 写完测试，再 execute 上面的测试命令；失败最多修复一次；\n"
    "- reviewer：两个文件各 read_file 一次后直接给结论。\n"
    "所有汇报和你的最终总结都只要 1~2 句。"
)


def review_of(state) -> ReviewResult | None:
    """解析 reviewer 的【最后一次】结构化结论（返工后以最终审查为准；容忍 JSON 前后夹杂文字）。"""
    for m in reversed(state.get("messages", [])):
        s = str(getattr(m, "content", ""))
        if isinstance(m, ToolMessage) and '"approved"' in s:
            try:
                return ReviewResult.model_validate_json(s[s.find("{"): s.rfind("}") + 1])
            except ValueError:
                continue
    return None


def check(state) -> list[Check]:
    art = state.get("artifacts") or {}
    code = art.get(PRICING, b"").decode("utf-8", "replace")
    out = art.get(RESULT, b"").decode("utf-8", "replace").strip()
    ds = [tc["args"].get("subagent_type") for tc in tool_calls(state) if tc["name"] == "task"]
    order = [d for i, d in enumerate(ds) if d not in ds[:i]]       # 去重保序
    review = review_of(state)
    float_hit = FLOAT_MONEY.search(code)
    return [
        Check(f"团队协作：按 {' → '.join(PIPELINE)} 顺序委派", order == PIPELINE, f"实际 {ds}"),
        Check("主 Agent 只协调：未亲自写文件 / 执行命令",
              not any(called(state, n) for n in ("write_file", "edit_file", "execute"))),
        Check("沙箱执行：pytest 全部通过（取回的沙箱真实输出）",
              "passed" in out and "failed" not in out and "error" not in out.lower(),
              out.splitlines()[-1] if out else "未取回测试输出（tester 没执行测试命令）"),
        Check("产物写入：pricing.py 含 calc_discounted_total 且用 Decimal",
              "def calc_discounted_total" in code and "Decimal" in code),
        Check("Memory 铁律：金额未使用 float", bool(code) and not float_hit,
              f"发现 {float_hit.group(0)!r}" if float_hit else ""),
        Check("产物写入：测试文件已写入沙箱", TESTS in art),
        Check("结构化审查：reviewer 返回 ReviewResult 且 approved",
              bool(review and review.approved), review.summary if review else "未找到可解析的结论"),
    ]


async def main() -> int:
    # 零 token 预检：宿主机同名文件会被 seed 进沙箱，而 write_file 不覆盖已有文件，只能读回再改
    for rel in ("app/pricing.py", "tests/test_pricing.py"):
        if (PROJECT_ROOT / rel).exists():
            print(f"❌ 宿主机已有 {rel}，请先移走再运行（未消耗 token）")
            return 1

    async def one_attempt(i: int) -> tuple[bool, int]:
        # 每次都是新 thread + 新沙箱，起点一致；超时取消时沙箱由 run_issue 的 finally 回收
        try:
            state = await asyncio.wait_for(
                run_issue(ISSUE, user_id="alice", channel="cli",
                          fetch_paths=[PRICING, TESTS, RESULT], max_model_calls=MAX_MODEL_CALLS),
                TIMEOUT_S,
            )
        except TimeoutError:
            print(f"\n⛔ 超过 {TIMEOUT_S}s 未结束，已中止（多半是子代理在反复重试）")
            state = {}
        print_run(state, False, 0)   # 复用第 4 章：主 Agent 的工具轨迹、最终回复、用量
        return report(check(state)), int(state.get("total_input_tokens") or 0)

    return 0 if await run_attempts(one_attempt, MAX_ATTEMPTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
