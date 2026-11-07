"""Regression tests for the Docker sandbox lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import sandbox.docker_sandbox as docker_sandbox


def test_stop_removes_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """DockerSandbox.stop should synchronously remove the container."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Capture the Docker command and report success."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(docker_sandbox.subprocess, "run", fake_run)

    sandbox = docker_sandbox.DockerSandbox("container-1")
    sandbox.stop()

    assert calls[0][0] == ["docker", "rm", "-f", "container-1"]


def test_upload_files_uses_exec_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploads must not use docker cp on a read-only rootfs."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Capture the upload command and payload."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(docker_sandbox.subprocess, "run", fake_run)
    sandbox = docker_sandbox.DockerSandbox("container-1")

    results = sandbox.upload_files([("/home/agent/tests/test_x.py", b"print(1)")])

    assert results[0].error is None
    assert calls[0][0][:5] == ["docker", "exec", "-i", "container-1", "sh"]
    assert "mkdir -p /home/agent/tests" in calls[0][0][-1]
    assert "cat > /home/agent/tests/test_x.py" in calls[0][0][-1]
    assert calls[0][1]["input"] == b"print(1)"


def test_upload_files_reports_docker_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed upload should be reported per file, not raised."""
    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Simulate a rejected write."""
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"permission denied")

    monkeypatch.setattr(docker_sandbox.subprocess, "run", fake_run)
    sandbox = docker_sandbox.DockerSandbox("container-1")

    results = sandbox.upload_files([("/home/agent/a.py", b"x")])

    assert results[0].error == "permission denied"


def test_download_files_reads_via_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Downloads should read file bytes through docker exec cat."""
    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Return fake file content."""
        return SimpleNamespace(returncode=0, stdout=b"content", stderr=b"")

    monkeypatch.setattr(docker_sandbox.subprocess, "run", fake_run)
    sandbox = docker_sandbox.DockerSandbox("container-1")

    results = sandbox.download_files(["/home/agent/a.py"])

    assert results[0].content == b"content"
    assert results[0].error is None


def test_download_files_reports_missing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing file should be reported as an error."""
    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        """Simulate a missing file."""
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"No such file")

    monkeypatch.setattr(docker_sandbox.subprocess, "run", fake_run)
    sandbox = docker_sandbox.DockerSandbox("container-1")

    results = sandbox.download_files(["/home/agent/missing.py"])

    assert results[0].content is None
    assert results[0].error == "No such file"