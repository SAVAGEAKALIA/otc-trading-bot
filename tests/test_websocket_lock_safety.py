"""Regression coverage for the bundled IQ Option websocket send guards."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# The workstation also has an editable iqoptionapi checkout outside this
# repository.  Put this repository's bundled client first, matching Docker's
# ``pip install -e /app/iqoptionapi`` behaviour.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "iqoptionapi"))

from trading_platform.vendor.iqoptionapi.iqoptionapi.api import IQOptionAPI
from trading_platform.vendor.iqoptionapi.iqoptionapi.ws.client import WebsocketClient
import trading_platform.vendor.iqoptionapi.iqoptionapi.global_value as global_value


class TestWebsocketLockSafety(unittest.TestCase):
    def setUp(self):
        global_value.ssl_Mutual_exclusion = False
        global_value.ssl_Mutual_exclusion_write = False

    def tearDown(self):
        global_value.ssl_Mutual_exclusion = False
        global_value.ssl_Mutual_exclusion_write = False

    def test_send_exception_releases_write_guard(self):
        api = object.__new__(IQOptionAPI)
        websocket = MagicMock()
        websocket.send.side_effect = RuntimeError("socket failed")
        api.websocket_client = SimpleNamespace(wss=websocket)

        with self.assertRaisesRegex(RuntimeError, "socket failed"):
            api.send_websocket_request("sendMessage", {"x": 1})

        self.assertFalse(global_value.ssl_Mutual_exclusion_write)

    def test_bad_message_releases_read_guard(self):
        client = object.__new__(WebsocketClient)
        client.api = MagicMock()

        with self.assertRaises(json.JSONDecodeError):
            client.on_message(None, "not-json")

        self.assertFalse(global_value.ssl_Mutual_exclusion)

    def test_open_sets_connected_socket_timeout(self):
        socket = MagicMock()
        wss = SimpleNamespace(sock=socket)

        WebsocketClient.on_open(wss)

        socket.settimeout.assert_called_once_with(
            WebsocketClient.SOCKET_TIMEOUT_SECONDS
        )


if __name__ == "__main__":
    unittest.main()
