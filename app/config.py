from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str = "bowenstreet-dev-secret-change-in-production"
    access_token_expire_hours: int = 8
    tax_rate: float = 0.055
    store_name: str = "Bowenstreet Market"
    dymo_label_size: str = "30336"
    openrouter_api_key: Optional[str] = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
