"""Exercise the real transport against a loopback server that stalls in headers."""
from pathlib import Path
import socketserver
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transfer import transport


class TrickleHeaders(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(4096)
        header = b'HTTP/1.1 206 Partial Content\r\n'
        for byte in header:
            try:
                self.request.sendall(bytes([byte]))
            except OSError:
                break
            time.sleep(0.04)


with socketserver.TCPServer(('127.0.0.1', 0), TrickleHeaders) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            transport(f'http://127.0.0.1:{server.server_address[1]}/',
                      {'Range': 'bytes=0-0'}, 0.2)
        except TimeoutError as exc:
            assert 'whole range deadline' in str(exc)
        else:
            raise AssertionError('trickling headers escaped the whole request deadline')
    finally:
        server.shutdown()
print('PASS: trickling headers hit the whole request deadline')
