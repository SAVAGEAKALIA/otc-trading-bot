import os
import sys
import sqlite3
import logging
import argparse
import pickle
import json
import pandas as pd
import numpy as np

# Ensure we can import from trading_platform.legacy.iqoption_bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading_platform.legacy.iqoption_bot.ml.feature_engineering import FeatureEngineer

try:
    import optuna
    from xgboost import XGBClassifier
    from sklearn.metrics import log_loss, accuracy_score
except ImportError:
    print("Missing required ML libraries. Please run: pip install optuna xgboost scikit-learn")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('OptunaTuner')

def load_and_prep_data(db_path="data/ml/historical_candles.sqlite"):
    if not os.path.exists(db_path):
        logger.error(f"Database not found at {db_path}. Run harvest_data.py first.")
        sys.exit(1)
        
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM candles ORDER BY timestamp ASC", conn)
    conn.close()
    
    logger.info("Applying Feature Engineering...")
    engineer = FeatureEngineer()
    processed_dfs = []
    
    if 'asset' in df.columns and 'timeframe' in df.columns:
        for name, group_df in df.groupby(['asset', 'timeframe']):
            processed_dfs.append(engineer.generate_features(group_df.copy()))
        df = pd.concat(processed_dfs, ignore_index=True)
    else:
        df = engineer.generate_features(df)
        
    drop_cols = ['timestamp']
    for col in ['asset', 'timeframe', 'next_close']:
        if col in df.columns:
            drop_cols.append(col)
            
    ml_df = df.drop(columns=drop_cols, errors='ignore')
    
    X = ml_df.drop(columns=['target'])
    y = ml_df['target']
    
    # Chronological split to prevent lookahead bias
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    logger.info(f"Prepared Data: Train={len(X_train)}, Test={len(X_test)}")
    return X_train, y_train, X_test, y_test

def objective(trial, X_train, y_train, X_test, y_test):
    params = {
        'n_estimators': trial.suggest_int('n_estimators', 100, 400, step=100),
        'learning_rate': trial.suggest_float('learning_rate', 0.005, 0.1, log=True),
        'max_depth': trial.suggest_int('max_depth', 2, 5),
        'subsample': trial.suggest_float('subsample', 0.3, 0.9),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.3, 0.9),
        'gamma': trial.suggest_float('gamma', 0.0, 5.0),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 7),
        'random_state': 42,
        'eval_metric': 'logloss',
        'n_jobs': -1
    }
    
    model = XGBClassifier(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False
    )
    
    y_prob = model.predict_proba(X_test)[:, 1]
    
    # We use LogLoss for Optuna because it provides a smooth, continuous gradient 
    # to evaluate how well-calibrated the model's confidence scores are.
    return log_loss(y_test, y_prob)

def main():
    parser = argparse.ArgumentParser(description="Tune XGBoost Hyperparameters using Optuna")
    parser.add_argument('--trials', type=int, default=50, help='Number of optuna trials to run')
    args = parser.parse_args()
    
    X_train, y_train, X_test, y_test = load_and_prep_data()
    
    logger.info(f"Starting Optuna hyperparameter tuning for {args.trials} trials...")
    # Minimizing LogLoss directly optimizes the exact confidence probabilities we rely on!
    study = optuna.create_study(direction="minimize")
    study.optimize(lambda trial: objective(trial, X_train, y_train, X_test, y_test), n_trials=args.trials)
    
    logger.info("🎉 Best hyperparameters found:")
    for key, value in study.best_params.items():
        logger.info(f"  {key}: {value}")
        
    logger.info("Saving best parameters to data/ml/models/best_params.json")
    os.makedirs('data/ml/models', exist_ok=True)
    with open('data/ml/models/best_params.json', 'w') as f:
        json.dump(study.best_params, f, indent=4)
        
    logger.info("Tuning complete! You can now manually plug these into train_xgboost.py or modify it to read this JSON.")

if __name__ == "__main__":
    main()
