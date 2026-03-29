"""cogweb CLI — start/stop/restart the CogWeb graph visualizer.

Usage:
    cogweb start [--port 8787]      Build frontend (if needed) and start the UI server
    cogweb stop  [--port 8787]      Stop a running server
    cogweb restart [--port 8787]    Restart the server
    cogweb ui [--port 8787]         Open the UI in a browser
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_PID_DIR = Path.home() / ".cogweb"
_APP_DIR = Path(__file__).parent / "ui" / "app"
_DIST_INDEX = Path(__file__).parent / "ui" / "static" / "dist" / "index.html"


def _pid_file(port: int) -> Path:
    return _PID_DIR / f"cogweb-{port}.pid"


def _read_pid(port: int) -> int | None:
    pf = _pid_file(port)
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        pf.unlink(missing_ok=True)
        return None


def _write_pid(port: int, pid: int) -> None:
    _PID_DIR.mkdir(parents=True, exist_ok=True)
    _pid_file(port).write_text(str(pid))


def _remove_pid(port: int) -> None:
    _pid_file(port).unlink(missing_ok=True)


def _ensure_built() -> bool:
    """Build the React Flow frontend if dist/ is missing. Returns True on success."""
    if _DIST_INDEX.exists():
        return True

    if not _APP_DIR.exists():
        print("Warning: app/ source not found, using legacy UI.", file=sys.stderr)
        return True  # server will fall back to static/index.html

    node_modules = _APP_DIR / "node_modules"
    if not node_modules.exists():
        print("Installing frontend dependencies...")
        rc = subprocess.run(["npm", "install"], cwd=_APP_DIR).returncode
        if rc != 0:
            print("npm install failed", file=sys.stderr)
            return False

    print("Building frontend...")
    rc = subprocess.run(["npm", "run", "build"], cwd=_APP_DIR).returncode
    if rc != 0:
        print("Frontend build failed", file=sys.stderr)
        return False

    print("Frontend built.")
    return True


# ── Server script that runs in background ───────────────────────

_SERVER_SCRIPT = '''
import asyncio, json, os, sys
port = int(sys.argv[1])

from coglet.weblet import CogWebRegistry
from cogweb.ui.server import CogWebUI

async def main():
    registry = CogWebRegistry()
    ui = CogWebUI(registry, host="0.0.0.0", port=port)
    await ui.start()
    print(json.dumps({"status": "running", "port": port, "pid": os.getpid()}), flush=True)
    # Run until killed
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await ui.stop()

asyncio.run(main())
'''


# ── Commands ────────────────────────────────────────────────────

def cmd_start(args: argparse.Namespace) -> int:
    port = args.port
    existing = _read_pid(port)
    if existing:
        print(f"cogweb already running on port {port} (pid {existing})")
        return 1

    # Auto-build frontend
    if not _ensure_built():
        return 1

    env = os.environ.copy()
    # Ensure src/ is on PYTHONPATH
    src_dir = str(Path(__file__).parent.parent)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        [sys.executable, "-c", _SERVER_SCRIPT, str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    # Wait for the server to emit its startup JSON
    try:
        line = proc.stdout.readline().decode().strip()  # type: ignore[union-attr]
        info = json.loads(line)
        pid = info["pid"]
        _write_pid(port, pid)
        print(f"cogweb started on http://0.0.0.0:{port} (pid {pid})")

        if args.open:
            _open_browser(port)

        return 0
    except (json.JSONDecodeError, KeyError):
        stderr = proc.stderr.read().decode() if proc.stderr else ""  # type: ignore[union-attr]
        print(f"Failed to start cogweb server:\n{stderr}", file=sys.stderr)
        proc.kill()
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    port = args.port
    pid = _read_pid(port)
    if pid is None:
        print(f"No cogweb server running on port {port}")
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for graceful shutdown
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break
        else:
            # Force kill
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    _remove_pid(port)
    print(f"cogweb stopped (port {port}, pid {pid})")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    pid = _read_pid(args.port)
    if pid:
        cmd_stop(args)
        time.sleep(0.5)
    return cmd_start(args)


def cmd_ui(args: argparse.Namespace) -> int:
    port = args.port
    pid = _read_pid(port)
    if pid is None:
        print(f"No cogweb server on port {port}. Starting one...")
        args.open = False
        rc = cmd_start(args)
        if rc != 0:
            return rc

    _open_browser(port)
    return 0


def _open_browser(port: int) -> None:
    import webbrowser
    url = f"http://localhost:{port}"
    print(f"Opening {url}")
    webbrowser.open(url)


# ── Argument parser ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cogweb",
        description="CogWeb — coglet graph visualizer",
    )
    sub = parser.add_subparsers(dest="command")

    # start
    p_start = sub.add_parser("start", help="Build frontend (if needed) and start the UI server")
    p_start.add_argument("--port", type=int, default=8787, help="Server port (default: 8787)")
    p_start.add_argument("--open", action="store_true", help="Open browser after starting")

    # stop
    p_stop = sub.add_parser("stop", help="Stop a running CogWeb server")
    p_stop.add_argument("--port", type=int, default=8787, help="Server port (default: 8787)")

    # restart
    p_restart = sub.add_parser("restart", help="Restart the CogWeb server")
    p_restart.add_argument("--port", type=int, default=8787, help="Server port (default: 8787)")
    p_restart.add_argument("--open", action="store_true", help="Open browser after starting")

    # ui
    p_ui = sub.add_parser("ui", help="Open the CogWeb UI in a browser (starts server if needed)")
    p_ui.add_argument("--port", type=int, default=8787, help="Server port (default: 8787)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    dispatch = {
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "ui": cmd_ui,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
