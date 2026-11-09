"""Pure causal replicas of two frozen legacy OTC decision rules."""

from .contracts import Candle, Offer, Quote, Signal
from .policy import decide

__all__ = ['Candle', 'Offer', 'Quote', 'Signal', 'decide']
