"""Contract tests for LangSmith settings wiring."""

from __future__ import annotations

import pytest

from infra import settings as settings_module
from infra.settings import Settings

LANGSMITH_ENV_NAMES = (
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
)


def _clear_langsmith_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove LangSmith variables so each test starts from a clean slate."""
    for name in LANGSMITH_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"SYC_{name}", raising=False)


def test_langsmith_fields_read_unprefixed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK variable names must work despite the SYC_ model prefix."""
    _clear_langsmith_env(monkeypatch)
    monkeypatch.setenv("SYC_API_KEY", "unused")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "felix-test")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://example.invalid")

    config = Settings(_env_file=None)

    assert config.langsmith_tracing is True
    assert config.langsmith_api_key.get_secret_value() == "lsv2_test_key"
    assert config.langsmith_project == "felix-test"
    assert config.langsmith_endpoint == "https://example.invalid"


def test_langsmith_fields_accept_prefixed_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SYC_-prefixed LangSmith variables remain supported for compatibility."""
    _clear_langsmith_env(monkeypatch)
    monkeypatch.setenv("SYC_API_KEY", "unused")
    monkeypatch.setenv("SYC_LANGSMITH_TRACING", "true")
    monkeypatch.setenv("SYC_LANGSMITH_API_KEY", "lsv2_prefixed_key")
    monkeypatch.setenv("SYC_LANGSMITH_PROJECT", "felix-prefixed")

    config = Settings(_env_file=None)

    assert config.langsmith_tracing is True
    assert config.langsmith_api_key.get_secret_value() == "lsv2_prefixed_key"
    assert config.langsmith_project == "felix-prefixed"


def test_export_langsmith_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exporting config must populate the process variables the SDK reads."""
    _clear_langsmith_env(monkeypatch)
    config = Settings(
        _env_file=None,
        api_key="unused",
        langsmith_tracing=True,
        langsmith_api_key="lsv2_test_key",
        langsmith_project="felix-test",
        langsmith_endpoint="https://example.invalid",
    )

    settings_module._export_langsmith_env(config)

    assert settings_module.os.environ["LANGSMITH_TRACING"] == "true"
    assert settings_module.os.environ["LANGSMITH_API_KEY"] == "lsv2_test_key"
    assert settings_module.os.environ["LANGSMITH_PROJECT"] == "felix-test"
    assert settings_module.os.environ["LANGSMITH_ENDPOINT"] == "https://example.invalid"


def test_export_langsmith_env_skips_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SDK variables are written when tracing is off."""
    _clear_langsmith_env(monkeypatch)
    config = Settings(_env_file=None, api_key="unused", langsmith_tracing=False)

    settings_module._export_langsmith_env(config)

    for name in LANGSMITH_ENV_NAMES:
        assert name not in settings_module.os.environ
