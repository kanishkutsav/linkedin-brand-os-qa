from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LinkedIn Personal Brand OS"
    environment: str = "development"
    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./brand_os.db"
    emergency_stop: bool = False
    approval_ttl_minutes: int = 60
    cors_origins: str = "http://localhost:3000"
    secret_key: str = "dev-secret-change-me"
    render_external_url: str | None = None
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    jwt_secret: str | None = None
    frontend_url: str | None = None
    linkedin_client_id: str | None = None
    linkedin_client_secret: str | None = None
    linkedin_api_base_url: str | None = None
    linkedin_api_version: str = "202609"
    api_base_url: str | None = None
    linkedin_redirect_uri: str | None = None
    # Request analytics scopes only after LinkedIn Community Management access is approved.
    linkedin_analytics_oauth_enabled: bool = False

    # LLM provider routing
    # OpenRouter is the primary free-inference provider.
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openrouter/free"

    # Groq is the callback provider. GPT-OSS 120B is currently available on
    # Groq's free tier with rate limits; paid usage begins only after upgrading.
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"

    # Retained only for current web-grounded research until research is moved
    # to the same provider router.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    learning_embedding_model: str = "gemini-embedding-001"
    published_post_retention_limit: int = 10
    learning_event_retention_days: int = 30

    agent_enabled: bool = True
    agent_timezone: str = "Asia/Kolkata"
    agent_daily_discovery_enabled: bool = True
    agent_daily_discovery_hour: int = 9
    agent_daily_discovery_minute: int = 0
    agent_calendar_enabled: bool = True
    agent_calendar_hour: int = 9
    agent_calendar_minute: int = 15
    agent_in_process_schedule_enabled: bool = True
    scheduled_job_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        for origin in (self.render_external_url, self.frontend_url):
            if origin and origin.rstrip("/") not in {item.rstrip("/") for item in origins}:
                origins.append(origin.rstrip("/"))
        return origins

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production" or self.app_env.lower() == "production"


settings = Settings()
