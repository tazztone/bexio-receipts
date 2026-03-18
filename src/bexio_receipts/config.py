from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    bexio_api_token: str
    bexio_base_url: str = "https://api.bexio.com"
    
    # OCR Settings
    ocr_engine: str = "paddleocr"  # or "glm-ocr"
    ocr_confidence_threshold: float = 0.85
    glm_ocr_model: str = "glm-ocr"
    glm_ocr_url: str = "http://localhost:11434" # Ollama default
    
    # LLM Settings
    llm_provider: str = "ollama"  # or "openai"
    llm_model: str = "qwen2.5:7b"
    
    # Default accounts for bexio
    default_booking_account_id: Optional[int] = None
    default_bank_account_id: Optional[int] = None
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
