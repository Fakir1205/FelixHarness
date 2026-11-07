"""Regression tests for Docker command execution."""

from __future__ import annotations

import asyncio
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sandbox.docker_manager as docker_manager


def test_run_uses_windows_safe_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Docker commands should not depend on asyncio subprocess support."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Capture the subprocess invocation and return output."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"ok")

    monkeypatch.setattr(docker_manager.subprocess, "run", fake_run)

    code, output = asyncio.run(docker_manager._run(["docker", "version"]))

    assert code == 0
    assert output == "ok"
    assert calls[0][0] == ["docker", "version"]
    assert calls[0][1]["stdout"] is docker_manager.subprocess.PIPE


def test_seed_project_streams_tar_into_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Seed must use docker exec + tar because the container rootfs is read-only."""
    skill = tmp_path / "skills" / "unit-test" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")

    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Capture the docker exec command and archive payload."""
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(docker_manager.subprocess, "run", fake_run)
    sandbox = SimpleNamespace(container_id="container-1", workdir="/home/agent")

    asyncio.run(docker_manager.seed_project(sandbox, root=tmp_path))

    assert captured["command"] == [
        "docker", "exec", "-i", "-u", "1000",
        "container-1", "tar", "-xf", "-", "-C", "/home/agent",
    ]
    archive = tarfile.open(fileobj=io.BytesIO(captured["kwargs"]["input"]))
    names = archive.getnames()
    assert "skills/unit-test/SKILL.md" in names
    assert "AGENTS.md" in names


def test_seed_project_raises_when_copy_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed seed must raise instead of logging a false success."""
    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Simulate a failing docker exec."""
        return SimpleNamespace(returncode=1, stdout=b"permission denied")

    monkeypatch.setattr(docker_manager.subprocess, "run", fake_run)
    sandbox = SimpleNamespace(container_id="container-1", workdir="/home/agent")

    with pytest.raises(RuntimeError, match="permission denied"):
        asyncio.run(docker_manager.seed_project(sandbox, root=tmp_path))