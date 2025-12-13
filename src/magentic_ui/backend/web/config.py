# api/config.py

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URI: str = "postgresql+psycopg://postgres:postgres@localhost:5432/magentic_ui"
    API_DOCS: bool = False
    CLEANUP_INTERVAL: int = 300  # 5 minutes
    SESSION_TIMEOUT: int = 3600 * 100  # 24 hour
    CONFIG_DIR: str = "configs"  # Default config directory relative to app_root
    DEFAULT_USER_ID: str = "guestuser@gmail.com"
    UPGRADE_DATABASE: bool = False
    LANGGRAPH_API_URL: str | None = None

    model_config = {"env_prefix": "MAGENTIC_UI_"}


settings = Settings()
