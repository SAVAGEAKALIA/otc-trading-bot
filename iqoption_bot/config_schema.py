import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

@dataclass
class TelegramConfig:
    api_id: int = 0
    api_hash: str = ""
    channel_name: Optional[int] = 0
    session_name: str = "otc_session"
    admin_ids: List[int] = field(default_factory=list)
    control_chat_id: Optional[int] = None
    send_notifications: bool = True

@dataclass
class SizingConfig:
    method: str = "fixed"
    fixed_amount: float = 1.0
    fixed_percentage: float = 0.01
    kelly_fraction: float = 0.25
    min_trade: float = 1.0
    max_trade: float = 50.0
    max_risk_percentage: float = 0.05

@dataclass
class RiskConfig:
    max_daily_loss: float = 50.0
    max_consecutive_losses: int = 3
    daily_profit_target: float = 100.0
    martingale_enabled: bool = False
    martingale_max_steps: int = 1
    martingale_multiplier: float = 2.3
    martingale_duration: int = 2
    martingale_wait_for_pullback: bool = False

@dataclass
class ScannerSettings:
    enabled: bool = False
    interval: int = 15
    confidence_min: float = 0.70
    trade_mode: str = "multi"
    profile: str = "trend"
    top_n_pairs: int = 15
    close_window_sec: int = 25
    min_confluence: int = 4
    require_mtf_alignment: bool = True
    allowed_volatility: List[str] = field(default_factory=lambda: ["normal", "low", "high", "extreme"])
    autostop_on_session_block: bool = True
    dynamic_timeframe: bool = True
    ml_enabled: bool = False
    strategy: str = "indicators"
    precision_timing: bool = True

