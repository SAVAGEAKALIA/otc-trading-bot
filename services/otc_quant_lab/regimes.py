"""Unsupervised regime discovery and state-table direction models.

Every model here learns P(up | discrete state) on the train window with a Beta(50, 50) prior and
returns that posterior mean as p_up. States come from:
- colour patterns (Markov order 3 and 5: the candle-sequence / MHI family of ideas),
- K-means and Gaussian-mixture clusters of regime features,
- a 3-state Gaussian HMM decoded with a FORWARD-ONLY filter (forward-backward smoothing and
  Viterbi both use future bars and would leak).
"""
from __future__ import annotations

import numpy as np

from .features import FEATURES
from .models import SEED

REGIME_COLUMNS = ["volr", "eff20", "ret20", "zsma20", "rng0", "ret5", "posr20", "z0"]
PRIOR = 50.0


class StateTable:
    """p_up = (ups + PRIOR) / (n + 2 PRIOR) per state; unseen states get 0.5."""

    def __init__(self, state_fn):
        self.state_fn = state_fn

    def fit(self, x, y):
        self.fit_states(x)
        s = self.state_fn(self, x)
        ok = s >= 0
        n = np.bincount(s[ok], minlength=self.n_states)
        k = np.bincount(s[ok], weights=y[ok], minlength=self.n_states)
        self.table = (k + PRIOR) / (n + 2 * PRIOR)
        self.counts = n
        return self

    def fit_states(self, x):
        pass

    def predict(self, x):
        s = self.state_fn(self, x)
        return np.where(s >= 0, self.table[np.clip(s, 0, None)], 0.5)


def _col(x, name):
    return x[:, FEATURES.index(name)]


class Pattern(StateTable):
    def __init__(self, column: str, n_states: int):
        self.column, self.n_states = column, n_states
        super().__init__(lambda self, x: np.nan_to_num(_col(x, self.column), nan=-1).astype(int))


class Clusters(StateTable):
    def __init__(self, kind: str, k: int):
        self.kind, self.n_states = kind, k
        super().__init__(Clusters._assign)

    def _matrix(self, x):
        m = np.stack([_col(x, c) for c in REGIME_COLUMNS], axis=1).astype(np.float64)
        return np.clip(np.nan_to_num(m, nan=0.0), -10, 10)

    def fit_states(self, x):
        m = self._matrix(x)[-200_000:]
        self.mu, self.sd = m.mean(0), m.std(0) + 1e-9
        z = (m - self.mu) / self.sd
        if self.kind == "kmeans":
            from sklearn.cluster import MiniBatchKMeans

            self.model = MiniBatchKMeans(self.n_states, random_state=SEED, n_init=3, batch_size=4096).fit(z)
        else:
            from sklearn.mixture import GaussianMixture

            self.model = GaussianMixture(self.n_states, covariance_type="full", random_state=SEED,
                                         max_iter=200).fit(z)

    @staticmethod
    def _assign(self, x):
        return self.model.predict((self._matrix(x) - self.mu) / self.sd).astype(int)


def forward_filter(obs: np.ndarray, start: np.ndarray, trans: np.ndarray, means: np.ndarray,
                   variances: np.ndarray, reset: np.ndarray) -> np.ndarray:
    """Filtered state probabilities P(s_t | obs_<=t) for a diagonal Gaussian HMM.

    reset[t] True restarts the filter (new contiguous run or new asset).
    """
    n, k = len(obs), len(start)
    out = np.empty((n, k))
    inv = 1.0 / variances
    norm = -0.5 * np.log(2 * np.pi * variances).sum(axis=1)
    loglik = norm[None, :] - 0.5 * (((obs[:, None, :] - means[None]) ** 2) * inv[None]).sum(axis=2)
    lik = np.exp(loglik - loglik.max(axis=1, keepdims=True))
    alpha = start.copy()
    for t in range(n):
        prior = start if reset[t] else alpha @ trans
        a = prior * lik[t]
        alpha = a / a.sum()
        out[t] = alpha
    return out


def hmm_states(z0: np.ndarray, rng0: np.ndarray, reset: np.ndarray, fit_mask: np.ndarray,
               states: int = 3, seed: int = SEED) -> np.ndarray:
    """Fit a Gaussian HMM (via a GMM initialisation + Baum-Welch on fit_mask rows) and decode causally."""
    from sklearn.mixture import GaussianMixture

    obs = np.stack([np.clip(np.nan_to_num(z0), -8, 8), np.clip(np.nan_to_num(rng0), 0, 15)], axis=1)
    sample = obs[fit_mask][-200_000:]
    gmm = GaussianMixture(states, covariance_type="diag", random_state=seed).fit(sample)
    means, variances = gmm.means_, gmm.covariances_ + 1e-6
    start = np.full(states, 1.0 / states)
    trans = np.full((states, states), 0.1 / (states - 1)) + np.eye(states) * (0.9 - 0.1 / (states - 1))
    fit_obs, fit_reset = obs[fit_mask][-200_000:], reset[fit_mask][-200_000:]
    for _ in range(8):  # Baum-Welch transition update using filtered x next-likelihood (approximate EM)
        f = forward_filter(fit_obs, start, trans, means, variances, fit_reset)
        counts = (f[:-1, :, None] * f[1:, None, :])[~fit_reset[1:]].sum(axis=0) + 1.0
        trans = counts / counts.sum(axis=1, keepdims=True)
        w = f / f.sum(axis=0, keepdims=True)
        means = w.T @ fit_obs
        variances = np.stack([(w[:, j:j + 1] * (fit_obs - means[j]) ** 2).sum(0) for j in range(states)]) + 1e-6
    filtered = forward_filter(obs, start, trans, means, variances, reset)
    return filtered.argmax(axis=1)


def regime_zoo() -> dict:
    return {
        "markov_pat3": lambda: Pattern("pat3", 27),
        "markov_pat5": lambda: Pattern("pat5", 243),
        "regime_kmeans16": lambda: Clusters("kmeans", 16),
        "regime_gmm8": lambda: Clusters("gmm", 8),
    }
