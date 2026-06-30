from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://loupe:loupe@localhost:5433/loupe"
    environment: str = "development"
    secret_key: str = "dev-secret-change-me"
    sentry_dsn: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None

    # B7: server-side branch re-runs LLM calls with the *server's* provider keys.
    # Fine for single-user self-host; set false on a shared deployment so a branch
    # click can't spend the operator's budget (post-branch LLM spans then pass
    # through the stored output instead of re-executing live).
    allow_server_side_llm_replay: bool = True


settings = Settings()
