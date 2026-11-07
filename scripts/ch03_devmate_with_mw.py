"""scripts/ch03_devmate_with_mw.py —— 第 3 章：带审计/成本/上下文中间件跑 DevMate

运行（项目根目录）：uv run python -m scripts.ch03_devmate_with_mw
"""
import asyncio

from scripts._common import devmate_agent, print_all


async def main():
    # 传入身份，观察 RequestContextMiddleware 注入效果
    async with devmate_agent(thread_id='ch03-middleware', user_id='alice', channel='cli') as agent:

        task = (
            "为订单服务实现一个折扣计算模块，放在 discount.py：calc_subtotal、apply_coupon、"
            "calc_final_total 三个函数，带类型注解、docstring，处理空列表与无效优惠券。"
        )

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"configurable": {"thread_id": "ch03-middleware"}},
        )

        print_all(result)

        # 顺带看成本中间件累加进状态的 token（CostState 的字段）
        print("\n=== 累计 token（来自 CostMeterMiddleware）===")
        print("input :", result.get("total_input_tokens"))
        print("output:", result.get("total_output_tokens"))


if __name__ == "__main__":
    asyncio.run(main())
