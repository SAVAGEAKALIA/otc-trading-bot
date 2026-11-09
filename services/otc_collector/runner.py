"""Disabled-by-default read-only transport with frozen schedule and bounded network operations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import ssl
import threading
import time
from .adapter import SNAPSHOT, allowed_outgoing, subscriptions
from .collector import Collector, CollectorHalted
from .export import freeze
from .monitor import emit
from .protocol import LIMITS, canonical, make_registration, read_registration, utc_ms, write_registration
from .store import Store, StorageFault

AUTH_URL = "https://auth.iqoption.com/api/v2/login"
WS_URL = "wss://iqoption.com/echo/websocket"


class TransportFault(RuntimeError):
    pass


def credentials(path):
    """Read only named keys from a private external file, without modifying process env."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("credentials require an external absolute env file")
    path = candidate.resolve()
    if path.is_relative_to(Path(__file__).resolve().parent):
        raise ValueError("credentials require an external absolute env file")
    if path.stat().st_mode & 0o077:
        raise ValueError("credential file permissions must be 0600")
    if path.stat().st_size > 65_536:
        raise ValueError("credential file too large")
    data = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip() in {"IQ_EMAIL", "IQ_PASSWORD"}:
            key = key.strip()
            if key in data:
                raise ValueError("duplicate credential field")
            data[key] = value.strip().strip("\"'")
    if set(data) != {"IQ_EMAIL", "IQ_PASSWORD"} or not all(data.values()):
        raise ValueError("external env must define IQ_EMAIL and IQ_PASSWORD")
    return data["IQ_EMAIL"], data["IQ_PASSWORD"]


def authenticate(env_path, *, session_factory=None):
    import requests
    email, password = credentials(env_path)
    session = (session_factory or requests.Session)()
    session.trust_env = False
    session.verify = True
    try:
        response = session.post(AUTH_URL, data={"identifier": email, "password": password},
                                timeout=LIMITS["http_timeout_s"], verify=True, allow_redirects=False)
        if response.status_code != 200:
            raise TransportFault("authentication_failed")
        ssid = response.cookies.get("ssid")
        if not isinstance(ssid, str) or not ssid or len(ssid) > 4096:
            raise TransportFault("authentication_failed")
        return ssid
    except TransportFault:
        raise
    except Exception as exc:
        # requests errors may include request headers, bodies, or remote personal data.
        raise TransportFault("authentication_transport_failed") from None
    finally:
        session.close()
        del email, password


def send_read(ws, operation):
    if not allowed_outgoing(operation):
        raise TransportFault("outgoing_operation_rejected")
    ws.send(canonical(operation))


