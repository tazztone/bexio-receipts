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
    glm_ocr_model: str = "glm-ocr"
    glm_ocr_url: str = "http://localhost:11434"  # Ollama default
    glm_ocr_timeout: int = 25

    # LLM Settings
    llm_provider: str = "ollama"  # or "openai"
    llm_model: str = "qwen3.5:9b"
    llm_timeout: int = 30
    ollama_url: str = "http://localhost:11434"
    openai_api_key: str | None = None

    # Default accounts for bexio
    default_booking_account_id: int = 0
    default_bank_account_id: int = 0
    default_vat_rate: float = 8.1
    default_payment_terms_days: int = 30

    # bexio-receipts specific accounts
    bexio_allowed_soll_accounts: list[int] = [4400, 4200, 4270, 4201, 6460]
    bexio_haben_account_bank: int = 1020
    bexio_haben_account_cash: int = 1000

    # bexio-receipts specific paths
    inbox_path: str = "./inbox"
    review_username: str = "admin"
    review_password: str = "password"
    review_users: dict[str, str] = {}  # Multi-user support {"username": "password"}
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
    def validate_passwords(self):
        if self.env != "development" and self.review_password == "password":
            raise ValueError(
                "review_password must be changed from 'password' in non-development environments"
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

        # Hash passwords if they are not already hashed
        import bcrypt

        def hash_pwd(pwd: str) -> str:
            if pwd.startswith("$2b$") or pwd.startswith("$2a$"):
                return pwd
            return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()

        self.review_password = hash_pwd(self.review_password)

        hashed_users = {}
        for user, pwd in self.review_users.items():
            hashed_users[user] = hash_pwd(pwd)
        self.review_users = hashed_users

        return self
