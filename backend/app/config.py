from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List
import logging
import os

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@postgres:5432/whatsapp_ai"
    redis_url: str = "redis://redis:6379/0"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_api_key: str = ""
    jwt_secret: str = "change_this_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    session_encryption_key: str = "change_this_32_byte_key_in_prod_"
    cors_origins: str = "http://localhost:3000"
    backend_port: int = 8000
    sessions_dir: str = "/app/sessions"
    media_dir: str = "/app/media"

    class Config:
        env_file = ".env"
        case_sensitive = False

    @model_validator(mode="after")
    def check_security_defaults(self):
        if self.jwt_secret == "change_this_in_production":
            logger.warning(
                "⚠️  SECURITY WARNING: Using default JWT_SECRET! "
                "Set the JWT_SECRET environment variable in production."
            )
        if self.session_encryption_key == "change_this_32_byte_key_in_prod_":
            logger.warning(
                "⚠️  SECURITY WARNING: Using default SESSION_ENCRYPTION_KEY! "
                "Set the SESSION_ENCRYPTION_KEY environment variable in production."
            )
        return self

    def get_cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


settings = Settings()
