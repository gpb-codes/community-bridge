from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    PROJECT_NAME: str = "Community Bridge"
    ENVIRONMENT: Literal["development", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    ADMIN_API_KEY: str = "change-me-in-production"

    # Database
    DATABASE_URL: str = "postgresql://bridge:bridge@postgres:5432/community_bridge"

    # Redis / Queue
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    # Discord
    DISCORD_BOT_TOKEN: Optional[str] = None
    DISCORD_GUILD_ID: Optional[str] = None
    DISCORD_REQUIRED_INTENTS: str = "guilds,guild_messages,message_content"

    # WhatsApp (Meta Cloud API)
    WHATSAPP_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_WABA_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None
    WHATSAPP_API_BASE: str = "https://graph.facebook.com/v21.0"
    WHATSAPP_IS_OBA: bool = False  # Not an OBA: group creation/discovery falls back to MANUAL/PENDING

    # Formatting
    WHATSAPP_PREFIX: str = "🟢 [WhatsApp]"
    DISCORD_PREFIX: str = "🟣 [Discord]"
    BRIDGE_GENERATED_TTL_SECONDS: int = 86400

    # Security
    WEBHOOK_MAX_AGE_SECONDS: int = 300  # replay protection

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL


settings = Settings()
