from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    app_name: str = "GepaNavigator"
    database_url: str = "sqlite:///./gepa.db"
    jwt_secret: str = Field(
        default="local-development-only-secret-change-before-deployment-2026",
        min_length=32,
    )
    jwt_expire_minutes: int = 480
    integration_key: str = Field(
        default="local-demo-integration-key-change-before-deployment-2026",
        min_length=32,
    )
    seed_demo: bool = False

    # Disabled by default: YandexGPT receives only explicitly entered, synthetic draft context.
    yandexgpt_enabled: bool = False
    yandexgpt_api_key: SecretStr | None = Field(default=None, repr=False)
    yandexgpt_folder_id: str | None = None
    yandexgpt_model_version: str = Field(
        default="latest", min_length=1, max_length=30, pattern=r"^[A-Za-z0-9._-]+$"
    )
    yandexgpt_timeout_seconds: int = Field(default=30, ge=1, le=120)
    yandexgpt_max_tokens: int = Field(default=1200, ge=64, le=4096)
    yandexgpt_temperature: float = Field(default=0.2, ge=0.0, le=1.0)


settings = Settings()
