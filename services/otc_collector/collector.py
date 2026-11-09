"""Receipt-first bounded ingress; all storage failures stop the collector."""
from __future__ import annotations

import queue
import threading
import time
from .adapter import Adapter, InvalidFrame, Receipt
from .protocol import LIMITS, utc_ms
from .store import StorageFault


class CollectorHalted(RuntimeError):
    pass


class Collector:
    def __init__(self, store, *, wall_clock=utc_ms, monotonic_clock=time.monotonic_ns,
                 wall_clock_ns=None,
                 capacity=LIMITS["queue_capacity"], asynchronous=False):
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("capacity must be positive integer")
        self.store = store
        self.wall_clock, self.monotonic_clock = wall_clock, monotonic_clock
        self.wall_clock_ns = wall_clock_ns if wall_clock_ns is not None else (time.time_ns if wall_clock is utc_ms else None)
        self.queue = queue.Queue(maxsize=capacity)
        self.adapter = Adapter()
        self.stop = threading.Event()
        self.capture_lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.sequence = 0
        self.previous = None
        self.session_id = store.open_session(at_ms=wall_clock())
        self.halt_code = None
        self.asynchronous = asynchronous
        self.worker = None
        self.socket = None
        if asynchronous:
            self.worker = threading.Thread(target=self._work, name="otc-receipt-writer", daemon=False)
            self.worker.start()

    def fatal(self, code, receipt=None):
        self.halt_code = code
        self.stop.set()
        try:
            self.store.health(code, receipt.received_at_ms if receipt else self.wall_clock(), self.session_id,
                              pending_receipts=self.queue.qsize())
        except StorageFault:
            pass
        if self.socket is not None:
            self.socket.close()

    def on_message(self, ws, raw):
        # Capture both clocks before JSON parsing, hashing, filtering, or queue operations.
        received_at_ns = self.wall_clock_ns() if self.wall_clock_ns is not None else None
        received_at_ms = self.wall_clock() if received_at_ns is None else received_at_ns // 1_000_000
        monotonic_ns = self.monotonic_clock()
        self.socket = ws
        with self.capture_lock:
            if self.stop.is_set():
                raise CollectorHalted(self.halt_code or "collector_stopped")
            self.sequence += 1
            receipt = Receipt(self.session_id, self.sequence, received_at_ms, monotonic_ns, received_at_ns)
            if self.previous is not None:
                wall_delta = received_at_ms - self.previous.received_at_ms
                mono_delta = (monotonic_ns - self.previous.monotonic_ns) // 1_000_000
                if mono_delta < 0 or abs(wall_delta - mono_delta) > LIMITS["clock_jump_ms"]:
                    self.fatal("receiver_clock_jump", receipt)
                    raise CollectorHalted("receiver_clock_jump")
            self.previous = receipt
            if not self.store.registration["start_ms"] <= received_at_ms <= self.store.registration["end_ms"]:
                self.fatal("outside_registered_window", receipt)
                raise CollectorHalted("outside_registered_window")
            if not isinstance(raw, (str, bytes)) or (len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)) > LIMITS["frame_bytes"]:
                self.fatal("ingress_frame_limit", receipt)
                raise CollectorHalted("ingress_frame_limit")
            try:
                self.queue.put_nowait((receipt, raw))
            except queue.Full as exc:
                self.fatal("queue_overflow", receipt)
                raise CollectorHalted("queue_overflow") from exc
        if not self.asynchronous:
            self.drain()

    def _process(self, receipt, raw):
        try:
            envelope = self.adapter.parse(raw, receipt)
        except InvalidFrame as exc:
            envelope = self.adapter.envelope(receipt, [], {"code": "frame_quarantine", "reason": str(exc)})
        if envelope is not None:
            self.store.append(envelope)

    def drain(self):
        with self.process_lock:
            while True:
                try:
                    receipt, raw = self.queue.get_nowait()
                except queue.Empty:
                    return
                try:
                    self._process(receipt, raw)
                except StorageFault as exc:
                    self.fatal("storage_write_failure", receipt)
                    raise CollectorHalted("storage_write_failure") from exc
                finally:
                    self.queue.task_done()

    def _work(self):
        while not self.stop.is_set() or not self.queue.empty():
            try:
                with self.process_lock:
                    try:
                        receipt, raw = self.queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    try:
                        self._process(receipt, raw)
                    finally:
                        self.queue.task_done()
            except StorageFault:
                self.fatal("storage_write_failure", receipt)
                return
            except Exception:
                self.fatal("writer_internal_error", receipt)
                return

    def reconnect(self):
        """Drain old receipt identities, then expose a new session with fresh synchronization."""
        with self.capture_lock:
            if self.stop.is_set():
                raise CollectorHalted(self.halt_code or "collector_stopped")
            self.drain()
            now = self.wall_clock()
            self.store.health("disconnect", now, self.session_id)
            self.store.close_session(self.session_id, at_ms=now, code="reconnect")
            self.session_id = self.store.open_session(at_ms=now)
            self.sequence, self.previous = 0, None
            self.adapter = Adapter()

    def close(self, code="graceful_close"):
        with self.capture_lock:
            self.stop.set()
        if self.worker is not None:
            self.worker.join(timeout=5)
            if self.worker.is_alive():
                self.fatal("writer_close_timeout")
                raise CollectorHalted("writer_close_timeout")
        elif not self.store.failed:
            self.drain()
        if self.socket is not None:
            self.socket.close()
        if not self.store.failed:
            self.store.close_session(self.session_id, at_ms=self.wall_clock(), code=self.halt_code or code)
