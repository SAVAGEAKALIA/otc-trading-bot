"""Validated ONNX LSTM inference for closed IQ Option candles."""

import logging
import pickle
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .base import BaseStrategy, StrategyResult
from trading_platform.research.feature_engineering import FeatureEngineer, FeatureEngineeringError
from trading_platform.research.context_features import CONTEXT_SCHEMA_VERSION, MarketContextProvider

logger = logging.getLogger("MLLSTMStrategy")

try:
    import onnxruntime as ort
except ImportError:
    ort = None

try:
    import joblib
except ImportError:
    joblib = None


class MLLSTMStrategy(BaseStrategy):
    """Run a compatible LSTM artifact without changing scanner risk policy."""

    MIN_LIVE_CONFIDENCE = 0.60

    def __init__(
        self,
        model_path: str = "data/ml/models/deep_lstm_v1.onnx",
        scaler_path: str = "data/ml/models/lstm_scaler.pkl",
        metadata_path: str = "data/ml/models/lstm_metadata.pkl",
        min_live_confidence: float = MIN_LIVE_CONFIDENCE,
        context_provider: MarketContextProvider | None = None,
    ):
        super().__init__("ML_LSTM")
        self.model_path = Path(model_path)
        self.scaler_path = Path(scaler_path)
        self.metadata_path = Path(metadata_path)
        self.min_live_confidence = float(min_live_confidence)

        self.ort_session = None
        self.scaler = None
        self.metadata: Dict[str, Any] = {}
        self.seq_length = 90
        self.warmup_candles = 40
        self.scale_idx = 0
        self.features: List[str] = []
        self.asset_features: List[str] = []
        self.trained_threshold = self.min_live_confidence
        self.threshold = self.min_live_confidence
        self.output_type = "logit"
        self.calibration_id: str | None = None
        self.disabled_reason = "Model not loaded"
        self.engineer = FeatureEngineer()
        self.context_provider = context_provider or MarketContextProvider()
        self.requires_market_context = False
        self._load_assets()

    @property
    def is_available(self) -> bool:
        return self.ort_session is not None and self.scaler is not None and not self.disabled_reason

    def _disable(self, reason: str) -> None:
        self.ort_session = None
        self.scaler = None
        self.disabled_reason = reason
        logger.error("LSTM disabled: %s", reason)

    def _load_assets(self) -> None:
        """Load model artifacts and reject incompatible schemas before trading."""
        if ort is None or joblib is None:
            self._disable("onnxruntime and joblib are required")
            return
        if not 0.5 < self.min_live_confidence < 1.0:
            self._disable("min_live_confidence must be between 0.5 and 1.0")
            return
        for label, path in (
            ("ONNX model", self.model_path),
            ("scaler", self.scaler_path),
            ("metadata", self.metadata_path),
        ):
            if not path.is_file():
                self._disable(f"{label} missing at {path}")
                return

        try:
            session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
            scaler = joblib.load(self.scaler_path)
            with self.metadata_path.open("rb") as handle:
                metadata = pickle.load(handle)

            features = list(metadata.get("features", []))
            asset_features = list(metadata.get("asset_features", []))
            scale_idx = int(metadata.get("scale_idx", 0))
            if not features:
                raise ValueError("metadata has no feature list")
            if not 0 < scale_idx <= len(features):
                raise ValueError("metadata scale_idx is outside the feature list")
            if not set(asset_features).issubset(features):
                raise ValueError("metadata asset features are absent from the feature list")
            if getattr(scaler, "n_features_in_", scale_idx) != scale_idx:
                raise ValueError(
                    "scaler feature count does not match metadata scale_idx"
                )

            input_meta = session.get_inputs()[0]
            shape = input_meta.shape
            expected_seq = shape[1] if len(shape) >= 3 else None
            expected_features = shape[2] if len(shape) >= 3 else None
            if isinstance(expected_features, int) and expected_features != len(features):
                raise ValueError(
                    f"ONNX expects {expected_features} features, metadata has {len(features)}"
                )

            output_type = str(metadata.get("output_type", "logit")).lower()
            if output_type not in {"logit", "probability"}:
                raise ValueError("metadata output_type must be logit or probability")
            trained_threshold = float(metadata.get("threshold", self.min_live_confidence))
            if not 0.0 < trained_threshold < 1.0:
                raise ValueError("metadata threshold must be between 0 and 1")
            sequence_length = int(metadata.get("sequence_length", self.seq_length))
            warmup_candles = int(metadata.get("warmup_candles", 40))
            if sequence_length < 2:
                raise ValueError("metadata sequence_length must be at least 2")
            if warmup_candles < 0:
                raise ValueError("metadata warmup_candles cannot be negative")
            requires_market_context = bool(
                metadata.get("requires_market_context", False)
            )
            if requires_market_context:
                if metadata.get("context_schema_version") != CONTEXT_SCHEMA_VERSION:
                    raise ValueError("LSTM market-context schema mismatch")
                if not bool(metadata.get("deployment_approved", False)):
                    raise ValueError(
                        "Enriched LSTM artifact did not pass its offline "
                        "deployment gate"
                    )
                calibration_id = str(metadata.get("calibration_id", "")).strip()
                if not calibration_id:
                    raise ValueError("approved LSTM artifact has no calibration ID")
                if not bool(metadata.get("strict_provenance_manifest", False)):
                    raise ValueError("approved LSTM artifact lacks strict provenance")
            else:
                calibration_id = None
            required_pandas_ta = str(
                metadata.get("pandas_ta_version", "")
            ).strip()
            if required_pandas_ta:
                try:
                    installed_pandas_ta = importlib_metadata.version("pandas-ta")
                except importlib_metadata.PackageNotFoundError:
                    installed_pandas_ta = ""
                if installed_pandas_ta != required_pandas_ta:
                    raise ValueError(
                        "pandas-ta artifact/runtime mismatch: "
                        f"model={required_pandas_ta}, "
                        f"runtime={installed_pandas_ta or 'missing'}"
                    )
            if isinstance(expected_seq, int) and expected_seq != sequence_length:
                raise ValueError(
                    f"ONNX sequence length {expected_seq} does not match "
                    f"metadata sequence_length {sequence_length}"
                )

            self.ort_session = session
            self.scaler = scaler
            self.metadata = metadata
            self.features = features
            self.asset_features = asset_features
            self.scale_idx = scale_idx
            self.output_type = output_type
            self.seq_length = sequence_length
            self.warmup_candles = warmup_candles
            self.trained_threshold = trained_threshold
            self.threshold = max(trained_threshold, self.min_live_confidence)
            self.requires_market_context = requires_market_context
            self.calibration_id = calibration_id
            self.disabled_reason = ""
            if trained_threshold < self.min_live_confidence:
                logger.warning(
                    "LSTM metadata threshold %.3f raised to live floor %.3f",
                    trained_threshold,
                    self.min_live_confidence,
                )
            logger.info(
                "Loaded LSTM model: sequence=%s, features=%s, scaled=%s, threshold=%.3f",
                self.seq_length,
                len(self.features),
                self.scale_idx,
                self.threshold,
            )
        except Exception as exc:
            self._disable(str(exc))

    def set_runtime_threshold(self, threshold: float) -> None:
        """Set a temporary operator threshold; resets to artifact policy on restart."""
        threshold = float(threshold)
        if not 0.5 <= threshold < 1.0:
            raise ValueError("LSTM threshold must be between 0.50 and 0.99")
        self.threshold = threshold
        logger.warning(
            "LSTM runtime threshold changed to %.3f (artifact threshold %.3f)",
            self.threshold,
            self.trained_threshold,
        )

    def analyze(self, candles: List[Dict[str, Any]], **kwargs) -> StrategyResult:
        if not self.is_available:
            return StrategyResult(
                0, "neutral", 0.0, [], [self.disabled_reason], False
            )
        if not candles:
            return StrategyResult(0, "neutral", 0.0, [], ["No closed candles"], False)

        try:
            min_required = self.seq_length + self.warmup_candles
            if len(candles) < min_required:
                print(
                    f"   🧠 [{kwargs.get('symbol', 'Unknown')}] LSTM skipped: "
                    f"need {min_required} closed candles, got {len(candles)}"
                )
                return StrategyResult(
                    0,
                    "neutral",
                    0.0,
                    [],
                    [f"Need at least {min_required} closed candles; got {len(candles)}"],
                    False,
                )

            symbol = str(kwargs.get("symbol", "Unknown")).upper()
            candle_frame = pd.DataFrame(candles)
            if self.requires_market_context:
                candle_frame = self.context_provider.enrich_candles(
                    candle_frame,
                    symbol,
                    int(self.metadata.get("timeframe_seconds", 120)),
                )
                if candle_frame.empty or float(
                    candle_frame.iloc[-1].get("context_complete", 0.0)
                ) < 0.5:
                    return StrategyResult(
                        0,
                        "neutral",
                        0.0,
                        [],
                        ["Required live quote/mood/payout context is missing or stale"],
                        False,
                    )
            features_df = self.engineer.generate_features(
                candle_frame, is_training=False
            )
            expected_asset_col = f"asset_{symbol}"
            if self.asset_features and expected_asset_col not in self.asset_features:
                return StrategyResult(
                    0,
                    "neutral",
                    0.0,
                    [],
                    [f"LSTM was not trained for {symbol}"],
                    False,
                )
            for asset_col in self.asset_features:
                features_df[asset_col] = int(asset_col == expected_asset_col)

            missing = [feature for feature in self.features if feature not in features_df]
            if missing:
                raise FeatureEngineeringError(
                    f"Model features missing from live schema: {', '.join(missing)}"
                )

            sequence_df = (
                features_df[self.features]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .tail(self.seq_length)
            )
            if len(sequence_df) != self.seq_length:
                return StrategyResult(
                    0,
                    "neutral",
                    0.0,
                    [],
                    ["Insufficient complete feature rows after indicator warm-up"],
                    False,
                )

            seq_array = sequence_df.to_numpy(dtype=np.float32, copy=True)
            scale_part = seq_array[:, :self.scale_idx].reshape(-1, self.scale_idx)
            seq_array[:, :self.scale_idx] = self.scaler.transform(scale_part)
            if not np.isfinite(seq_array).all():
                raise FeatureEngineeringError("Non-finite values remain after scaling")

            input_meta = self.ort_session.get_inputs()[0]
            raw_output = self.ort_session.run(
                None,
                {input_meta.name: seq_array.reshape(1, self.seq_length, len(self.features))},
            )[0]
            raw_score = float(np.asarray(raw_output).reshape(-1)[0])
            if not np.isfinite(raw_score):
                raise ValueError("ONNX returned a non-finite score")
            prob_call = (
                raw_score
                if self.output_type == "probability"
                else float(1.0 / (1.0 + np.exp(-np.clip(raw_score, -60, 60))))
            )
            if not 0.0 <= prob_call <= 1.0:
                raise ValueError("ONNX probability is outside [0, 1]")
            prob_put = 1.0 - prob_call

            print(
                f"   🧠 [{symbol}] LSTM -> CALL: {prob_call * 100:.1f}% | "
                f"PUT: {prob_put * 100:.1f}% (Req: {self.threshold * 100:.1f}%)"
            )
            if prob_call >= self.threshold:
                return StrategyResult(
                    prob_call * 100,
                    "call",
                    prob_call,
                    [f"LSTM predicts UP with {prob_call * 100:.1f}% confidence"],
                    [],
                    True,
                    confluence=1,
                    calibrated_win_probability=(
                        prob_call if self.calibration_id else None
                    ),
                    calibration_id=self.calibration_id,
                )
            if prob_put >= self.threshold:
                return StrategyResult(
                    -(prob_put * 100),
                    "put",
                    prob_put,
                    [f"LSTM predicts DOWN with {prob_put * 100:.1f}% confidence"],
                    [],
                    True,
                    confluence=1,
                    calibrated_win_probability=(
                        prob_put if self.calibration_id else None
                    ),
                    calibration_id=self.calibration_id,
                )
            return StrategyResult(
                0,
                "neutral",
                max(prob_call, prob_put),
                [],
                ["LSTM confidence below live threshold"],
                False,
            )
        except (FeatureEngineeringError, ValueError, KeyError, TypeError) as exc:
            logger.error("LSTM inference rejected: %s", exc)
            return StrategyResult(0, "neutral", 0.0, [], [str(exc)], False)
        except Exception as exc:
            logger.exception("LSTM inference failed")
            return StrategyResult(0, "neutral", 0.0, [], [f"Inference error: {exc}"], False)
