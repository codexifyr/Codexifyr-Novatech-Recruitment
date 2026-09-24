from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
    env_file=("../.env", ".env"),
    extra="ignore",
)

    app_name: str = "NovaTech Recruitment API"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:3000"
    allowed_origins: str = "http://localhost:3000"

    supabase_url: str = ""
    supabase_publishable_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    supabase_secret_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")
    n8n_webhook_base_url: str = Field(default="", alias="WEBHOOK_BASE_URL")
    n8n_webhook_secret: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_enabled: bool = False
    otp_pepper: str = "change-me-in-production"
    otp_expiry_minutes: int = 10
    expose_test_otp: bool = False
    session_cookie_name: str = "novatech_session"
    refresh_cookie_name: str = "novatech_refresh"
    csrf_cookie_name: str = "novatech_csrf"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 28800
    shared_staff_login_enabled: bool = False
    persona_cookie_name: str = "novatech_persona"

    turnstile_secret_key: str = ""
    turnstile_enabled: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    google_calendar_client_id: str = ""
    google_calendar_client_secret: str = ""
    google_calendar_refresh_token: str = ""
    google_calendar_id: str = "primary"
    interview_reminder_minutes: int = 30
    interview_day_reminder_hours: int = 24

    @property
    def google_calendar_ready(self) -> bool:
        return bool(self.google_calendar_client_id and self.google_calendar_client_secret and self.google_calendar_refresh_token)

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.allowed_origins.split(",") if value.strip()]

    @property
    def supabase_ready(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def cookie_secure(self) -> bool:
        return self.session_cookie_secure or self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
