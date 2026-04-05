import os
from typing import Optional
from pydantic_settings import BaseSettings


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        url = os.environ.get("DATABASE_PRIVATE_URL", "")
    if not url:
        url = os.environ.get("DATABASE_PUBLIC_URL", "")
    return url


class Settings(BaseSettings):
    database_url: str = ""
    secret_key: str
    access_token_expire_hours: int = 8
    tax_rate: float = 0.05
    store_name: str = "Bowenstreet Market"
    dymo_label_size: str = "30347"
    openrouter_api_key: Optional[str] = None
    square_access_token: Optional[str] = None
    square_location_id: Optional[str] = None
    square_application_id: Optional[str] = None
    poynt_app_id: str = ""
    poynt_business_id: str = ""
    poynt_store_id: str = ""
    poynt_terminal_id: str = ""
    poynt_private_key: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


_db_url = _resolve_database_url()
if _db_url:
    os.environ["DATABASE_URL"] = _db_url

settings = Settings()
