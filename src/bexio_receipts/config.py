"""
Configuration management using Pydantic Settings.
Loads and validates environment variables and configuration files.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: str = "development"
    offline_mode: bool = False
    bexio_push_enabled: bool = False
    bexio_api_token: str = "offline"
    bexio_base_url: str = "https://api.bexio.com"

    # OCR Settings
    # GLM-OCR SDK (self-hosted via vLLM/SGLang)
    glm_ocr_api_host: str = "localhost"
    glm_ocr_api_port: int = 8080
    glm_ocr_layout_device: str = "cpu"  # "cpu" | "cuda" | "cuda:N"
    glm_ocr_timeout: int = 60  # total pipeline budget
    glm_ocr_connect_timeout: int = 120  # wait for vLLM to be ready
    glm_ocr_request_timeout: int = 180  # per-image inference budget

    # LLM Settings
    llm_provider: str = "ollama"  # or "openai", "openrouter"
    llm_model: str = "qwen3.5:9b"
    llm_timeout: int = 60
    ollama_url: str = "http://localhost:11434"
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "https://github.com/tazztone/bexio-receipts"
    openrouter_site_name: str = "Bexio Receipts"
    openrouter_use_structured_output: bool = True

    # Default accounts for bexio
    default_booking_account_id: int = 0
    default_bank_account_id: int = 0
    default_vat_rate: float = 8.1
    default_payment_terms_days: int = 30

    # bexio-receipts specific accounts
    bexio_allowed_soll_accounts: list[int] = [4400, 4200, 4270, 4201, 6460]
    bexio_haben_account_bank: int = 1020
    bexio_haben_account_cash: int = 1000
    bexio_accounts: dict[str, str] = {
        "4200": "Einkauf Handelsware (food/resale goods)",
        "4201": "Einkauf Handelsware Non-Food",
        "4270": "Gebühren Einkauf Handelswaren (fees/surcharges)",
        "4400": "Einkauf Dienstleistung (services)",
        "6460": "Kehrichtabfuhr, Sondermüll (waste disposal)",
    }

    # bexio-receipts specific paths
    inbox_path: str = "./inbox"
    review_username: str = "admin"
    review_password: str = "password"
    review_password_hash: str = ""
    review_users: dict[str, str] = {}  # Multi-user support {"username": "password"}
    review_users_hashed: dict[str, str] = {}
    secret_key: str = "change-me"
    database_path: str = "processed_receipts.db"
    review_dir: str = "./review_queue"
    review_skip_auth: bool = False
    max_receipt_age_days: int = 365

    # Google Drive Settings
    gdrive_credentials_file: str | None = None
    gdrive_token_path: str = "token.json"
    gdrive_folder_id: str | None = None
    gdrive_poll_interval: int = 60
    gdrive_processed_folder_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def validate_openrouter_model(self) -> "Settings":
        if self.llm_provider == "openrouter" and "/" not in (self.llm_model or ""):
            raise ValueError(
                "OpenRouter requires 'provider/model' format (e.g. 'anthropic/claude-3.5-sonnet')"
            )
        return self

    @model_validator(mode="after")
    def validate_passwords(self):
        is_dev = self.env == "development"
        if not is_dev and self.review_password == "password":
            raise ValueError(
                "review_password must be changed from 'password' in non-development environments"
            )
        if not is_dev and self.secret_key == "change-me":
            raise ValueError(
                "secret_key must be changed from 'change-me' in non-development environments"
            )

        if not self.offline_mode:
            if self.bexio_api_token == "offline":
                raise ValueError(
                    "bexio_api_token is required when offline_mode is False"
                )
            if self.default_booking_account_id == 0:
                raise ValueError(
                    "default_booking_account_id is required when offline_mode is False"
                )
            if self.default_bank_account_id == 0:
                raise ValueError(
                    "default_bank_account_id is required when offline_mode is False"
                )

        return self

    @model_validator(mode="after")
    def hash_passwords_for_auth(self) -> "Settings":
        import bcrypt

        def _hash(pwd: str) -> str:
            if pwd.startswith("$2b$") or pwd.startswith("$2a$"):
                return pwd
            return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()

        self.review_password_hash = _hash(self.review_password)
        self.review_users_hashed = {u: _hash(p) for u, p in self.review_users.items()}

        return self
