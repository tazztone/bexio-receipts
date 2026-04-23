import pytest
from pydantic import ValidationError

from bexio_receipts.config import Settings


def test_config_security_enforcement():
    # Development mode allows defaults
    s = Settings(env="development", review_password="password", secret_key="change-me")
    assert s.review_password_hash.startswith("$2")

    # Production mode forbids default password
    with pytest.raises(ValidationError, match="review_password must be changed"):
        Settings(env="production", review_password="password")

    # Production mode forbids default secret_key
    with pytest.raises(ValidationError, match="secret_key must be changed"):
        Settings(env="production", review_password="secure", secret_key="change-me")

    # Production mode with secure values
    s2 = Settings(
        env="production",
        review_password="secure",
        secret_key="very-secure",
        bexio_api_token="token",
    )
    assert s2.secret_key == "very-secure"


def test_vision_model_gguf_auto_quantization():
    # GGUF model should auto-set quantization to gguf if not already gguf
    s = Settings(
        vision_model="qwen.gguf",
        vision_quantization="auto",
        offline_mode=True,
        _env_file=None,
    )
    assert s.vision_quantization == "gguf"

    # Explicit override should be overwritten because .gguf requires 'gguf' quantization
    s2 = Settings(
        vision_model="qwen.gguf",
        vision_quantization="gptq",
        offline_mode=True,
        _env_file=None,
    )
    assert s2.vision_quantization == "gguf"

    # Non-GGUF model should stay default (awq)
    s3 = Settings(vision_model="qwen-awq", offline_mode=True, _env_file=None)
    assert s3.vision_quantization == "awq"
