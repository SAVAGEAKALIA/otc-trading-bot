from pathlib import Path
import tempfile
import copy
from functools import lru_cache
from services.otc_collector.protocol import make_registration
from services.otc_collector.store import Store
from services.otc_collector.collector import Collector

START_TEXT = "2030-01-01T00:00:00Z"
START = 1_893_456_000_000
RESEARCH_ROOT = str(Path(__file__).resolve().parent / "fixtures" / "research")


class Clock:
    def __init__(self):
        self.wall, self.mono = START, 10_000_000_000
    def step(self, ms=1):
        self.wall += ms
        self.mono += ms * 1_000_000
    def utc(self):
        return self.wall
    def monotonic(self):
        return self.mono


def temporary():
    return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)


@lru_cache(maxsize=1)
def _registered():
    return make_registration(START_TEXT, now_ms=START - 60_000, research_source_root=RESEARCH_ROOT)


def registered():
    return copy.deepcopy(_registered())


@lru_cache(maxsize=1)
def _pristine_database():
    # Independent byte copies avoid repeating durable schema DDL for each test.
    # The template contains registration only, never sessions or observations.
    with temporary() as directory:
        path = Path(directory) / "template.sqlite"
        store = Store(path, registered())
        store.close()
        return path.read_bytes()


def setup(directory, **kwargs):
    clock = Clock()
    path = Path(directory) / "fresh.sqlite"
    path.write_bytes(_pristine_database())
    store = Store(path, registered())
    collector = Collector(store, wall_clock=clock.utc, monotonic_clock=clock.monotonic, **kwargs)
    return store, collector, clock


def quote(active=76, at=START, bid=1.1, ask=1.2):
    return {"name": "candles-generated", "msg": {"active_id": active, "at": at,
             "bid": bid, "ask": ask, "candles": {"1": {}, "120": {}, "300": {}}}}


def snapshot():
    return {"name": "api_option_init_all_result", "msg": {"isSuccessful": True, "result": {
        "turbo": {"actives": {str(key): {"name": "front." + identity, "enabled": True, "is_suspended": False,
                   "option": {"profit": {"commission": 18}}} for key, identity in ((76, "EURUSD-OTC"), (81, "GBPUSD-OTC"))}}}}}
