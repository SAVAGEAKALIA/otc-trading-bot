"""Compatibility exports for platform-owned technical feature engineering."""

from trading_platform.research.feature_engineering import (
    FeatureEngineer,
    FeatureEngineeringError,
)

__all__ = ["FeatureEngineer", "FeatureEngineeringError"]
