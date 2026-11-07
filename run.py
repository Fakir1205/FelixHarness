"""API 服务启动入口。

Windows 上 uvicorn 默认创建 ProactorEventLoop，而 psycopg 3 的异步连接池
只支持 SelectorEventLoop；这里统一指定兼容的事件循环。
"""

from __future__ import annotations

import sys

import uvicorn

APP_PATH = "api.app:app"


def get_loop_factory(platform: str | None = None) -> str:
    """返回与 psycopg 异步连接池兼容的 uvicorn loop 工厂。"""
    current_platform = platform if platform is not None else sys.platform
    if current_platform == "win32":
        return "asyncio:SelectorEventLoop"
    return "auto"


def main(host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动 FastAPI 服务。"""
    uvicorn.run(APP_PATH, host=host, port=port, loop=get_loop_factory())


if __name__ == "__main__":
    main()