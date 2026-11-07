"""
infra/settings.py —— ShanYangClaw 的配置中枢

- 所有 API Key / Base URL / 连接串统一从这里取，不散落在业务代码里
- Pydantic Settings 做类型校验，缺失关键项时给清晰报错
- 字段前缀 SYC_（ShanYangClaw 缩写），避免与系统其他环境变量撞名
"""
from functools import lru_cache
import os
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    langsmith_tracing: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "LANGSMITH_TRACING", "SYC_LANGSMITH_TRACING"
        ),
    )
    langsmith_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "LANGSMITH_API_KEY", "SYC_LANGSMITH_API_KEY"
        ),
    )
    langsmith_project: str = Field(
        default="felix-harness",
        validation_alias=AliasChoices(
            "LANGSMITH_PROJECT", "SYC_LANGSMITH_PROJECT"
        ),
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias=AliasChoices(
            "LANGSMITH_ENDPOINT", "SYC_LANGSMITH_ENDPOINT"
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="SYC_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    # ===== 模型 =====
    model_name: str = "qwen-max"
    model_provider: str = "openai"
    api_key: SecretStr                    # 用 SecretStr，避免密钥被 print/log 泄露
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_tiers: dict[str, str] = {
        "strong": "qwen-max",  # 难任务：规划、写代码、审查
        "standard": "qwen-plus",  # 中等任务：测试
        "cheap": "qwen-turbo",  # 简单任务：读代码、总结
    }
    # ===== 连接弹性 =====
    max_retries: int = 12
    timeout: int = 60
    # 飞书
    feishu_app_id: str = ""
    feishu_app_secret: SecretStr = SecretStr("")
    feishu_encrypt_key: str = ""  # 长连接可留空；Webhook 回调模式才用
    feishu_verification_token: str = ""  # 同上

    # 网关多租户（第 9 章，给 require_api_key / ch09_test_gateway / ch09_test_tenant 用）
    # 形如 {"key-tenant-a": "tenant-a", "key-tenant-b": "tenant-b"}
    api_keys: dict[str, str] = {"key-tenant-a": "tenant-a", "key-tenant-b": "tenant-b"}
    # ===== 持久化底座 =====
    postgres_url: str = "postgresql://felix:felix123456@localhost:5434/felix"
    redis_url: str = "redis://localhost:6378/2"
    redis_pool_max: int = 20
    database_url: str = "postgresql://felix:felix123456@localhost:5434/felix"
    pg_pool_min: int = 2
    pg_pool_max: int = 20
    # ===== 运行 =====
    log_level: str = "INFO"
    #============================
    mcp_servers:dict[str,dict] = {}
    # =====沙箱隔离 =====
    sandbox_provider: str = "docker"
    sandbox_runtime: str = "runc"
    sandbox_image: str = "felix-sandbox:latest"
    sandbox_workdir: str = "/home/agent"
    sandbox_mem_limit: str = "512m"
    sandbox_pids_limit: int = 256
    sandbox_cpus: str = "1.0"
    sandbox_pool_size: int = 4
    max_concurrent_llm: int = 8

def _export_langsmith_env(s: "Settings") -> None:
    """把 LangSmith 变量写回 os.environ。

       关键：LangSmith 库只认系统环境变量，不读 Settings 对象——所以必须写回 os.environ。
       只在开启 tracing 时写，避免没配 key 时设一堆空变量。
       """
    if not s.langsmith_tracing:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key.get_secret_value()
    os.environ["LANGSMITH_PROJECT"] = s.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = s.langsmith_endpoint
_settings = Settings()
_export_langsmith_env(_settings)
@lru_cache
def get_settings() -> Settings:
    """全进程单例。业务代码统一通过它拿配置。"""
    return _settings
