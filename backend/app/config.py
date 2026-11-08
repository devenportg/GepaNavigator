from pydantic import Field
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


settings = Settings()
