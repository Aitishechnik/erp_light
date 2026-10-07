"""Настройки приложения. Читаются из <корень проекта>/.env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_port: int = 4110
    api_port: int = 4111
    session_ttl_days: int = 30
    database_url: str = "postgresql+psycopg://erp_lite:erp_lite@127.0.0.1:5547/erp_lite"
    test_database_url: str = "postgresql+psycopg://erp_lite:erp_lite@127.0.0.1:5547/erp_lite_test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
