"""Dashboard HTTP server with regenerate endpoint.

Serves static files from the dashboard directory and exposes a POST /regenerate
endpoint that triggers the cogamer to rebuild the dashboard.
"""

from __future__ import annotations

import os
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

_COGAMER_NAME = os.environ.get("COGAMER_NAME", "unknown")


_HEARTBEAT_PATH = os.path.expanduser("~/repo/runtime/heartbeat.json")


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/heartbeat.json":
            try:
                with open(_HEARTBEAT_PATH, "rb") as f:
                    data = f.read()
            except FileNotFoundError:
                data = b'{"status":"unknown","message":"No heartbeat yet","timestamp":""}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/regenerate":
            subprocess.run(
                ["tmux", "send-keys", "-t", "main", "Read and follow ~/repo/runtime/skills/dashboard.md", "Enter"],
                capture_output=True,
                timeout=5,
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(405)
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress request logging


def main() -> None:
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    os.chdir(directory)
    server = HTTPServer(("0.0.0.0", 8080), DashboardHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
