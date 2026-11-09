"""Directional CatBoost inference from enriched closed-candle features."""

from __future__ import annotations

import json
import logging
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd

from .base import BaseStrategy, StrategyResult
from trading_platform.research.context_features import (
    CONTEXT_SCHEMA_VERSION,
    MarketContextProvider,
    canonical_asset,
)
from trading_platform.research.feature_engineering import FeatureEngineer, FeatureEngineeringError


logger = logging.getLogger("MLCatBoostDirectional")


class MLDirectionalCatBoostStrategy(BaseStrategy):
    """Predict the direction of the next exact two-minute broker candle."""

    def __init__(
        self,
        model_path: str = "data/ml/models/catboost_directional.cbm",
        calibrator_path: str = "data/ml/models/catboost_directional_calibrator.joblib",
        metadata_path: str = "data/ml/models/catboost_directional_metadata.json",
        context_provider: Optional[MarketContextProvider] = None,
    ) -> None:
        super().__init__("ML_CatBoost_Directional")
        self.model_path = Path(model_path)
        self.calibrator_path = Path(calibrator_path)
        self.metadata_path = Path(metadata_path)
        self.context_provider = context_provider or MarketContextProvider()
        self.engineer = FeatureEngineer()
        self.model = None
        self.calibrator = None
        self.metadata: Dict[str, Any] = {}
        self.feature_order: List[str] = []
        self.numeric_features: List[str] = []
        self.categorical_features: List[str] = []
        self.threshold = 1.0
        self.disabled_reason = "Artifacts not loaded"
        self._load()

    @property
    def is_available(self) -> bool:
        return (
            self.model is not None
            and self.calibrator is not None
            and not self.disabled_reason
        )

    @property
    def offline_approved(self) -> bool:
        return bool(self.metadata.get("offline_deployment_approved", False))

    def _load(self) -> None:
        try:
            from catboost import CatBoostClassifier
        except ImportError:
            self.disabled_reason = "catboost is not installed"
            return
        for label, path in (
            ("model", self.model_path),
            ("calibrator", self.calibrator_path),
            ("metadata", self.metadata_path),
        ):
            if not path.is_file():
                self.disabled_reason = f"{label} missing at {path}"
                return
        try:
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if metadata.get("artifact_type") != "iqoption_directional_catboost":
                raise ValueError("wrong artifact_type")
            if metadata.get("positive_class") != "next_candle_up":
                raise ValueError("positive class must be next_candle_up")
            if metadata.get("context_schema_version") != CONTEXT_SCHEMA_VERSION:
                raise ValueError("market-context schema mismatch")
            if int(metadata.get("timeframe_seconds", 0)) != 120:
                raise ValueError("directional model must use 120-second candles")
            required_ta = str(metadata.get("pandas_ta_version", "")).strip()
            installed_ta = importlib_metadata.version("pandas-ta")
            if required_ta and required_ta != installed_ta:
                raise ValueError(
                    f"pandas-ta mismatch: model={required_ta}, runtime={installed_ta}"
                )
            feature_order = list(metadata.get("feature_order", []))
            numeric = list(metadata.get("numeric_features", []))
            categorical = list(metadata.get("categorical_features", []))
            if not feature_order or feature_order != numeric + categorical:
                raise ValueError("invalid feature order in metadata")
            threshold = float(metadata.get("selected_confidence_threshold", 1.0))
            if not 0.5 <= threshold < 1.0:
                raise ValueError("invalid directional confidence threshold")
            model = CatBoostClassifier()
            model.load_model(str(self.model_path))
            if list(model.feature_names_) != feature_order:
                raise ValueError("CatBoost feature names differ from metadata")
            self.calibrator = joblib.load(self.calibrator_path)
            self.model = model
            self.metadata = metadata
            self.feature_order = feature_order
            self.numeric_features = numeric
            self.categorical_features = categorical
            self.threshold = threshold
            self.disabled_reason = ""
            logger.info(
                "Loaded directional CatBoost: features=%d threshold=%.3f approved=%s",
                len(feature_order), threshold, self.offline_approved,
            )
        except Exception as exc:
            self.model = None
            self.calibrator = None
            self.disabled_reason = str(exc)
            logger.error("Directional CatBoost disabled: %s", exc)

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        if not self.is_available:
            return StrategyResult(
                0.0, "neutral", 0.0, [], [self.disabled_reason], False
            )
        if len(candles) < 65:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"Need at least 65 closed candles; got {len(candles)}"], False,
            )
        symbol = canonical_asset(str(kwargs.get("symbol", "Unknown")))
        trained_assets = set(self.metadata.get("assets", []))
        if trained_assets and symbol not in trained_assets:
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"Directional CatBoost was not trained for {symbol}"], False,
            )
        try:
            frame = self.context_provider.enrich_candles(candles, symbol, 120)
            latest_context = frame.iloc[-1]
            if float(latest_context.get("context_complete", 0.0)) < 0.5:
                return StrategyResult(
                    0.0, "neutral", 0.0, [],
                    ["Required live quote/mood/payout context is missing or stale"],
                    False,
                )
            featured = self.engineer.generate_features(frame, is_training=False)
            if featured.empty:
                raise FeatureEngineeringError("No directional feature row")
            row = featured.iloc[-1].to_dict()
            row["asset"] = symbol
            missing = [name for name in self.feature_order if name not in row]
            if missing:
                raise FeatureEngineeringError(
                    "Directional CatBoost schema missing: " + ", ".join(missing)
                )
            vector = pd.DataFrame(
                [{name: row[name] for name in self.feature_order}]
            )
            for name in self.numeric_features:
                vector[name] = pd.to_numeric(vector[name], errors="coerce")
            if vector[self.numeric_features].isna().any().any():
                raise FeatureEngineeringError("Latest directional features contain NaN")
            for name in self.categorical_features:
                vector[name] = vector[name].fillna("unknown").astype(str)
            raw = float(np.asarray(self.model.predict(
                vector, prediction_type="RawFormulaVal"
            )).reshape(-1)[0])
            probability_up = float(
                self.calibrator.predict_proba(
                    np.asarray([[raw]], dtype=float)
                )[0, 1]
            )
            direction = "call" if probability_up >= 0.5 else "put"
            confidence = max(probability_up, 1.0 - probability_up)
            payout = float(latest_context.get("payout_fraction", 0.0))
            minimum_payout = float(kwargs.get("ml_min_payout", 0.75))
            minimum_ev = float(kwargs.get("ml_min_expected_value", 0.02))
            expected_value = confidence * payout - (1.0 - confidence)
            reasons = [
                f"Directional CatBoost {direction.upper()}: {confidence:.1%}",
                f"Current payout {payout:.1%}; model EV {expected_value:.3f}",
            ]
            warnings = []
            if not self.offline_approved:
                warnings.append(
                    "Directional artifact is research-only: offline deployment gate failed"
                )
            should_trade = confidence >= self.threshold
            if payout < minimum_payout:
                should_trade = False
                warnings.append(
                    f"Payout {payout:.1%} below minimum {minimum_payout:.1%}"
                )
            if expected_value < minimum_ev:
                should_trade = False
                warnings.append(
                    f"Expected value {expected_value:.3f} below minimum {minimum_ev:.3f}"
                )
            calibration_id = str(self.metadata.get("calibration_id", "")).strip() or None
            return StrategyResult(
                score=confidence * 100.0,
                direction=direction,
                confidence=confidence,
                reasons=reasons,
                warnings=warnings,
                should_trade=should_trade,
                confluence=1 if should_trade else 0,
                calibrated_win_probability=(confidence if calibration_id else None),
                calibration_id=calibration_id,
            )
        except Exception as exc:
            logger.error("Directional CatBoost inference failed: %s", exc)
            return StrategyResult(
                0.0, "neutral", 0.0, [],
                [f"Directional CatBoost inference error: {exc}"], False,
            )
