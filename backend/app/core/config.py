from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (not the working directory): backend/.env, then repo-root .env.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_ENV_FILES = (_BACKEND_DIR / ".env", _BACKEND_DIR.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    anthropic_api_key: str | None = None
    model_name: str = "claude-sonnet-5"
    database_url: str = "sqlite:///./tasks.db"
    cors_origins: str = "http://localhost:5173"

    max_message_length: int = 1000
    max_title_length: int = 200
    max_description_length: int = 2000
    max_list_limit: int = 100
    max_stored_reply_length: int = 8000  # assistant replies are clipped to this when stored
    max_conversation_page: int = 200  # most messages returned/loaded per request
    context_message_limit: int = 6  # saved messages given to the model as conversation context
    context_entry_max_chars: int = 500  # each context entry is clipped to this many characters


@lru_cache
def get_settings() -> Settings:
    return Settings()


def env_file_found() -> bool:
    return any(p.is_file() for p in _ENV_FILES)
