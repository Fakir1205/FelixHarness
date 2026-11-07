import asyncio

from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from deepagents import create_deep_agent

from agent.main import build_model

@tool
async def delete_database(db_name: str) -> str:
    """删除指定的数据库（危险操作，不可逆）。"""
    # 真实场景这里会真的删库；demo 里只返回一句话
    return f"数据库 {db_name} 已删除。"