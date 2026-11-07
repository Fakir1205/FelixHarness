"""Regression tests for CLI tools on Windows SelectorEventLoop."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from tools import git_tools, test_tools


def _completed(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> SimpleNamespace:
    """Build a subprocess.CompletedProcess-like result."""
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def test_run_pytest_works_on_selector_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_pytest must not use asyncio subprocesses, which SelectorEventLoop lacks."""
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        """Capture the command instead of launching pytest."""
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _completed(stdout=b"3 passed")

    monkeypatch.setattr(test_tools.subprocess, "run", fake_run)

    result = asyncio.run(
        test_tools.run_pytest.ainvoke({"path": "tests/demo.py"}),
        loop_factory=asyncio.SelectorEventLoop,
    )

    assert result == "3 passed"
    assert captured["cmd"][0] == sys.executable
    assert captured["cmd"][1:] == ["-m", "pytest", "tests/demo.py", "-q"]


def test_git_run_returns_stdout_on_selector_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """git_tools._run must execute subprocesses outside the Selector event loop."""
    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        """Return a fake successful git result."""
        return _completed(stdout=b" M app.py\n")

    monkeypatch.setattr(git_tools.subprocess, "run", fake_run)

    result = asyncio.run(
        git_tools._run(["git", "status", "--short"]),
        loop_factory=asyncio.SelectorEventLoop,
    )

    assert result == "M app.py"


def test_git_run_returns_stderr_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed git command should surface stderr."""
    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        """Return a fake failed git result."""
        return _completed(stderr=b"fatal: not a git repository\n", returncode=1)

    monkeypatch.setattr(git_tools.subprocess, "run", fake_run)

    result = asyncio.run(
        git_tools._run(["git", "status"]),
        loop_factory=asyncio.SelectorEventLoop,
    )

    assert result == "[git error] fatal: not a git repository"