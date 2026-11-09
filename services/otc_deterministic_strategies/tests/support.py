from dataclasses import replace
from ..contracts import Candle, Offer, Quote

ASSET = 'EURUSD-OTC'
DECISION_MS = 29 * 120000
DECISION_NS = DECISION_MS * 1000000


def candles(closes=None):
    closes = closes or [100.0 + index for index in range(29)]
    result = []
    for index, close in enumerate(closes):
        start = index * 120000
        result.append(Candle(ASSET, start, 120000, (start + 120000) * 1000000,
                             start + 120000, close - 0.6, close + 0.1,
                             close - 0.7, close, True))
    return result


def inputs():
    offer = Offer(ASSET, 'turbo-option', DECISION_NS, DECISION_MS, 0.85,
                  DECISION_MS + 120000, DECISION_MS + 90000, True, 'supported')
    quote = Quote(ASSET, DECISION_NS, DECISION_MS, 128.0)
    return offer, quote, candles()
