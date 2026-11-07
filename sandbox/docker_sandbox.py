"""sandbox/docker_sandbox.py —— 自托管加固容器沙箱（实现 BaseSandbox 的四个成员）

依赖：本机装好 Docker。
导入路径（官方确认）：
    from deepagents.backends.sandbox import BaseSandbox
    from deepagents.backends.protocol import (
        ExecuteResponse, FileUploadResponse, FileDownloadResponse
    )
设计：容器在创建期就以加固参数起好并常驻（sleep infinity），本类的四个成员通过 docker 命令操作那个容器：
    - id              → 容器名
    - execute         → docker exec 跑命令
    - upload_files    → docker exec 以容器用户写入文件
    - download_files  → docker exec cat 读文件
注意：容器根文件系统只读，docker cp 写入会失败，所以不能用 docker cp。
      本类实现同步方法;BaseSandbox 会用 asyncio.to_thread 把它们包成异步(aexecute 等),
      所以 agent 走 ainvoke 时不阻塞事件循环。
"""
from __future__ import annotations

import os
import shlex
import subprocess

from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse,
)

from infra.logging import get_logger

logger = get_logger()


class DockerSandbox(BaseSandbox):
    """在一个加固 Docker 容器里执行命令、传输文件。容器生命周期由 docker_manager.py 管。"""

    def __init__(self, container_id: str, workdir: str = "/home/agent"):
        self.container_id = container_id
        self.workdir = workdir

    # ---------- 必须实现 1：唯一标识 ----------
    @property
    def id(self) -> str:
        return self.container_id

    def stop(self) -> None:
        """Stop and remove the backing container."""
        proc = subprocess.run(
            ["docker", "rm", "-f", self.container_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            error = proc.stdout.decode("utf-8", errors="replace") or "docker rm failed"
            raise RuntimeError(error)
        logger.info("容器已停止：{}", self.container_id)

    # ---------- 必须实现 2：执行命令（同步）----------
    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """在容器里跑一条 shell 命令，返回 ExecuteResponse（output + exit_code + truncated）。"""
        proc = subprocess.run(
            ["docker", "exec", "-w", self.workdir, self.container_id, "sh", "-lc", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # 合并 stderr 到 stdout
            timeout=timeout,
        )
        text = proc.stdout.decode("utf-8", errors="replace")
        truncated = len(text) > 8000
        return ExecuteResponse(
            output=text[-8000:],        # 截断尾部，避免巨量输出灌爆上下文
            exit_code=proc.returncode,
            truncated=truncated,
        )

    # ---------- 必须实现 3：上传文件（write_file/edit_file 底层依赖它）----------
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """把 [(沙箱内绝对路径, 字节内容), ...] 写进容器。逐个处理，支持部分成功（不抛异常）。"""
        results: list[FileUploadResponse] = []
        for path, content in files:
            try:
                parent = os.path.dirname(path)
                command = f"cat > {shlex.quote(path)}"
                if parent:
                    command = f"mkdir -p {shlex.quote(parent)} && {command}"
                proc = subprocess.run(
                    ["docker", "exec", "-i", self.container_id, "sh", "-c", command],
                    input=content,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if proc.returncode == 0:
                    results.append(FileUploadResponse(path=path))
                else:
                    err = (
                        proc.stderr.decode("utf-8", errors="replace").strip()
                        or proc.stdout.decode("utf-8", errors="replace").strip()
                        or "upload_failed"
                    )
                    results.append(FileUploadResponse(path=path, error=err))
            except Exception as e:  # noqa: BLE001 协议要求部分成功,不抛异常
                results.append(FileUploadResponse(path=path, error=str(e)))
        return results

    # ---------- 必须实现 4：下载文件 ----------
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """从容器读出 paths 指定的文件字节。逐个处理，支持部分成功（不抛异常）。"""
        results: list[FileDownloadResponse] = []
        for path in paths:
            try:
                proc = subprocess.run(
                    ["docker", "exec", self.container_id, "cat", path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if proc.returncode == 0:
                    results.append(FileDownloadResponse(path=path, content=proc.stdout))
                else:
                    error = (
                        proc.stderr.decode("utf-8", errors="replace").strip()
                        or "file_not_found"
                    )
                    results.append(
                        FileDownloadResponse(path=path, content=None, error=error)
                    )
            except Exception as e:  # noqa: BLE001
                results.append(FileDownloadResponse(path=path, content=None, error=str(e)))
        return results