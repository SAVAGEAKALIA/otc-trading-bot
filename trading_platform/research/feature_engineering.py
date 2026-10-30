import numpy as np
import pandas as pd
import logging
try:
    import pandas_ta as ta
except ImportError:
    ta = None

logger = logging.getLogger(__name__)


class FeatureEngineeringError(ValueError):
    """Raised when live candles cannot reproduce the trained feature schema."""


class FeatureEngineer:
    REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")

    @staticmethod
    def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize IQ Option and historical OHLCV column names safely."""
        if df.empty:
            return df.copy()

        normalized = df.copy()
        aliases = {
            "timestamp": ("from", "at", "time"),
            "high": ("max", "h"),
            "low": ("min", "l"),
            "open": ("o",),
            "close": ("c",),
            "volume": ("v",),
        }
        for target, sources in aliases.items():
            if target not in normalized.columns:
                source = next((item for item in sources if item in normalized.columns), None)
                if source:
                    normalized = normalized.rename(columns={source: target})

        missing = [column for column in FeatureEngineer.REQUIRED_COLUMNS if column not in normalized.columns]
        if missing:
            raise FeatureEngineeringError(
                f"Missing OHLCV columns required for ML inference: {', '.join(missing)}"
            )

        for column in ("open", "high", "low", "close"):
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        if normalized[list(("open", "high", "low", "close"))].isna().any().any():
            raise FeatureEngineeringError("OHLCV contains non-numeric values")

        timestamp = normalized["timestamp"]
        if pd.api.types.is_numeric_dtype(timestamp):
            max_timestamp = float(timestamp.abs().max())
            unit = "ns" if max_timestamp >= 1e17 else "us" if max_timestamp >= 1e14 else "ms" if max_timestamp >= 1e11 else "s"
            normalized["timestamp"] = pd.to_datetime(timestamp, unit=unit, utc=True)
        else:
            normalized["timestamp"] = pd.to_datetime(timestamp, utc=True, errors="coerce")
        if normalized["timestamp"].isna().any():
            raise FeatureEngineeringError("OHLCV contains invalid timestamps")

        invalid_range = (
            (normalized["high"] < normalized[["open", "close", "low"]].max(axis=1))
            | (normalized["low"] > normalized[["open", "close", "high"]].min(axis=1))
        )
        if invalid_range.any():
            raise FeatureEngineeringError("OHLCV contains invalid high/low ranges")

        return normalized.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)

    def generate_features(self, df: pd.DataFrame, is_training: bool = True) -> pd.DataFrame:
        """
        Takes a raw OHLCV DataFrame and generates a robust feature matrix.
        Expects columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        if ta is None:
            raise FeatureEngineeringError(
                "pandas_ta is required to reproduce the model feature schema"
            )
        if df.empty:
            return df.copy()

        df = self.normalize_ohlcv(df)
        
        # --- 1. Base Returns (Stationarity) ---
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[f'{col}_pct'] = df[col].pct_change()
                
        # Drop volume entirely as OTC markets rarely have accurate volume
        if 'volume' in df.columns:
            df = df.drop(columns=['volume'])
        
        # --- 2. Trend & Distance ---
        # Use pandas-ta rather than pandas' raw EWM implementation.  The LSTM
        # was trained with ta.ema(), whose warm-up/initialisation behaviour is
        # not guaranteed to be identical to Series.ewm().  Inference must
        # reproduce the training feature definition exactly.
        ema_20 = ta.ema(df['close'], length=20)
        ema_50 = ta.ema(df['close'], length=50)
        if ema_20 is None or ema_50 is None:
            raise FeatureEngineeringError(
                "pandas-ta could not calculate EMA features from the supplied candles"
            )
        df['ema_20'] = ema_20
        df['ema_50'] = ema_50
        df['dist_ema_20'] = (df['close'] - df['ema_20']) / df['ema_20']
        df['dist_ema_50'] = (df['close'] - df['ema_50']) / df['ema_50']
        
        # --- 3. Momentum & Oscillators ---
        
        # RSI 14 (Normalized 0-1)
        df['rsi_14'] = ta.rsi(df['close'], length=14) / 100.0
        
        # ROC 10 retained as a stationary momentum feature for current models.
        df['roc_10'] = df['close'].pct_change(periods=10) * 100
        
        # MACD Histogram
        macd_df = ta.macd(df['close'], fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            df['macd_hist'] = macd_df.iloc[:, 1]
        else:
            df['macd_hist'] = 0.0
            
        # Stochastic Oscillator %K (Normalized 0-1)
        stoch_df = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3)
        if stoch_df is not None and not stoch_df.empty:
            df['stoch_k'] = stoch_df.iloc[:, 0] / 100.0
        else:
            df['stoch_k'] = 0.5
            
        # Bollinger Bands %B
        bbands_df = ta.bbands(df['close'], length=20, std=2)
        if bbands_df is not None and not bbands_df.empty:
            df['bb_percent_b'] = bbands_df.iloc[:, 4]
        else:
            df['bb_percent_b'] = 0.5
        
        # --- 4. Volatility ---
        # Match the pandas-ta ATR used during LSTM training exactly.
        df['atr_14'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['atr_pct'] = df['atr_14'] / df['close']
        
        # --- 5. Candle Anatomy (Micro-Structure) ---
        df['candle_range'] = df['high'] - df['low'] + 1e-8
        df['body_size'] = abs(df['close'] - df['open'])
        df['body_ratio'] = df['body_size'] / df['candle_range']
        
        df['upper_wick'] = np.where(df['close'] >= df['open'], df['high'] - df['close'], df['high'] - df['open'])
        df['lower_wick'] = np.where(df['close'] >= df['open'], df['open'] - df['low'], df['close'] - df['low'])
        
        df['upper_wick_ratio'] = df['upper_wick'] / df['candle_range']
        df['lower_wick_ratio'] = df['lower_wick'] / df['candle_range']
        df['close_position'] = (df['close'] - df['low']) / df['candle_range']
        
        # --- 6. The Target Label (Only if training) ---
        if is_training:
            # Debug NaNs
            nan_counts = df.isnull().sum()
            nan_cols = nan_counts[nan_counts > 0]
            if not nan_cols.empty and len(df) > 0:
                logger.info(f"NaNs before drop: {nan_cols.to_dict()}")
        
        # --- 7. Time Context ---
        df['hour_of_day'] = df['timestamp'].dt.hour / 24.0
        df['day_of_week'] = df['timestamp'].dt.dayofweek / 7.0

        # --- 7.5. Telemetry Fallbacks (if missing during legacy inference) ---
        if 'spread' not in df.columns:
            df['spread'] = 0.0
        if 'deal_count' not in df.columns:
            df['deal_count'] = 0
        if 'call_ratio' not in df.columns:
            df['call_ratio'] = 0.5
        if 'traders_mood' not in df.columns:
            df['traders_mood'] = 0.5

        # --- 8. Stationary v4 LSTM Features ---
        # Keep the legacy columns above for existing model artifacts. New v4
        # metadata selects only this schema, so adding these columns is
        # backward-compatible with already deployed v3 models.
        close = df['close'].replace(0.0, np.nan)
        open_price = df['open'].replace(0.0, np.nan)
        log_close = np.log(close)
        for horizon in (1, 2, 3, 5, 10):
            df[f'log_return_{horizon}'] = log_close.diff(horizon)

        previous_close = close.shift(1)
        df['open_gap_log'] = np.log(open_price / previous_close)
        df['high_from_open_log'] = np.log(df['high'] / open_price)
        df['low_from_open_log'] = np.log(df['low'] / open_price)
        df['close_from_open_log'] = np.log(close / open_price)
        df['range_pct'] = (df['high'] - df['low']) / close

        df['dist_ema_50'] = (df['close'] - df['ema_50']) / df['ema_50']
        df['ema_20_slope_3'] = np.log(df['ema_20'] / df['ema_20'].shift(3))
        df['ema_50_slope_3'] = np.log(df['ema_50'] / df['ema_50'].shift(3))
        df['atr_ratio_30'] = df['atr_pct'] / df['atr_pct'].rolling(
            30, min_periods=30
        ).median()
        df['macd_hist_atr'] = df['macd_hist'] / df['atr_14'].replace(0.0, np.nan)
        df['rsi_centered'] = (df['rsi_14'] * 100.0 - 50.0) / 50.0
        df['stoch_k_centered'] = (df['stoch_k'] * 100.0 - 50.0) / 50.0
        signed_body = df['close'] - df['open']
        df['signed_body_ratio'] = signed_body / df['candle_range']

        one_bar_return = df['log_return_1']
        df['realized_vol_10'] = one_bar_return.rolling(
            10, min_periods=10
        ).std(ddof=0)
        df['realized_vol_30'] = one_bar_return.rolling(
            30, min_periods=30
        ).std(ddof=0)
        rolling_mean = one_bar_return.rolling(20, min_periods=20).mean()
        rolling_std = one_bar_return.rolling(
            20, min_periods=20
        ).std(ddof=0)
        df['return_zscore_20'] = (
            one_bar_return - rolling_mean
        ) / rolling_std.replace(0.0, np.nan)

        minute_of_day = df['timestamp'].dt.hour * 60 + df['timestamp'].dt.minute
        hour_angle = 2.0 * np.pi * minute_of_day / 1440.0
        day_angle = 2.0 * np.pi * df['timestamp'].dt.dayofweek / 7.0
        df['hour_sin'] = np.sin(hour_angle)
        df['hour_cos'] = np.cos(hour_angle)
        df['day_sin'] = np.sin(day_angle)
        df['day_cos'] = np.cos(day_angle)

        if is_training:
            # Drop only after every requested schema has been calculated.
            # Doing this earlier changes rolling-window initialization and
            # makes training/live feature rows disagree.
            df = df.replace([np.inf, -np.inf], np.nan).dropna().reset_index(
                drop=True
            )

        return df

    def prepare_for_inference(self, df: pd.DataFrame, expected_features: list) -> pd.DataFrame:
        """
        Prepares real-time live data for inference by ensuring exact column matching.
        """
        df = self.generate_features(df, is_training=False)
        
        # Forward fill only. Backfilling a warm-up value would use future
        # candles and introduce look-ahead leakage into live inference.
        df = df.ffill().replace([np.inf, -np.inf], np.nan)
        
        # In live inference, we might be missing the One-Hot encoded asset columns
        # So we add them as 0 if they are missing
        for col in expected_features:
            if col not in df.columns:
                df[col] = 0
                
        # Ensure exact column order and presence
        prepared = df[expected_features]
        if prepared.empty or prepared.iloc[-1].isna().any():
            raise FeatureEngineeringError(
                "Latest candle does not have a complete ML feature row"
            )
        return prepared
