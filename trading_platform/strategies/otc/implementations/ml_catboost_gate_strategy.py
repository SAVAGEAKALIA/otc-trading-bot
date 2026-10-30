"""Conditional CatBoost candidate gate for scanner-generated directions."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd

from trading_platform.research.context_features import (
    CONTEXT_SCHEMA_VERSION,
    MarketContextProvider,
    candle_decision_ms,
    canonical_asset,
)
from trading_platform.research.feature_engineering import FeatureEngineer, FeatureEngineeringError


logger = logging.getLogger("MLCatBoostGate")


@dataclass
class CatBoostGateResult:
    available: bool
    accepted: bool
    probability: Optional[float] = None
    threshold: Optional[float] = None
    payout: Optional[float] = None
    expected_value: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    calibration_id: Optional[str] = None


class MLCatBoostGateStrategy:
    """Estimate whether an existing strategy candidate should be accepted.

    Despite the historical class name, this object is deliberately not a
    BaseStrategy and cannot vote or invent a CALL/PUT direction.
    """

    def __init__(
        self,
        model_path: str = "data/ml/models/catboost_gate.cbm",
        calibrator_path: str = "data/ml/models/catboost_calibrator.joblib",
        metadata_path: str = "data/ml/models/catboost_gate_metadata.json",
        context_provider: Optional[MarketContextProvider] = None,
    ) -> None:
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
    def available(self) -> bool:
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
            logger.warning("CatBoost gate disabled: %s", self.disabled_reason)
            return
        for label, path in (
            ("model", self.model_path),
            ("calibrator", self.calibrator_path),
            ("metadata", self.metadata_path),
        ):
            if not path.is_file():
                self.disabled_reason = f"{label} missing at {path}"
                logger.warning("CatBoost gate disabled: %s", self.disabled_reason)
                return
        try:
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if metadata.get("artifact_type") != "iqoption_candidate_meta_gate":
                raise ValueError("wrong artifact_type")
            if metadata.get("positive_class") != "candidate_wins":
                raise ValueError("positive class must be candidate_wins")
            if metadata.get("context_schema_version") != CONTEXT_SCHEMA_VERSION:
                raise ValueError("market-context schema mismatch")
            feature_order = list(metadata.get("feature_order", []))
            numeric = list(metadata.get("numeric_features", []))
            categorical = list(metadata.get("categorical_features", []))
            if not feature_order or feature_order != numeric + categorical:
                raise ValueError("invalid feature order in metadata")
            threshold = float(metadata.get("selected_threshold", 1.0))
            if not 0.5 <= threshold < 1.0:
                raise ValueError("invalid selected threshold")

            model = CatBoostClassifier()
            model.load_model(str(self.model_path))
            calibrator = joblib.load(self.calibrator_path)
            if list(model.feature_names_) != feature_order:
                raise ValueError("CatBoost feature names differ from metadata")

            self.model = model
            self.calibrator = calibrator
            self.metadata = metadata
            self.feature_order = feature_order
            self.numeric_features = numeric
            self.categorical_features = categorical
            self.threshold = threshold
            self.disabled_reason = ""
            logger.info(
                "Loaded conditional CatBoost gate: features=%d threshold=%.3f approved=%s",
                len(feature_order), threshold, self.offline_approved,
            )
        except Exception as exc:
            self.model = None
            self.calibrator = None
            self.disabled_reason = str(exc)
            logger.error("CatBoost gate disabled: %s", exc)

    def evaluate_candidate(
        self,
        *,
        asset: str,
        direction: str,
        strategy: str,
        candles: List[Dict[str, Any]],
        strategy_score: float,
        strategy_confidence: float,
        confluence: int,
        duration_minutes: int,
        regime: Optional[str],
        trend_5m: Optional[str],
        trend_15m: Optional[str],
        minimum_payout: float,
        minimum_expected_value: float,
    ) -> CatBoostGateResult:
        if not self.available:
            return CatBoostGateResult(
                available=False,
                accepted=False,
                warnings=[self.disabled_reason],
            )
        normalized_direction = str(direction).lower()
        if normalized_direction not in {"call", "put"}:
            return CatBoostGateResult(
                available=True,
                accepted=False,
                warnings=["Candidate direction must be call or put"],
            )
        if not candles:
            return CatBoostGateResult(
                available=True,
                accepted=False,
                warnings=["No completed candles supplied to CatBoost gate"],
            )
        try:
            candle_frame = pd.DataFrame(candles)
            featured = self.engineer.generate_features(
                candle_frame,
                is_training=False,
            )
            if featured.empty:
                raise FeatureEngineeringError("No candidate feature row")
            row = featured.iloc[-1].to_dict()
            decision_ms = candle_decision_ms(candle_frame.iloc[-1].to_dict(), 120)
            context = self.context_provider.snapshot(asset, decision_ms)
            row.update(context)
            row.update(
                asset=canonical_asset(asset),
                direction=normalized_direction,
                strategy=str(strategy or "unknown"),
                regime=str(regime or "unknown"),
                trend_5m=str(trend_5m or "unknown"),
                trend_15m=str(trend_15m or "unknown"),
                strategy_score=float(strategy_score),
                strategy_confidence=float(strategy_confidence),
                confluence=float(confluence),
                duration_minutes=float(duration_minutes),
                direction_sign=1.0 if normalized_direction == "call" else -1.0,
            )
            missing = [name for name in self.feature_order if name not in row]
            if missing:
                raise FeatureEngineeringError(
                    "Live CatBoost schema missing: " + ", ".join(missing)
                )
            vector = pd.DataFrame([{name: row[name] for name in self.feature_order}])
            for name in self.numeric_features:
                vector[name] = pd.to_numeric(vector[name], errors="coerce")
            for name in self.categorical_features:
                vector[name] = vector[name].fillna("unknown").astype(str)
            raw = float(
                np.asarray(
                    self.model.predict(vector, prediction_type="RawFormulaVal")
                ).reshape(-1)[0]
            )
            probability = float(
                self.calibrator.predict_proba(np.asarray([[raw]], dtype=float))[0, 1]
            )
            payout = float(context["payout_fraction"])
            payout_missing = bool(context["payout_missing"] >= 0.5)
            expected_value = (
                probability * payout - (1.0 - probability)
                if not payout_missing else None
            )
            reasons = [
                f"CatBoost candidate-win probability {probability:.1%} "
                f"(threshold {self.threshold:.1%})"
            ]
            warnings: List[str] = []
            accepted = probability >= self.threshold
            if payout_missing:
                accepted = False
                warnings.append("Current payout is missing or stale")
            elif payout < minimum_payout:
                accepted = False
                warnings.append(
                    f"Payout {payout:.1%} below minimum {minimum_payout:.1%}"
                )
            if expected_value is not None and expected_value < minimum_expected_value:
                accepted = False
                warnings.append(
                    f"Expected value {expected_value:.3f} below minimum "
                    f"{minimum_expected_value:.3f}"
                )
            if context["quote_missing"] >= 0.5 or context["mood_missing"] >= 0.5:
                accepted = False
                warnings.append("Required quote or mood context is stale")
            if not self.offline_approved:
                warnings.append("Artifact has not passed its offline deployment gate")
            return CatBoostGateResult(
                available=True,
                accepted=accepted,
                probability=probability,
                threshold=self.threshold,
                payout=None if payout_missing else payout,
                expected_value=expected_value,
                reasons=reasons,
                warnings=warnings,
                calibration_id=(
                    str(self.metadata.get("calibration_id", "")).strip() or None
                ),
            )
        except Exception as exc:
            logger.error("CatBoost candidate evaluation failed: %s", exc)
            return CatBoostGateResult(
                available=False,
                accepted=False,
                warnings=[f"CatBoost inference error: {exc}"],
            )
