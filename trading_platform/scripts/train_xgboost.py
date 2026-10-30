import os
import sys
import sqlite3
import logging
import argparse
import pickle
import pandas as pd
import numpy as np

# Ensure we can import from trading_platform.legacy.iqoption_bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_platform.legacy.iqoption_bot.ml.feature_engineering import FeatureEngineer

try:
    from xgboost import XGBClassifier
    from sklearn.metrics import accuracy_score, precision_score, classification_report, roc_auc_score, f1_score
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.calibration import CalibratedClassifierCV
except ImportError:
    print("Missing required ML libraries. Please run: pip install xgboost scikit-learn pandas-ta")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('XGBQuantTrainer')

# Configuration from Audit
NOISE_THRESHOLD = 0.00010  
N_SPLITS = 5               
CALIBRATE_PROBAS = True    

def load_data(db_path="data/ml/historical_candles.sqlite", asset=None, timeframe=None):
    if not os.path.exists(db_path):
        logger.error(f"Database not found at {db_path}. Run harvest_data.py first.")
        return pd.DataFrame()
        
    conn = sqlite3.connect(db_path)
    
    query = "SELECT * FROM candles"
    conditions, params = [], []
    
    if asset:
        conditions.append("asset = ?")
        params.append(asset)
    if timeframe:
        conditions.append("timeframe = ?")
        params.append(timeframe)
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    query += " ORDER BY timestamp ASC"
    logger.info(f"Loading data from DB... (Asset: {asset}, Timeframe: {timeframe})")
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def train_model(df, model_save_path):
    logger.info("Applying Feature Engineering (strictly per asset to prevent leakage)...")
    engineer = FeatureEngineer()
    
    processed_dfs = []
    if 'asset' in df.columns and 'timeframe' in df.columns:
        for name, group_df in df.groupby(['asset', 'timeframe']):
            logger.info(f"Asset: {name[0]}, Raw candles: {len(group_df)}")
            group_df = group_df.sort_values('timestamp')
            group_df['future_return'] = group_df['close'].shift(-1) / group_df['close'] - 1
            feat_df = engineer.generate_features(group_df.copy())
            logger.info(f"  After Feature Gen (dropped NaNs): {len(feat_df)}")
            
            if 'future_return' in feat_df.columns:
                feat_df['target'] = np.where(feat_df['future_return'] > NOISE_THRESHOLD, 1, 
                                    np.where(feat_df['future_return'] < -NOISE_THRESHOLD, 0, np.nan))
                feat_df = feat_df.dropna(subset=['target'])
                logger.info(f"  After Target Noise Threshold: {len(feat_df)}")
                
            processed_dfs.append(feat_df)
        df = pd.concat(processed_dfs, ignore_index=True)
    else:
        df['future_return'] = df['close'].shift(-1) / df['close'] - 1
        df = engineer.generate_features(df)
        df['target'] = np.where(df['future_return'] > NOISE_THRESHOLD, 1, 
                       np.where(df['future_return'] < -NOISE_THRESHOLD, 0, np.nan))
        df = df.dropna(subset=['target'])
    
    if df.empty or len(df) < 100:
        logger.error("Not enough data to train after feature engineering and noise reduction.")
        return
        
    # Generate Asset Identity (One-Hot) if multiple assets exist
    if 'asset' in df.columns and df['asset'].nunique() > 1:
        asset_dummies = pd.get_dummies(df['asset'], prefix='asset', dtype=int)
        df = pd.concat([df, asset_dummies], axis=1)
        
    drop_cols = ['timestamp', 'asset', 'timeframe', 'next_close', 'future_return']
    ml_df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors='ignore')
    
    X = ml_df.drop(columns=['target'])
    y = ml_df['target'].values
    features = list(X.columns)
    
    logger.info(f"Dataset shape: {X.shape}. Features: {len(features)}")
    logger.info(f"Class Balance -> UP: {(y==1).sum()/len(y):.2f} | DOWN: {(y==0).sum()/len(y):.2f}")
    
    # 5-Fold Walk-Forward Validation
    tscv = TimeSeriesSplit(n_splits=N_SPLITS)
    
    xgb_params = {
        'n_estimators': 300,
        'learning_rate': 0.01,
        'max_depth': 4,
        'subsample': 0.7,
        'colsample_bytree': 0.7,
        'eval_metric': 'logloss',
        'random_state': 42
    }
    
    fold_metrics = []
    best_macro_f1 = 0
    best_model = None
    best_thresh = 0.52 # Default fallback
    
    logger.info("--- Starting 5-Fold Walk-Forward Validation ---")
    
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train_f, y_train_f = X.iloc[train_idx], y[train_idx]
        X_val_f, y_val_f = X.iloc[val_idx], y[val_idx]
        
        pos_weight = (len(y_train_f) - y_train_f.sum()) / (y_train_f.sum() + 1e-8)
        
        model = XGBClassifier(**xgb_params, scale_pos_weight=pos_weight)
        model.fit(X_train_f, y_train_f, verbose=False)
        
        if CALIBRATE_PROBAS:
            calibrated = CalibratedClassifierCV(model, method='isotonic', cv='prefit')
            calibrated.fit(X_val_f, y_val_f)
            eval_model = calibrated
        else:
            eval_model = model
            
        val_probs = eval_model.predict_proba(X_val_f)[:, 1]
        
        # Dynamic Threshold Optimization (Macro F1)
        fold_best_thresh, fold_best_f1 = 0.50, 0
        for thresh in np.linspace(0.50, 0.65, 16):
            preds = (val_probs > thresh).astype(int)
            f1 = f1_score(y_val_f, preds, average='macro', zero_division=0)
            if f1 > fold_best_f1:
                fold_best_f1 = f1
                fold_best_thresh = thresh
                
        final_preds = (val_probs > fold_best_thresh).astype(int)
        acc = accuracy_score(y_val_f, final_preds)
        
        # Handle single-class edge case in AUC
        try:
            auc = roc_auc_score(y_val_f, val_probs)
        except ValueError:
            auc = 0.5
            
        fold_metrics.append({'Accuracy': acc, 'AUC': auc, 'Macro_F1': fold_best_f1, 'Threshold': fold_best_thresh})
        logger.info(f"Fold {fold+1}/{N_SPLITS} | Acc: {acc:.4f} | AUC: {auc:.4f} | F1: {fold_best_f1:.4f} | Thresh: {fold_best_thresh:.3f}")
        
        # Keep track of the model that achieved the highest F1
        if fold_best_f1 > best_macro_f1:
            best_macro_f1 = fold_best_f1
            best_model = eval_model
            best_thresh = fold_best_thresh
            
    # Walk-Forward Summary
    df_metrics = pd.DataFrame(fold_metrics)
    logger.info("--- Walk-Forward Summary ---")
    logger.info(f"Mean Accuracy: {df_metrics['Accuracy'].mean():.4f}")
    logger.info(f"Mean Macro F1: {df_metrics['Macro_F1'].mean():.4f}")
    logger.info(f"Global Optimal Threshold Selected: {best_thresh:.3f}")
    
    # Save the mathematically optimal model and threshold
    os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
    
    model_data = {
        'model': best_model,
        'features': features,
        'accuracy': df_metrics['Accuracy'].mean(),
        'optimal_threshold': best_thresh,
        'timeframe_trained': df['timeframe'].iloc[0] if 'timeframe' in df.columns else 'mixed'
    }
    
    with open(model_save_path, 'wb') as f:
        pickle.dump(model_data, f)
        
    logger.info(f"✅ Quant Model saved to {model_save_path}")

def main():
    parser = argparse.ArgumentParser(description="Train XGBoost Model on Historical Candles")
    parser.add_argument('--asset', type=str, default=None, help='Asset to train on (default: all assets)')
    parser.add_argument('--timeframe', type=int, default=120, help='Timeframe in seconds (e.g. 120 for 2m)')
    parser.add_argument('--out', type=str, default='data/ml/models/xgb_v1.pkl', help='Output path for the .pkl model')
    args = parser.parse_args()
    
    df = load_data(asset=args.asset, timeframe=args.timeframe)
    if df.empty:
        return
        
    train_model(df, args.out)

if __name__ == "__main__":
    main()
