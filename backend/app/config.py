from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@postgres:5432/whatsapp_ai"
    redis_url: str = "redis://redis:6379/0"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
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

    def get_cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


settings = Settings()
