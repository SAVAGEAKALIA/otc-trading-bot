"""Deep sequence models (PyTorch, CPU). Same fit/predict contract as models.py.

Input: last SEQ_LEN bars x SEQ_CHANNELS (normalised return, body, wicks, range) plus the tabular
feature vector. Each architecture encodes the sequence; a shared head adds the tabular features.
"""
from __future__ import annotations

import numpy as np

from .models import SEED, THREADS

SEQ_CAP = 150_000
EPOCHS = 2
BATCH = 1024


def _torch():
    import torch

    torch.set_num_threads(THREADS)
    torch.manual_seed(SEED)
    return torch


def _encoder(kind: str, channels: int, width: int = 32):
    torch = _torch()
    nn = torch.nn

    class GRU(nn.Module):
        def __init__(self):
            super().__init__()
            self.rnn = nn.GRU(channels, width, batch_first=True)

        def forward(self, s):
            return self.rnn(s)[0][:, -1]

    class TCN(nn.Module):
        def __init__(self):
            super().__init__()
            layers, c = [], channels
            for d in (1, 2, 4, 8):
                layers += [nn.Conv1d(c, width, 3, dilation=d, padding=2 * d), nn.GELU()]
                c = width
            self.net = nn.Sequential(*layers)

        def forward(self, s):
            y = self.net(s.transpose(1, 2))
            return y[:, :, : s.shape[1]][:, :, -1]  # causal: drop right padding, take last step

    class CNNLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Sequential(nn.Conv1d(channels, width, 3, padding=1), nn.GELU())
            self.rnn = nn.LSTM(width, width, batch_first=True)

        def forward(self, s):
            y = self.conv(s.transpose(1, 2)).transpose(1, 2)
            return self.rnn(y)[0][:, -1]

    class Transformer(nn.Module):
        def __init__(self):
            super().__init__()
            self.inp = nn.Linear(channels, width)
            self.pos = nn.Parameter(torch.zeros(1, 32, width))
            layer = nn.TransformerEncoderLayer(width, 4, 64, dropout=0.1, batch_first=True)
            self.enc = nn.TransformerEncoder(layer, 2)

        def forward(self, s):
            return self.enc(self.inp(s) + self.pos[:, : s.shape[1]])[:, -1]

    return {"gru": GRU, "tcn": TCN, "cnn_lstm": CNNLSTM, "transformer": Transformer}[kind]()


class SeqModel:
    def __init__(self, kind: str, cap: int = SEQ_CAP):
        self.kind, self.cap = kind, cap

    def fit(self, data, y):
        seq, tab = data
        seq, tab, y = seq[-self.cap:], tab[-self.cap:], y[-self.cap:]
        torch = _torch()
        nn = torch.nn
        tab = np.nan_to_num(tab.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        self.mu, self.sd = tab.mean(0), tab.std(0) + 1e-6
        tab = np.clip((tab - self.mu) / self.sd, -8, 8)
        encoder = _encoder(self.kind, seq.shape[2])

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = encoder
                self.tab = nn.Sequential(nn.Linear(tab.shape[1], 32), nn.GELU())
                self.head = nn.Sequential(nn.Dropout(0.1), nn.Linear(64, 1))

            def forward(self, s, x):
                return self.head(torch.cat([self.encoder(s), self.tab(x)], dim=1)).squeeze(1)

        self.net = Net()
        opt = torch.optim.AdamW(self.net.parameters(), lr=1e-3, weight_decay=1e-4)
        loss_fn = nn.BCEWithLogitsLoss()
        rng = np.random.default_rng(SEED)
        s_t, x_t = torch.from_numpy(seq), torch.from_numpy(tab)
        y_t = torch.from_numpy(y.astype(np.float32))
        self.net.train()
        for _ in range(EPOCHS):
            order = torch.from_numpy(rng.permutation(len(y)))  # shuffles minibatches inside train only
            for start in range(0, len(y), BATCH):
                idx = order[start:start + BATCH]
                opt.zero_grad()
                loss = loss_fn(self.net(s_t[idx], x_t[idx]), y_t[idx])
                loss.backward()
                opt.step()
        return self

    def predict(self, data):
        torch = _torch()
        seq, tab = data
        tab = np.clip((np.nan_to_num(tab.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0) - self.mu) / self.sd,
                      -8, 8)
        self.net.eval()
        out = []
        with torch.no_grad():
            for start in range(0, len(tab), 8192):
                s = torch.from_numpy(seq[start:start + 8192])
                x = torch.from_numpy(tab[start:start + 8192])
                out.append(torch.sigmoid(self.net(s, x)).numpy())
        return np.concatenate(out)


def seq_zoo() -> dict:
    return {f"deep_{kind}": (lambda k=kind: SeqModel(k)) for kind in ("gru", "tcn", "cnn_lstm", "transformer")}
