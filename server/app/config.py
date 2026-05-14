from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://loupe:loupe@localhost:5433/loupe"
    environment: str = "development"
    secret_key: str = "dev-secret-change-me"
    sentry_dsn: str | None = None


settings = Settings()