class LiveRunner:
    def __init__(self, collector, env_path, progress_log):
        self.collector, self.env_path, self.progress_log = collector, env_path, progress_log
        self.ws = None
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.last_snapshot_ms = None
        self.snapshot_pending_ms = None
        self.last_frame_ms = None
        self.previous_tick = None
        self.result = 0

    def request_stop(self, *_):
        self.stop.set()
        if self.ws is not None:
            self.ws.close()

    def on_open(self, ws):
        ws.sock.settimeout(LIMITS["socket_timeout_s"])
        send_read(ws, {"name": "ssid", "msg": self.ssid})

    def on_message(self, ws, raw):
        try:
            self.collector.on_message(ws, raw)
        except CollectorHalted:
            self.stop.set()
            return
        self.last_frame_ms = utc_ms()
        # Personal/auth frames are used only in memory to acknowledge connection.
        # The collector discards their body, name, digest, and raw payload.
        try:
            frame = json.loads(raw)
            if not isinstance(frame, dict):
                return
            if frame.get("name") == "profile" and isinstance(frame.get("msg"), dict) and not self.ready.is_set():
                for operation in subscriptions():
                    send_read(ws, operation)
                self.ready.set()
                self.request_snapshot()
            elif frame.get("name") == "api_option_init_all_result":
                self.snapshot_pending_ms = None
        except Exception:
            # No raw input or transport exception is printed.
            return

    def request_snapshot(self):
        now = utc_ms()
        if self.snapshot_pending_ms is None and (self.last_snapshot_ms is None or now - self.last_snapshot_ms >= LIMITS["snapshot_interval_ms"]):
            send_read(self.ws, SNAPSHOT)
            self.last_snapshot_ms, self.snapshot_pending_ms = now, now

    def on_error(self, *_):
        try:
            self.collector.store.health("websocket_transport_error", utc_ms(), self.collector.session_id)
        except StorageFault:
            self.collector.fatal("storage_write_failure")
            self.stop.set()

    def tick(self):
        now, mono = utc_ms(), time.monotonic_ns()
        if self.previous_tick is not None:
            previous, previous_mono = self.previous_tick
            delta = now - previous - (mono - previous_mono) // 1_000_000
            if abs(delta) > LIMITS["clock_jump_ms"]:
                self.collector.fatal("receiver_clock_jump")
                self.stop.set()
                self.result = 2
        self.previous_tick = now, mono
        if now >= self.collector.store.registration["end_ms"]:
            self.request_stop()
        if self.snapshot_pending_ms is not None and now - self.snapshot_pending_ms > LIMITS["snapshot_timeout_ms"]:
            self.collector.store.health("snapshot_response_timeout", now, self.collector.session_id)
            self.snapshot_pending_ms = None
        if self.ready.is_set() and self.ws is not None:
            self.request_snapshot()
        return now

    def run(self):
        import websocket
        websocket.enableTrace(False)
        websocket.setdefaulttimeout(LIMITS["socket_timeout_s"])
        for attempt in range(LIMITS["max_reconnects"] + 1):
            if self.stop.is_set() or self.collector.stop.is_set():
                break
            now = self.tick()
            if now >= self.collector.store.registration["end_ms"]:
                break
            self.ssid = authenticate(self.env_path)
            self.ready.clear()
            self.last_snapshot_ms, self.snapshot_pending_ms = None, None
            self.ws = websocket.WebSocketApp(WS_URL, on_open=self.on_open, on_message=self.on_message,
                                            on_error=self.on_error, on_close=lambda *_: None)
            worker = threading.Thread(target=lambda: self.ws.run_forever(
                sslopt={"cert_reqs": ssl.CERT_REQUIRED, "check_hostname": True},
                ping_interval=20, ping_timeout=10), name="otc-quote-network", daemon=False)
            worker.start()
            opened = time.monotonic()
            last_monitor = opened - LIMITS["monitor_interval_s"]
            while worker.is_alive() and not self.stop.is_set() and not self.collector.stop.is_set():
                self.tick()
                if not self.ready.is_set() and time.monotonic() - opened > 15:
                    self.collector.store.health("authentication_ack_timeout", utc_ms(), self.collector.session_id)
                    self.ws.close()
                    break
                if time.monotonic() - last_monitor >= LIMITS["monitor_interval_s"]:
                    emit(self.collector.store.path, self.progress_log)
                    last_monitor = time.monotonic()
                self.stop.wait(0.25)
            self.ws.close()
            worker.join(timeout=10)
            del self.ssid
            if worker.is_alive():
                self.collector.fatal("network_close_timeout")
                self.result = 2
                break
            if self.stop.is_set() or self.collector.stop.is_set():
                break
            if attempt == LIMITS["max_reconnects"]:
                self.collector.fatal("reconnect_budget_exhausted")
                self.result = 2
                break
            self.collector.reconnect()
            backoff = min(2 ** attempt, LIMITS["max_backoff_s"])
            self.collector.store.health("reconnect_backoff", utc_ms(), self.collector.session_id, seconds=backoff)
            deadline = time.monotonic() + backoff
            while time.monotonic() < deadline and not self.stop.is_set():
                self.tick()
                self.stop.wait(0.25)
        if self.collector.halt_code:
            self.result = 2
        return self.result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register")
    register.add_argument("--start-utc", required=True)
    register.add_argument("--registration", required=True)
    register.add_argument("--research-source-root", required=True)
    check = sub.add_parser("dry-run")
    check.add_argument("--registration", required=True)
    live = sub.add_parser("live")
    live.add_argument("--registration", required=True)
    live.add_argument("--db", required=True)
    live.add_argument("--env-file", required=True)
    live.add_argument("--progress-log", required=True)
    live.add_argument("--allow-account-read", action="store_true")
    export = sub.add_parser("export")
    export.add_argument("--db", required=True)
    export.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "register":
        record = make_registration(args.start_utc, research_source_root=args.research_source_root)
        write_registration(args.registration, record)
        print(canonical({"registration": str(Path(args.registration).resolve()), "sha256": record["registration_sha256"],
                         "start_utc": record["start_utc"], "end_utc": record["end_utc"]}))
        return 0
    if args.command == "dry-run":
        record = read_registration(args.registration)
        print(canonical({"registration_sha256": record["registration_sha256"], "network_enabled": False,
                         "subscription_count": len(subscriptions()), "registration_policy": record["registration_policy"]}))
        return 0
    if args.command == "export":
        print(canonical(freeze(args.db, args.output)))
        return 0
    if not args.allow_account_read:
        parser.error("live requires --allow-account-read; authentication reads an account")
    record = read_registration(args.registration)
    if utc_ms() >= record["end_ms"]:
        raise ValueError("registered collection window has ended")
    # Lock registration in the fresh DB before credentials or network access.
    store = Store(args.db, record)
    wait_stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: wait_stop.set())
    signal.signal(signal.SIGTERM, lambda *_: wait_stop.set())
    print(f"tail -f {Path(args.progress_log).resolve()}", flush=True)
    try:
        while utc_ms() < record["start_ms"] and not wait_stop.is_set():
            wait_stop.wait(max(0, min(0.25, (record["start_ms"] - utc_ms()) / 1000)))
        if wait_stop.is_set():
            return 0
        collector = Collector(store, asynchronous=True)
        runner = LiveRunner(collector, args.env_file, args.progress_log)
        signal.signal(signal.SIGINT, runner.request_stop)
        signal.signal(signal.SIGTERM, runner.request_stop)
        try:
            return runner.run()
        except (TransportFault, StorageFault):
            collector.fatal("transport_or_storage_halted")
            print(canonical({"code": "transport_or_storage_halted"}), flush=True)
            return 2
        finally:
            runner.request_stop()
            collector.close()
            emit(args.db, args.progress_log)
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
