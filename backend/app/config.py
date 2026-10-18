from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "GepaNavigator"
    database_url: str = "sqlite:///./gepa.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 480
    integration_key: str = "gis-demo-key"
    seed_demo: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
