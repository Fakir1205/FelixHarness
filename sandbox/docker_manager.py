"""sandbox/docker_manager.py —— 加固容器的创建/seed/销毁

runtime 参数是隔离级别开关：runc(加固容器) / runsc(gVisor) / kata(microVM)。
换 runtime 就换隔离级别，DockerSandbox 代码不变（见第 4 节）。

容器根文件系统是只读的，不能使用 docker cp 写入；seed 和文件上传都通过
docker exec 以容器用户身份流式写入可写的 tmpfs 工作目录。
"""
from __future__ import annotations
import time
from obs.metrics import SANDBOX_CREATE_DURATION
import asyncio
import io
import subprocess
import tarfile
import uuid
from pathlib import Path

from infra.settings import get_settings
from infra.logging import get_logger
from sandbox.docker_sandbox import DockerSandbox

logger = get_logger()


async def _run(cmd: list[str], *, input_data: bytes | None = None) -> tuple[int, str]:
    """运行 docker 命令，返回 (退出码, 合并后的输出)。"""
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def _make_seed_tar(
    root: Path,
    subdirs: tuple[str, ...],
    extra_files: tuple[str, ...],
) -> bytes:
    """把需要 seed 的目录和文件打包成 tar 字节流。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for sub in subdirs:
            path = root / sub
            if path.exists():
                archive.add(path, arcname=sub)
        for name in extra_files:
            path = root / name
            if path.is_file():
                archive.add(path, arcname=name)
    return buffer.getvalue()


async def create_one_sandbox() -> DockerSandbox:
    """以加固参数起一个常驻容器，返回 DockerSandbox。"""
    start = time.perf_counter()
    s = get_settings()
    name = f"syc-sbx-{uuid.uuid4().hex[:12]}"
    workdir = s.sandbox_workdir

    # tmpfs 工作目录：可写 + 可执行 + 限大小 + 属主对齐非 root 用户(uid=1000)
    tmpfs_opt = f"{workdir}:rw,exec,size=512m,uid=1000"

    code, out = await _run([
        "docker", "run", "-d", "--name", name,
        "--runtime", s.sandbox_runtime,             # ← 换它即换隔离级别
        "--network", "none",                        # 断网
        "--cap-drop", "ALL",                        # 丢能力
        "--security-opt", "no-new-privileges",      # 禁提权
        "--read-only",                              # 只读根
        "--tmpfs", tmpfs_opt,                       # 唯一可写区
        "--tmpfs", "/tmp:rw,exec,size=128m,uid=1000",  # 额外给 /tmp 可写(部分工具需要)
        "--memory", s.sandbox_mem_limit,
        "--memory-swap", s.sandbox_mem_limit,
        "--pids-limit", str(s.sandbox_pids_limit),
        "--cpus", s.sandbox_cpus,
        "--user", "1000:1000",                      # 非 root
        "-w", workdir,
        s.sandbox_image, "sleep", "infinity",       # 常驻，等 docker exec
    ])
    if code != 0:
        raise RuntimeError(f"起沙箱容器失败：{out}")
    logger.info("加固容器已起：{}（runtime={}）", name, s.sandbox_runtime)
    SANDBOX_CREATE_DURATION.observe(time.perf_counter() - start)
    return DockerSandbox(container_id=name, workdir=workdir)

async def create_readonly_sandbox(source_sandbox: DockerSandbox) -> DockerSandbox:
    """给 reviewer 起一个只读容器：把 source_sandbox 的工作目录内容复制进来后设为只读。

    实现：① 起一个新容器；② 从源容器把代码 cp 出来再 cp 进新容器；
         ③ 在新容器内 chmod -R a-w 工作目录,使 execute 跑 echo>file 也写不进。
    这样 reviewer 即使用 execute 也改不了代码——靠文件系统权限,不靠 prompt。
    """
    import tempfile
    s = get_settings()
    name = f"syc-ro-{uuid.uuid4().hex[:12]}"
    workdir = s.sandbox_workdir
    code, out = await _run([
        "docker", "run", "-d", "--name", name,
        "--runtime", s.sandbox_runtime,
        "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--read-only",
        "--tmpfs", f"{workdir}:rw,exec,size=512m,uid=1000",
        "--memory", s.sandbox_mem_limit, "--memory-swap", s.sandbox_mem_limit,
        "--pids-limit", str(s.sandbox_pids_limit), "--cpus", s.sandbox_cpus,
        "--user", "1000:1000", "-w", workdir,
        s.sandbox_image, "sleep", "infinity",
    ])
    if code != 0:
        raise RuntimeError(f"起只读沙箱失败：{out}")
    ro = DockerSandbox(container_id=name, workdir=workdir)
    # 把源容器代码搬进来(经宿主中转),然后把工作目录设为不可写
    with tempfile.TemporaryDirectory() as tmpd:
        await _run(["docker", "cp", f"{source_sandbox.container_id}:{workdir}/.", tmpd])
        await _run(["docker", "cp", f"{tmpd}/.", f"{name}:{workdir}"])
    # chmod 去掉写位(用 root 改,因为非 root 改不动自己没权限的位)
    await _run(["docker", "exec", "-u", "0", name, "chmod", "-R", "a-w", workdir])
    logger.info("只读 reviewer 沙箱已起：{}", name)
    return ro

async def seed_project(
    sandbox: DockerSandbox,
    root: Path | None = None,
    subdirs: tuple[str, ...] = ("app", "tests", "skills"),
    extra_files: tuple[str, ...] = ("AGENTS.md",),
) -> None:
    """把宿主项目 seed 进容器工作目录。

    容器根文件系统只读，docker cp 会直接失败；这里用 tar 流通过
    docker exec 以 uid=1000 解压到可写的 tmpfs 工作目录。
    """
    root = root or Path(__file__).resolve().parent.parent
    cid = sandbox.container_id
    workdir = sandbox.workdir
    archive = _make_seed_tar(root, subdirs, extra_files)
    code, out = await _run(
        ["docker", "exec", "-i", "-u", "1000", cid, "tar", "-xf", "-", "-C", workdir],
        input_data=archive,
    )
    if code != 0:
        raise RuntimeError(f"seed 项目失败：{out}")
    logger.info("项目已 seed 进容器 {}", cid)


async def destroy_sandbox(sandbox: DockerSandbox) -> None:
    """销毁容器（用完即弃）。tmpfs 工作目录随容器一起消失，不残留。"""
    code, out = await _run(["docker", "rm", "-f", sandbox.container_id])
    if code != 0:
        raise RuntimeError(f"销毁容器失败：{out}")
    logger.info("容器已销毁：{}", sandbox.container_id)