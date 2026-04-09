import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        url = os.environ.get("DATABASE_PRIVATE_URL", "")
    if not url:
        url = os.environ.get("DATABASE_PUBLIC_URL", "")
    return url


DEFAULT_OFFLINE_SNAPSHOT_PATH = str(
    Path.home()
    / "Library"
    / "Application Support"
    / "BMM-POS"
    / "offline"
    / "current-operational-backup.json.gz"
)


class Settings(BaseSettings):
    database_url: str = ""
    secret_key: str
    access_token_expire_hours: int = 8
    data_sync_secret: Optional[str] = None
    tax_rate: float = 0.05
    store_name: str = "Bowenstreet Market"
    openrouter_api_key: Optional[str] = None
    square_access_token: Optional[str] = None
    square_location_id: Optional[str] = None
    square_application_id: Optional[str] = None
    poynt_app_id: str = ""
    poynt_business_id: str = ""
    poynt_store_id: str = ""
    poynt_terminal_id: str = ""
    poynt_private_key: str = ""
    do_spaces_key: Optional[str] = None
    do_spaces_secret: Optional[str] = None
    do_spaces_region: str = "nyc3"
    do_spaces_bucket: Optional[str] = None
    do_spaces_cdn_endpoint: Optional[str] = None
    offline_mode: bool = False
    offline_allowed_payment_methods: str = "cash,gift_card,split,crypto_blackbox"
    offline_snapshot_path: str = DEFAULT_OFFLINE_SNAPSHOT_PATH
    offline_restore_on_start: bool = False
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_chat_model: str = "llama3.2:latest"
    local_llm_vision_model: str = ""
    local_llm_api_key: Optional[str] = None
    local_llm_timeout_seconds: float = 60.0

    model_config = {"env_file": (".env", ".env.offline"), "extra": "ignore"}

    @property
    def resolved_offline_payment_methods(self) -> list[str]:
        return [
            method.strip()
            for method in (self.offline_allowed_payment_methods or "").split(",")
            if method.strip()
        ]

    @property
    def local_ai_enabled(self) -> bool:
        return bool(self.local_llm_base_url and self.local_llm_chat_model)


_db_url = _resolve_database_url()
if _db_url:
    os.environ["DATABASE_URL"] = _db_url

settings = Settings()
