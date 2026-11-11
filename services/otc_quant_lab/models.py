"""Model zoo. Every model maps (X, y) -> p_up through the same fit/predict interface.

Training rows are capped to the most recent TRAIN_CAP rows of the train window for every model
(kNN and the kernel approximation use smaller caps for compute; documented in the report).
"""
from __future__ import annotations

import os

import numpy as np

TRAIN_CAP = 250_000
SEED = 20261109
THREADS = int(os.environ.get("LAB_THREADS", "5"))  # 8 vCPU WSL box: LightGBM 62s at 8 threads vs 32s at 4
PREDICT_CHUNK = 20_000  # bounds kNN distance-matrix memory (an unchunked kNN predict was OOM-killed)


class BaseRate:
    def fit(self, x, y):
        self.p = float(np.mean(y))
        return self

    def predict(self, x):
        return np.full(len(x), self.p)


class Sklearn:
    """Wrap an sklearn estimator; optional NaN fill + scaling for models that need it."""

    def __init__(self, make, scale: bool, cap: int = TRAIN_CAP):
        self.make, self.scale, self.cap = make, scale, cap

    def _prep(self, x, fit=False):
        x = np.nan_to_num(np.asarray(x, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        x = np.clip(x, -50, 150)
        if self.scale:
            if fit:
                self.mu, self.sd = x.mean(0), x.std(0) + 1e-6
            x = np.clip((x - self.mu) / self.sd, -8, 8)
        return x

    def fit(self, x, y):
        x, y = x[-self.cap:], y[-self.cap:]
        self.model = self.make().fit(self._prep(x, fit=True), y)
        return self

    def predict(self, x):
        x = self._prep(x)
        return np.concatenate([self.model.predict_proba(x[i:i + PREDICT_CHUNK])[:, 1]
                               for i in range(0, len(x), PREDICT_CHUNK)])


class Native:
    """Gradient boosting libraries that handle NaN themselves."""

    def __init__(self, kind: str, cap: int = TRAIN_CAP):
        self.kind, self.cap = kind, cap

    def fit(self, x, y):
        x, y = np.asarray(x[-self.cap:], dtype=np.float32), y[-self.cap:]
        if self.kind == "lightgbm":
            import lightgbm as lgb

            self.model = lgb.LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=31,
                                            min_child_samples=500, subsample=0.8, subsample_freq=1,
                                            colsample_bytree=0.8, reg_lambda=5.0, random_state=SEED,
                                            verbose=-1, n_jobs=THREADS)
        elif self.kind == "xgboost":
            import xgboost as xgb

            self.model = xgb.XGBClassifier(n_estimators=400, learning_rate=0.05, max_depth=5,
                                           subsample=0.8, colsample_bytree=0.8, min_child_weight=50,
                                           reg_lambda=5.0, tree_method="hist", random_state=SEED, n_jobs=THREADS)
        elif self.kind == "catboost":
            from catboost import CatBoostClassifier

            self.model = CatBoostClassifier(iterations=300, depth=6, learning_rate=0.05, l2_leaf_reg=5,
                                            random_seed=SEED, verbose=False, thread_count=THREADS)
        elif self.kind == "hist_gb":
            from sklearn.ensemble import HistGradientBoostingClassifier

            self.model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                                        min_samples_leaf=500, l2_regularization=5.0,
                                                        early_stopping=False, random_state=SEED)
        self.model.fit(x, y)
        return self

    def predict(self, x):
        return self.model.predict_proba(np.asarray(x, dtype=np.float32))[:, 1]


def tabular_zoo() -> dict:
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
    from sklearn.kernel_approximation import Nystroem
    from sklearn.linear_model import LogisticRegression, SGDClassifier
    from sklearn.naive_bayes import GaussianNB
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import make_pipeline

    return {
        "base_rate": lambda: BaseRate(),
        "logistic": lambda: Sklearn(lambda: LogisticRegression(C=0.1, max_iter=500), scale=True),
        "naive_bayes": lambda: Sklearn(GaussianNB, scale=True),
        "knn": lambda: Sklearn(lambda: KNeighborsClassifier(n_neighbors=200, n_jobs=THREADS), scale=True, cap=50_000),
        "svm_rbf": lambda: Sklearn(lambda: make_pipeline(
            Nystroem(n_components=300, random_state=SEED),
            SGDClassifier(loss="log_loss", alpha=1e-4, max_iter=20, random_state=SEED)), scale=True, cap=150_000),
        "random_forest": lambda: Sklearn(lambda: RandomForestClassifier(
            n_estimators=100, max_depth=10, min_samples_leaf=200, max_features="sqrt", n_jobs=THREADS,
            random_state=SEED), scale=False),
        "extra_trees": lambda: Sklearn(lambda: ExtraTreesClassifier(
            n_estimators=100, max_depth=10, min_samples_leaf=200, max_features="sqrt", n_jobs=THREADS,
            random_state=SEED), scale=False),
        "hist_gb": lambda: Native("hist_gb"),
        "lightgbm": lambda: Native("lightgbm"),
        "xgboost": lambda: Native("xgboost"),
        "catboost": lambda: Native("catboost"),
        "mlp": lambda: Sklearn(lambda: MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, batch_size=1024,
                                                     learning_rate_init=1e-3, max_iter=15, early_stopping=True,
                                                     n_iter_no_change=3, random_state=SEED), scale=True),
    }
