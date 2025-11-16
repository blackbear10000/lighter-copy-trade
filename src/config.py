"""
Configuration management for the Lighter Copy Trading System.
"""

import os
import json
from typing import List, Dict, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class AccountConfig(BaseModel):
    """Account configuration model."""
    index: int
    api_index: int
    private_key: str


class AppConfig(BaseModel):
    """Application configuration model."""
    base_url: str
    l1_address: str
    accounts: List[AccountConfig]
    max_slippage: float = Field(default=0.01, ge=0, le=1)
    stop_loss_ratio: float = Field(default=0.05, ge=0, le=1)
    scaling_factor: float = Field(default=1.0, ge=0.01, le=100)
    max_retries: int = Field(default=3, ge=0)
    retry_interval: int = Field(default=5, ge=1)
    telegram_bot_api_key: str
    telegram_group_id: str
    telegram_thread_id: Optional[int] = None  # Optional thread ID for forum groups
    api_key: Optional[str] = None  # API key for authentication

    @field_validator('accounts')
    @classmethod
    def validate_accounts(cls, v):
        if not v or len(v) == 0:
            raise ValueError("At least one account must be configured")
        return v


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    load_dotenv()
    
    # Load basic configuration
    base_url = os.getenv("BASE_URL", "https://mainnet.zklighter.elliot.ai")
    l1_address = os.getenv("L1_ADDRESS", "")
    
    # Load accounts
    accounts_json = os.getenv("ACCOUNTS", "[]")
    try:
        accounts_data = json.loads(accounts_json)
        accounts = [AccountConfig(**acc) for acc in accounts_data]
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise ValueError(f"Invalid ACCOUNTS format: {e}")
    
    # Load trading strategy parameters
    max_slippage = float(os.getenv("MAX_SLIPPAGE", "0.01"))
    stop_loss_ratio = float(os.getenv("STOP_LOSS_RATIO", "0.05"))
    scaling_factor = float(os.getenv("SCALING_FACTOR", "1.0"))
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    retry_interval = int(os.getenv("RETRY_INTERVAL", "5"))
    
    # Load Telegram configuration
    telegram_bot_api_key = os.getenv("TELEGRAM_BOT_API_KEY", "")
    telegram_group_id = os.getenv("TELEGRAM_GROUP_ID", "")
    telegram_thread_id_str = os.getenv("TELEGRAM_THREAD_ID", None)
    telegram_thread_id = int(telegram_thread_id_str) if telegram_thread_id_str else None
    
    # Load API key for authentication
    api_key = os.getenv("API_KEY", None)
    
    # Validate required fields
    if not l1_address:
        raise ValueError("L1_ADDRESS is required")
    if not telegram_bot_api_key:
        raise ValueError("TELEGRAM_BOT_API_KEY is required")
    if not telegram_group_id:
        raise ValueError("TELEGRAM_GROUP_ID is required")
    
    return AppConfig(
        base_url=base_url,
        l1_address=l1_address,
        accounts=accounts,
        max_slippage=max_slippage,
        stop_loss_ratio=stop_loss_ratio,
        scaling_factor=scaling_factor,
        max_retries=max_retries,
        retry_interval=retry_interval,
        telegram_bot_api_key=telegram_bot_api_key,
        telegram_group_id=telegram_group_id,
        telegram_thread_id=telegram_thread_id,
        api_key=api_key,
    )


# Global config instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config

