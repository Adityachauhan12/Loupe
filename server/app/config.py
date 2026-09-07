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

    # B8.4: default judge backend for suite runs. Format "<provider>/<model>".
    # Groq is free (zero-cost dev + self-host); switch to "claude/claude-sonnet-4-6"
    # for stronger semantic verdicts (per suite or per run). Overridable via env.
    # Note the model itself contains a slash — only the FIRST slash splits
    # provider from model, so "groq/openai/gpt-oss-120b" means gpt-oss-120b
    # served by Groq, not by OpenAI. (Was llama-3.3-70b-versatile until Groq
    # retired it; see B13.)
    judge_backend: str = "groq/openai/gpt-oss-120b"

    # B13: a trace is durable, the model behind it is not. Groq retired every
    # Llama chat model, which made every seeded trace un-replayable ("model
    # does not exist"). When the recorded model is gone, the branch engine
    # retries once on this model and labels the span `model_substituted`.
    # Empty string disables the fallback (fail loudly instead).
    replay_fallback_model: str = "openai/gpt-oss-120b"


settings = Settings()
