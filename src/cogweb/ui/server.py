"""CogWeb UI server — FastAPI + WebSocket bridge to CogWebRegistry.

Serves the React Flow frontend and provides:
  GET  /           — single-page app (graph editor)
  GET  /api/graph  — JSON snapshot of the current graph
  WS   /ws         — live graph updates pushed to the browser
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from coglet.weblet import CogWebRegistry

logger = logging.getLogger("cogweb.ui")

_STATIC_DIR = Path(__file__).parent / "static"


class CogWebUI:
    """Wraps a CogWebRegistry with an HTTP/WebSocket server.

    Usage:
        from coglet.weblet import CogWebRegistry
        from cogweb.ui import CogWebUI

        registry = CogWebRegistry()
        ui = CogWebUI(registry, host="0.0.0.0", port=8787)
        await ui.start()   # non-blocking, runs in background
        ...
        await ui.stop()
    """

    def __init__(
        self,
        registry: CogWebRegistry,
        host: str = "127.0.0.1",
        port: int = 8787,
        poll_interval: float = 0.5,
    ):
        self.registry = registry
        self.host = host
        self.port = port
        self.poll_interval = poll_interval
        self._app: Any = None
        self._server_task: asyncio.Task[None] | None = None
        self._ws_clients: list[Any] = []

    def _build_app(self) -> Any:
        """Build the Starlette/ASGI app (avoids import at module level)."""
        from starlette.applications import Starlette
        from starlette.responses import HTMLResponse, JSONResponse
        from starlette.routing import Route, WebSocketRoute
        from starlette.websockets import WebSocket

        registry = self.registry
        ws_clients = self._ws_clients

        async def index(request: Any) -> HTMLResponse:
            html_path = _STATIC_DIR / "index.html"
            return HTMLResponse(html_path.read_text())

        async def api_graph(request: Any) -> JSONResponse:
            snap = registry.snapshot()
            return JSONResponse(snap.to_dict())

        async def ws_endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            ws_clients.append(websocket)
            try:
                # Send initial snapshot
                snap = registry.snapshot()
                await websocket.send_json({"type": "snapshot", "data": snap.to_dict()})
                # Keep connection alive — client may send commands
                while True:
                    raw = await websocket.receive_text()
                    try:
                        msg = json.loads(raw)
                        await self._handle_ws_message(websocket, msg)
                    except json.JSONDecodeError:
                        await websocket.send_json({"type": "error", "data": "invalid json"})
            except Exception:
                pass
            finally:
                if websocket in ws_clients:
                    ws_clients.remove(websocket)

        async def static_file(request: Any) -> HTMLResponse:
            filename = request.path_params.get("path", "")
            file_path = _STATIC_DIR / filename
            if file_path.exists() and file_path.is_file():
                content_type = "text/css" if filename.endswith(".css") else "application/javascript"
                from starlette.responses import Response
                return Response(file_path.read_text(), media_type=content_type)
            return HTMLResponse("Not found", status_code=404)

        app = Starlette(
            routes=[
                Route("/", index),
                Route("/api/graph", api_graph),
                Route("/static/{path:path}", static_file),
                WebSocketRoute("/ws", ws_endpoint),
            ],
        )
        return app

    async def _handle_ws_message(self, websocket: Any, msg: dict) -> None:
        """Handle incoming WebSocket messages from the UI."""
        msg_type = msg.get("type")
        if msg_type == "refresh":
            snap = self.registry.snapshot()
            await websocket.send_json({"type": "snapshot", "data": snap.to_dict()})
        elif msg_type == "ping":
            await websocket.send_json({"type": "pong"})

    async def _broadcast_loop(self) -> None:
        """Periodically push graph snapshots to all connected WebSocket clients."""
        last_snapshot: str = ""
        while True:
            await asyncio.sleep(self.poll_interval)
            if not self._ws_clients:
                continue
            snap = self.registry.snapshot()
            snap_json = json.dumps(snap.to_dict(), default=str)
            if snap_json == last_snapshot:
                continue
            last_snapshot = snap_json
            msg = {"type": "snapshot", "data": snap.to_dict()}
            dead: list[Any] = []
            for ws in self._ws_clients:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._ws_clients.remove(ws)

    async def start(self) -> None:
        """Start the UI server in the background."""
        import uvicorn

        self._app = self._build_app()
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        self._server_task = asyncio.create_task(server.serve())
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info(f"CogWeb UI running at http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the UI server."""
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, "_broadcast_task") and self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        # Close all WebSocket connections
        for ws in self._ws_clients:
            try:
                await ws.close()
            except Exception:
                pass
        self._ws_clients.clear()