@dataclass
class BotConfig:
    # IQ Option
    iq_email: str = ""
    iq_password: str = ""
    account_type: str = "PRACTICE"
    
    # Components
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    scanner: ScannerSettings = field(default_factory=ScannerSettings)
    
    # General
    default_duration: int = 2
    signal_timezone: str = "Africa/Lagos"
    debug: bool = False
    log_file: str = "trade_log.json"
    
    # AI Analysis
    ai_api_key: str = ""
    ai_enabled: bool = False
    ai_confidence_threshold: float = 0.7
    
    # Gatekeeper
    gatekeeper_enabled: bool = True
    gatekeeper_mode_telegram: str = "very_relaxed"
    gatekeeper_mode_scanner: str = "normal"
    gatekeeper_strict_mode: bool = True
    mtf_enabled: bool = True
    mtf_15m_enabled: bool = True

    def validate(self) -> List[str]:
        """Validate the configuration and return a list of errors."""
        errors = []
        if not self.iq_email:
            errors.append("IQ_EMAIL is required")
        if not self.iq_password:
            errors.append("IQ_PASSWORD is required")
        if self.telegram.api_id == 0:
            errors.append("TG_API_ID is required")
        if not self.telegram.api_hash:
            errors.append("TG_API_HASH is required")
        
        if self.sizing.method not in ("fixed", "percentage", "fractional_kelly", "kelly"):
            errors.append(f"Invalid sizing method: {self.sizing.method}")
            
        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert the config to a flat dictionary for backward compatibility."""
        # This mirrors the old config structure exactly
        return {
            "api_id": self.telegram.api_id,
            "api_hash": self.telegram.api_hash,
            "channel_name": self.telegram.channel_name,
            "telegram_session": self.telegram.session_name,
            "admin_ids": self.telegram.admin_ids,
            "control_chat_id": self.telegram.control_chat_id,
            "send_notifications": self.telegram.send_notifications,
            "iq_email": self.iq_email,
            "iq_password": self.iq_password,
            "account_type": self.account_type,
            "default_duration": self.default_duration,
            "signal_timezone": self.signal_timezone,
            "debug": self.debug,
            "log_file": self.log_file,
            "position_sizing": asdict(self.sizing),
            "ai_api_key": self.ai_api_key,
            "ai_enabled": self.ai_enabled,
            "confidence_threshold": self.ai_confidence_threshold,
            "max_daily_loss": self.risk.max_daily_loss,
            "max_consecutive_losses": self.risk.max_consecutive_losses,
            "daily_profit_target": self.risk.daily_profit_target,
            "martingale_enabled": self.risk.martingale_enabled,
            "martingale_max_steps": self.risk.martingale_max_steps,
            "martingale_multiplier": self.risk.martingale_multiplier,
            "martingale_duration": self.risk.martingale_duration,
            "martingale_wait_for_pullback": self.risk.martingale_wait_for_pullback,
            "gatekeeper_enabled": self.gatekeeper_enabled,
            "gatekeeper_mode_telegram": self.gatekeeper_mode_telegram,
            "gatekeeper_mode_scanner": self.gatekeeper_mode_scanner,
            "gatekeeper_strict_mode": self.gatekeeper_strict_mode,
            "mtf_enabled": self.mtf_enabled,
            "mtf_15m_enabled": self.mtf_15m_enabled,
            "scanner_enabled": self.scanner.enabled,
            "scanner_interval": self.scanner.interval,
            "scanner_confidence_min": self.scanner.confidence_min,
            "scanner_trade_mode": self.scanner.trade_mode,
            "scanner_profile": self.scanner.profile,
            "scanner_top_n_pairs": self.scanner.top_n_pairs,
            "scanner_close_window_sec": self.scanner.close_window_sec,
            "scanner_min_confluence": self.scanner.min_confluence,
            "scanner_require_mtf_alignment": self.scanner.require_mtf_alignment,
            "scanner_allowed_volatility": ",".join(self.scanner.allowed_volatility),
            "scanner_autostop_on_session_block": self.scanner.autostop_on_session_block,
            "scanner_dynamic_timeframe": self.scanner.dynamic_timeframe,
            "scanner_ml_enabled": self.scanner.ml_enabled,
            "scanner_strategy": self.scanner.strategy,
            "scanner_precision_timing": self.scanner.precision_timing,
        }

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Load configuration from environment variables (fallback to old config.py)."""
        from .config import load_config_from_env
        old_config = load_config_from_env()
        return cls.from_dict(old_config)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotConfig":
        """Load configuration from a dictionary (the old flat structure)."""
        tg_data = {
            "api_id": data.get("api_id", 0),
            "api_hash": data.get("api_hash", ""),
            "channel_name": data.get("channel_name", 0),
            "session_name": data.get("telegram_session", "otc_session"),
            "admin_ids": data.get("admin_ids", []),
            "control_chat_id": data.get("control_chat_id"),
            "send_notifications": data.get("send_notifications", True),
        }
        
        sizing_data = data.get("position_sizing", {})
        
        vol = data.get("scanner_allowed_volatility", "normal,low,high,extreme")
        vol_list = [v.strip() for v in vol.split(",") if v.strip()]
        
        scanner_data = {
            "enabled": data.get("scanner_enabled", False),
            "interval": data.get("scanner_interval", 15),
            "confidence_min": data.get("scanner_confidence_min", 0.70),
            "trade_mode": data.get("scanner_trade_mode", "multi"),
            "profile": data.get("scanner_profile", "trend"),
            "top_n_pairs": data.get("scanner_top_n_pairs", 15),
            "close_window_sec": data.get("scanner_close_window_sec", 25),
            "min_confluence": data.get("scanner_min_confluence", 4),
            "require_mtf_alignment": data.get("scanner_require_mtf_alignment", True),
            "allowed_volatility": vol_list,
            "autostop_on_session_block": data.get("scanner_autostop_on_session_block", True),
            "dynamic_timeframe": data.get("scanner_dynamic_timeframe", True),
            "ml_enabled": data.get("scanner_ml_enabled", False),
            "strategy": data.get("scanner_strategy", "indicators"),
            "precision_timing": data.get("scanner_precision_timing", True),
        }
        
        risk_data = {
            "max_daily_loss": data.get("max_daily_loss", 50.0),
            "max_consecutive_losses": data.get("max_consecutive_losses", 3),
            "daily_profit_target": data.get("daily_profit_target", 100.0),
            "martingale_enabled": data.get("martingale_enabled", False),
            "martingale_max_steps": data.get("martingale_max_steps", 1),
            "martingale_multiplier": data.get("martingale_multiplier", 2.3),
            "martingale_duration": data.get("martingale_duration", 2),
            "martingale_wait_for_pullback": data.get("martingale_wait_for_pullback", False),
        }
        
        return cls(
            iq_email=data.get("iq_email", ""),
            iq_password=data.get("iq_password", ""),
            account_type=data.get("account_type", "PRACTICE"),
            telegram=TelegramConfig(**tg_data),
            sizing=SizingConfig(**sizing_data) if sizing_data else SizingConfig(),
            risk=RiskConfig(**risk_data),
            scanner=ScannerSettings(**scanner_data),
            default_duration=data.get("default_duration", 2),
            signal_timezone=data.get("signal_timezone", "Africa/Lagos"),
            debug=data.get("debug", False),
            log_file=data.get("log_file", "trade_log.json"),
            ai_api_key=data.get("ai_api_key", ""),
            ai_enabled=data.get("ai_enabled", False),
            ai_confidence_threshold=data.get("confidence_threshold", 0.7),
            gatekeeper_enabled=data.get("gatekeeper_enabled", True),
            gatekeeper_mode_telegram=data.get("gatekeeper_mode_telegram", "very_relaxed"),
            gatekeeper_mode_scanner=data.get("gatekeeper_mode_scanner", "normal"),
            gatekeeper_strict_mode=data.get("gatekeeper_strict_mode", True),
            mtf_enabled=data.get("mtf_enabled", True),
            mtf_15m_enabled=data.get("mtf_15m_enabled", True),
        )

    def save(self, path: str):
        """Save config to a JSON file."""
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=4)

    @classmethod
    def load(cls, path: str) -> "BotConfig":
        """Load config from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
            # Reconstruct nested dataclasses
            data["telegram"] = TelegramConfig(**data["telegram"])
            data["sizing"] = SizingConfig(**data["sizing"])
            data["risk"] = RiskConfig(**data["risk"])
            data["scanner"] = ScannerSettings(**data["scanner"])
            return cls(**data)
