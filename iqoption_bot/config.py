"""
Configuration loading utilities.
Supports loading from environment variables for Docker deployment.
"""

import os
from typing import List


# Global defaults
DEFAULT_PAYOUT = 0.80  # 80% default payout when broker data is unavailable
DEFAULT_TIMEZONE = "Africa/Lagos"  # Signal channel timezone


def env(name: str, default: str = "") -> str:
    """Get string from environment variable."""
    v = os.environ.get(name)
    return v if v is not None else default


def env_int(name: str, default: int) -> int:
    """Get integer from environment variable."""
    v = os.environ.get(name)
    return int(v) if v is not None and str(v).strip() != "" else default


def env_float(name: str, default: float) -> float:
    """Get float from environment variable."""
    v = os.environ.get(name)
    return float(v) if v is not None and str(v).strip() != "" else default


def env_bool(name: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def env_int_list(name: str) -> List[int]:
    """Get list of integers from comma-separated environment variable."""
    raw = env(name, "")
    if not raw.strip():
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def load_config_from_env() -> dict:
    """
    Load complete bot configuration from environment variables.
    Returns a config dict compatible with OTCTradingBot.
    """
    # Ensure data directory exists for Docker volume
    # data_dir = env("DATA_DIR", ".")
    # if data_dir != ".":
        # os.makedirs(data_dir, exist_ok=True)
    # data_dir = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
    # os.makedirs(data_dir, exist_ok=True)
    data_dir = os.environ.get("DATA_DIR", "")
    if not data_dir:
        # Use current working directory + data folder
        data_dir = os.path.join(os.getcwd(), "data")

    os.makedirs(data_dir, exist_ok=True)

    return {
        # Telegram API
        "api_id": env_int("TG_API_ID", 0),
        "api_hash": env("TG_API_HASH", ""),
        "channel_name": env_int("TG_CHANNEL_ID", 0),
        "telegram_session": env("TG_SESSION_NAME", os.path.join(data_dir, "otc_session")),

        # Bot Control
        "admin_ids": env_int_list("TG_ADMIN_IDS"),
        "control_chat_id": env_int("TG_CONTROL_CHAT_ID", 0) or None,

        # Notification Settings
        "send_notifications": env_bool("SEND_NOTIFICATIONS", True),

        # IQ Option Credentials
        "iq_email": env("IQ_EMAIL", ""),
        "iq_password": env("IQ_PASSWORD", ""),
        "account_type": env("IQ_ACCOUNT_TYPE", "PRACTICE"),

        # Trading Settings
        "default_duration": env_int("DEFAULT_DURATION", 2),
        "signal_timezone": env("SIGNAL_TIMEZONE", DEFAULT_TIMEZONE),

        # Debug Mode
        "debug": env_bool("DEBUG", False),

        # Position Sizing Configuration
        "position_sizing": {
            "method": env("SIZING_METHOD", "fixed"),
            "fixed_amount": env_float("SIZING_FIXED_AMOUNT", 1.0),
            "fixed_percentage": env_float("SIZING_FIXED_PERCENTAGE", 0.01),
            "kelly_fraction": env_float("SIZING_KELLY_FRACTION", 0.25),
            "min_trade": env_float("SIZING_MIN_TRADE", 1.0),
            "max_trade": env_float("SIZING_MAX_TRADE", 50.0),
            "max_risk_percentage": env_float("SIZING_MAX_RISK_PERCENTAGE", 0.05),
        },

        # AI Analysis
        "ai_api_key": env("AI_API_KEY", ""),
        "ai_enabled": env_bool("AI_ENABLED", False),
        "confidence_threshold": env_float("AI_CONFIDENCE_THRESHOLD", 0.7),

        # Pattern Analysis
        "pattern_analysis_enabled": env_bool("PATTERN_ANALYSIS_ENABLED", True),
        "pattern_filter_enabled": env_bool("PATTERN_FILTER_ENABLED", False),  # Filter trades based on patterns
        "strict_pattern_filter": env_bool("STRICT_PATTERN_FILTER", False),  # Skip conflicting trades

        # Session Manager (Risk Control)
        "max_daily_loss": env_float("MAX_DAILY_LOSS", 50.0),
        "max_consecutive_losses": env_int("MAX_CONSECUTIVE_LOSSES", 3),
        "daily_profit_target": env_float("DAILY_PROFIT_TARGET", 100.0),

        # Martingale Strategy
        "martingale_enabled": env_bool("MARTINGALE_ENABLED", False),
        "martingale_max_steps": env_int("MARTINGALE_MAX_STEPS", 1),
        "martingale_multiplier": env_float("MARTINGALE_MULTIPLIER", 2.3),
        "martingale_duration": env_int("MARTINGALE_DURATION", 2),  # Fixed duration if not dynamically overridden
        "martingale_wait_for_pullback": env_bool("MARTINGALE_WAIT_FOR_PULLBACK", False),  # Wait for valid pullback before placing step

        # Signal Gatekeeper & MTF (Multi-Timeframe) Analysis
        "gatekeeper_enabled": env_bool("GATEKEEPER_ENABLED", True),
        "gatekeeper_mode_telegram": env("GATEKEEPER_MODE_TELEGRAM", "very_relaxed"),  # Mode for Telegram signals
        "gatekeeper_mode_scanner": env("GATEKEEPER_MODE_SCANNER", "normal"),  # Default to normal for OTC
        "gatekeeper_strict_mode": env_bool("GATEKEEPER_STRICT_MODE", True),  # Hard reject vs warning
        "martingale_reanalyzer_enabled": env_bool("MARTINGALE_REANALYZER_ENABLED", True),  # Audit recovery steps
        "martingale_reanalyzer_flip_enabled": env_bool("MARTINGALE_REANALYZER_FLIP_ENABLED", True),  # Allow flips during recovery
        "martingale_reanalyzer_min_score": env_float("MARTINGALE_REANALYZER_MIN_SCORE", 15.0),  # Conviction floor
        "reanalyzer_sentiment_weight": env_float("REANALYZER_SENTIMENT_WEIGHT", 0.6), # Smart Sentiment bias
        "reanalyzer_technical_weight": env_float("REANALYZER_TECHNICAL_WEIGHT", 0.4), # Gatekeeper technical bias
        "mtf_enabled": env_bool("MTF_ENABLED", True),  # Enable 5m/15m context
        "mtf_15m_enabled": env_bool("MTF_15M_ENABLED", True),  # Can disable 15m independently

        # OTC Scanner (Auto Signal Discovery)
        "scanner_enabled": env_bool("SCANNER_ENABLED", False),
        "scanner_interval": env_int("SCANNER_INTERVAL", 15),  # Scan interval in seconds
        "scanner_confidence_min": env_float("SCANNER_CONFIDENCE_MIN", 0.70),  # raised from 0.55 for OTC quality
        "scanner_trade_mode": env("SCANNER_TRADE_MODE", "multi"),  # single or multi

        # Scanner Professional Filters (A+ Setup Engine)
        "scanner_profile": env("SCANNER_PROFILE", "trend"),  # trend is safer for OTC
        "scanner_top_n_pairs": env_int("SCANNER_TOP_N_PAIRS", 15),  # Only scan top N pairs (0=all)
        "scanner_close_window_sec": env_int("SCANNER_CLOSE_WINDOW_SEC", 10),  # seconds near candle close
        "scanner_min_confluence": env_int("SCANNER_MIN_CONFLUENCE", 2),  # Lowered from 4 to allow multi-strategy setup
        "scanner_wait_for_pullback": env_bool("SCANNER_WAIT_FOR_PULLBACK", False),  # EMA14 filter
        "scanner_allowed_volatility": env("SCANNER_ALLOWED_VOLATILITY", "normal,low,high,extreme"),  # allow intense OTC movement
        "scanner_autostop_on_session_block": env_bool("SCANNER_AUTOSTOP_ON_SESSION_BLOCK", True),  # Auto-disable on risk stop
        "scanner_dynamic_timeframe": env_bool("SCANNER_DYNAMIC_TIMEFRAME", True),  # Use volatility-based duration
        "scanner_ml_enabled": env_bool("SCANNER_ML_ENABLED", False),  # Statistical Fingerprinting Engine
        "scanner_strategy": env("SCANNER_STRATEGY", "indicators"),  # indicators or mhi
        "scanner_precision_timing": env_bool("SCANNER_PRECISION_TIMING", True),  # Second 58 Rule
        # Logging
        "log_file": env("LOG_FILE", os.path.join(data_dir, "trade_log.json")),
    }


def create_default_config() -> dict:
    """
    Create a default configuration dict with placeholder values.
    Used when not loading from environment.
    """
    return {
        # Telegram API (get from my.telegram.org)
        "api_id": 0,
        "api_hash": "",
        "channel_name": 0,
        "telegram_session": "otc_session",

        # Bot Control
        "admin_ids": [],
        "control_chat_id": None,

        # Notification Settings
        "send_notifications": True,

        # IQ Option Credentials
        "iq_email": "",
        "iq_password": "",
        "account_type": "PRACTICE",

        # Trading Settings
        "default_duration": 2,
        "signal_timezone": DEFAULT_TIMEZONE,

        # Debug Mode
        "debug": False,

        # Position Sizing Configuration
        "position_sizing": {
            "method": "fixed",
            "fixed_amount": 1.0,
            "fixed_percentage": 0.01,
            "kelly_fraction": 0.25,
            "min_trade": 1.0,
            "max_trade": 50.0,
            "max_risk_percentage": 0.05,
        },

        # AI Analysis
        "ai_api_key": "",
        "ai_enabled": False,
        "confidence_threshold": 0.7,

        # Pattern Analysis
        "pattern_analysis_enabled": True,
        "pattern_filter_enabled": False,
        "strict_pattern_filter": False,

        # Session Manager (Risk Control)
        "max_daily_loss": 50.0,
        "max_consecutive_losses": 5,
        "daily_profit_target": 100.0,

        # Martingale Strategy
        "martingale_enabled": False,
        "martingale_max_steps": 1,
        "martingale_multiplier": 2.0,
        "martingale_duration": 2,  # Fixed 2-minute duration

        # Signal Gatekeeper & MTF (Multi-Timeframe) Analysis
        "gatekeeper_enabled": False,
        "gatekeeper_mode_telegram": "relaxed",
        "gatekeeper_mode_scanner": "normal",
        "gatekeeper_strict_mode": True,
        "mtf_enabled": True,
        "mtf_15m_enabled": False,

        # OTC Scanner (Auto Signal Discovery)
        "scanner_enabled": False,
        "scanner_interval": 15,  # Scan interval in seconds
        "scanner_confidence_min": 0.55,  # lowered from 0.85
        "scanner_trade_mode": "single",  # single or multi

        # Scanner Professional Filters (A+ Setup Engine)
        "scanner_profile": "trend",  # trend, reversal, mixed
        "scanner_top_n_pairs": 15,  # Only scan top N pairs (0=all)
        "scanner_close_window_sec": 10,  # seconds near candle close
        "scanner_min_confluence": 2,  # lowered from 4
        "scanner_wait_for_pullback": False,
        "scanner_allowed_volatility": "normal,low,high,extreme",  # Comma-sep
        "scanner_autostop_on_session_block": True,  # Auto-disable on risk stop
        "scanner_ml_enabled": False,
        "scanner_strategy": "indicators",
        "scanner_precision_timing": True,

        # Logging
        "log_file": "trade_log.json",
    }


# Strategy Settings (Global)
STRATEGY_PROFILE = env("STRATEGY_PROFILE", "hybrid")


