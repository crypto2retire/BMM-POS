from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str = "bowenstreet-dev-secret-change-in-production"
    access_token_expire_hours: int = 8
    tax_rate: float = 0.05
    store_name: str = "Bowenstreet Market"
    dymo_label_size: str = "30347"
    openrouter_api_key: Optional[str] = None
    square_access_token: Optional[str] = None
    square_location_id: Optional[str] = None
    square_application_id: Optional[str] = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
