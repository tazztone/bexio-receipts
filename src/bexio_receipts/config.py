from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    env: str = "development"
    bexio_api_token: str
    bexio_base_url: str = "https://api.bexio.com"
    
    # OCR Settings
    ocr_engine: str = "paddleocr"  # or "glm-ocr"
    ocr_confidence_threshold: float = 0.85
    glm_ocr_model: str = "glm-ocr"
    glm_ocr_url: str = "http://localhost:11434" # Ollama default
    
    # LLM Settings
    llm_provider: str = "ollama"  # or "openai"
    llm_model: str = "qwen3.5:9b"
    
    # Default accounts for bexio
    default_booking_account_id: int | None = None
    default_bank_account_id: int | None = None
    default_vat_rate: float = 8.1
    
    # bexio-receipts specific
    inbox_path: str = "./inbox"
    review_password: str
    secret_key: str = "super-secret-key-change-me-in-prod"
    database_path: str = "processed_receipts.db"
    review_dir: str = "./review_queue"
    max_receipt_age_days: int = 365
    
    # IMAP Settings
    imap_server: str | None = None
    imap_user: str | None = None
    imap_password: str | None = None
    imap_folder: str = "INBOX"
    imap_poll_interval: int = 300  # seconds
    
    # Telegram Settings
    telegram_bot_token: str | None = None
    telegram_allowed_users: list[int] = [] # List of user IDs

    # Google Drive Settings
    gdrive_credentials_file: str | None = None
    gdrive_token_path: str = "token.json"
    gdrive_folder_id: str | None = None
    gdrive_poll_interval: int = 60
    gdrive_processed_folder_id: str | None = None
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
