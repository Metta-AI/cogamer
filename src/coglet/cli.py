"""coglet CLI — manage a persistent coglet runtime via FastAPI.

Commands:
    coglet runtime start [--port PORT] [--trace PATH]
    coglet runtime stop
    coglet runtime status

    coglet create PATH.cog                    -> counter-a3f1
    coglet stop ID
    coglet transmit ID:CHANNEL DATA           push data onto a channel
    coglet observe ID:CHANNEL [--follow]      subscribe to channel output
    coglet enact ID COMMAND [DATA]            send @enact command

    coglet link ID                            list channels for a coglet
    coglet link SRC:CH DEST:CH                wire channels
    coglet unlink SRC:CH DEST:CH
    coglet links

    coglet run PATH.cog [--trace PATH]        one-shot (no daemon)

IDs are "classname-xxxx" (e.g. counter-a3f1).
Channel refs use "id:channel" syntax (e.g. counter-a3f1:count).
MCP endpoint at /mcp.
"""

import asyncio
import hashlib
import importlib
import json
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import click

from coglet.handle import CogBase, Command
from coglet.runtime import CogletRuntime
from coglet.trace import CogletTrace

DEFAULT_PORT = 4510


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _make_id(class_name: str) -> str:
    """Generate a human-readable id: lowered-classname-4hexchars."""
    # Strip common suffixes for brevity
    name = class_name
    for suffix in ("Coglet", "Cog"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    name = name.lower()
    # 4 hex chars from hash of name + time for uniqueness
    h = hashlib.sha256(f"{class_name}{time.time_ns()}".encode()).hexdigest()[:4]
    return f"{name}-{h}"


# ---------------------------------------------------------------------------
# Channel ref parsing: "coglet_id:channel_name"
# ---------------------------------------------------------------------------

def _parse_channel_ref(ref: str) -> tuple[str, str]:
    """Parse 'id:channel' into (id, channel). Exits on bad format."""
    if ":" not in ref:
        sys.exit(f"error: expected 'id:channel', got '{ref}'")
    parts = ref.split(":", 1)
    return parts[0], parts[1]


def _parse_data(raw: str | None) -> Any:
    """Parse CLI data argument as JSON, fall back to string."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest(cog_dir: Path) -> dict[str, Any]:
    manifest_path = cog_dir / "manifest.toml"
    if not manifest_path.exists():
        sys.exit(f"error: {manifest_path} not found")
    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)
    if "coglet" not in manifest or "class" not in manifest["coglet"]:
        sys.exit("error: manifest.toml must have [coglet] with 'class' key")
    return manifest


def resolve_class(dotted: str, cog_dir: Path) -> type:
    parts = dotted.rsplit(".", 1)
    if len(parts) != 2:
        sys.exit(f"error: class must be 'module.ClassName', got '{dotted}'")
    module_name, class_name = parts
    cog_str = str(cog_dir.resolve())
    if cog_str not in sys.path:
        sys.path.insert(0, cog_str)
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        sys.exit(f"error: cannot import module '{module_name}': {e}")
    cls = getattr(module, class_name, None)
    if cls is None:
        sys.exit(f"error: class '{class_name}' not found in '{module_name}'")
    return cls


def build_config(manifest: dict[str, Any], cls: type) -> CogBase:
    kwargs = dict(manifest["coglet"].get("kwargs", {}))
    config_section = manifest.get("config", {})
    return CogBase(
        cls=cls,
        kwargs=kwargs,
        restart=config_section.get("restart", "never"),
        max_restarts=config_section.get("max_restarts", 3),
        backoff_s=config_section.get("backoff_s", 1.0),
    )


def load_cogbase(cog_dir: Path) -> CogBase:
    manifest = load_manifest(cog_dir)
    cls = resolve_class(manifest["coglet"]["class"], cog_dir)
    return build_config(manifest, cls)


def _serialize(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# FastAPI runtime server
# ---------------------------------------------------------------------------

# Enact commands from mixins — hidden from UI to reduce clutter
_INTERNAL_ENACT = {"log_level", "register", "executor", "suppress", "unsuppress", "cogweb_status"}

def create_app(trace_path: str | None = None):
    """Create the FastAPI app with all runtime endpoints + MCP + CogWeb."""
    import signal

    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, StreamingResponse
    from fastapi_mcp import FastApiMCP
    from fastapi.websockets import WebSocket, WebSocketDisconnect

    from contextlib import asynccontextmanager

    _broadcast_task: asyncio.Task | None = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal _broadcast_task
        _broadcast_task = asyncio.create_task(_ui_broadcast())
        yield
        _broadcast_task.cancel()
        try:
            await _broadcast_task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="coglet-runtime", description="Coglet runtime API",
                  lifespan=lifespan)

    trace = CogletTrace(trace_path) if trace_path else None
    runtime = CogletRuntime(trace=trace)
    # id -> (handle, cog_dir, class_name)
    registry: dict[str, tuple[Any, str, str]] = {}
    # (src_id, src_ch, dest_id, dest_ch, task)
    links: list[tuple[str, str, str, str, asyncio.Task]] = []

    # Auto-register any coglet spawned (including children via self.create())
    def _on_spawn(handle, config, parent):
        # Skip if already registered (e.g. from /create endpoint)
        for cid, (h, _, _) in registry.items():
            if h is handle:
                return
        class_name = type(handle.coglet).__name__
        cid = _make_id(class_name)
        registry[cid] = (handle, "", class_name)
    runtime._on_spawn.append(_on_spawn)

    # Auto-register links created via runtime.link()
    def _on_link(src, src_ch, dest, dest_ch, task):
        # Find registry IDs for these handles
        src_id = next((k for k, (h, _, _) in registry.items() if h is src), None)
        dest_id = next((k for k, (h, _, _) in registry.items() if h is dest), None)
        if src_id and dest_id:
            links.append((src_id, src_ch, dest_id, dest_ch, task))
    runtime._on_link.append(_on_link)

    def _lookup(coglet_id: str):
        entry = registry.get(coglet_id)
        if not entry:
            raise HTTPException(404, f"no coglet with id '{coglet_id}'")
        return entry

    def _channels_for(coglet_id: str) -> list[str]:
        """Return list of active channel names for a coglet."""
        handle = _lookup(coglet_id)[0]
        # Channels that have been transmitted on
        bus_channels = list(handle.coglet._bus._subscribers.keys())
        # Channels from @listen handlers
        listen_channels = list(handle.coglet._listen_handlers.keys())
        return sorted(set(bus_channels + listen_channels))

    # Resolve cogs directory relative to cwd at startup
    _cogs_dir = Path.cwd() / "cogs"

    @app.get("/cogs", operation_id="list_cogs")
    async def list_cogs():
        """List available .cog directories."""
        if not _cogs_dir.is_dir():
            return {"cogs": []}
        cogs = []
        for p in sorted(_cogs_dir.iterdir()):
            if p.is_dir() and p.suffix == ".cog":
                manifest_path = p / "manifest.toml"
                if manifest_path.exists():
                    cogs.append({"name": p.stem, "path": str(p.resolve())})
        return {"cogs": cogs}

    @app.post("/create", operation_id="create_coglet")
    async def create_coglet(cog_dir: str):
        """Spawn a coglet from a .cog directory. Returns the coglet_id."""
        path = Path(cog_dir)
        if not path.is_dir():
            raise HTTPException(404, f"'{cog_dir}' is not a directory")
        base = load_cogbase(path)
        handle = await runtime.spawn(base)
        # _on_spawn already registered it; find its cid and update cog_dir
        cid = None
        for k, (h, _, _) in registry.items():
            if h is handle:
                cid = k
                break
        if cid:
            class_name = registry[cid][2]
            registry[cid] = (handle, str(path), class_name)
        else:
            class_name = type(handle.coglet).__name__
            cid = _make_id(class_name)
            registry[cid] = (handle, str(path), class_name)
        return {"id": cid, "class": class_name}

    @app.post("/stop/{coglet_id}", operation_id="stop_coglet")
    async def stop_coglet(coglet_id: str):
        """Stop a running coglet and all its descendants."""
        handle, _, class_name = _lookup(coglet_id)
        # Collect all descendant IDs
        descendants = runtime._get_descendants(handle.coglet)
        dead_ids = {coglet_id}
        for desc in descendants:
            for cid, (h, _, _) in registry.items():
                if h.coglet is desc:
                    dead_ids.add(cid)
                    break
        # Cancel links involving any dead coglet
        remaining = []
        for src, src_ch, dest, dest_ch, task in links:
            if src in dead_ids or dest in dead_ids:
                task.cancel()
            else:
                remaining.append((src, src_ch, dest, dest_ch, task))
        links.clear()
        links.extend(remaining)
        # Stop coglet + descendants in runtime
        await runtime._stop_coglet(handle.coglet)
        # Remove from registry
        for did in dead_ids:
            registry.pop(did, None)
        return {"msg": f"stopped {class_name} (id={coglet_id}) + {len(dead_ids)-1} children"}

    @app.post("/enact/{coglet_id}", operation_id="enact_coglet")
    async def enact_coglet(coglet_id: str, command: str, data: Any = None):
        """Send a command to a coglet's @enact handlers."""
        handle = _lookup(coglet_id)[0]
        await handle.guide(Command(type=command, data=data))
        return {"msg": f"sent '{command}' to {coglet_id}"}

    @app.post("/transmit/{coglet_id}/{channel}", operation_id="transmit_coglet")
    async def transmit_coglet(coglet_id: str, channel: str, data: Any = None):
        """Push data into a coglet's channel.

        Delivers via _dispatch_listen which fires the @listen handler
        and pushes to the bus (so links and observers see it).
        """
        handle = _lookup(coglet_id)[0]
        await handle.coglet._dispatch_listen(channel, data)
        return {"msg": f"transmitted on {coglet_id}:{channel}"}

    @app.get("/channels/{coglet_id}", operation_id="list_channels")
    async def list_channels(coglet_id: str):
        """List all channels (transmit + @listen) for a coglet."""
        handle, _, class_name = _lookup(coglet_id)
        transmit_chs = list(handle.coglet._bus._subscribers.keys())
        listen_chs = list(handle.coglet._listen_handlers.keys())
        return {
            "id": coglet_id,
            "class": class_name,
            "transmit": sorted(transmit_chs),
            "listen": sorted(listen_chs),
        }

    @app.get("/observe/{coglet_id}/{channel}", operation_id="observe_coglet")
    async def observe_coglet(coglet_id: str, channel: str):
        """Subscribe to a coglet's channel output (SSE stream)."""
        handle = _lookup(coglet_id)[0]
        sub = handle.coglet._bus.subscribe(channel)

        async def event_stream():
            try:
                async for event_data in sub:
                    payload = json.dumps(_serialize(event_data))
                    yield f"data: {payload}\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/link", operation_id="link_channels")
    async def link_channels(
        src_id: str, src_channel: str, dest_id: str, dest_channel: str
    ):
        """Wire src's transmit channel to dest's @listen channel via runtime."""
        src_handle = _lookup(src_id)[0]
        _lookup(dest_id)  # validate dest exists
        dest_handle = registry[dest_id][0]
        runtime.link(src_handle, src_channel, dest_handle, dest_channel)
        # _on_link callback auto-registers in links list
        return {
            "msg": f"{src_id}:{src_channel} -> {dest_id}:{dest_channel}",
        }

    @app.delete("/link", operation_id="unlink_channels")
    async def unlink_channels(
        src_id: str, src_channel: str, dest_id: str, dest_channel: str
    ):
        """Remove a channel link."""
        remaining = []
        found = False
        for s, sc, d, dc, task in links:
            if s == src_id and sc == src_channel and d == dest_id and dc == dest_channel:
                task.cancel()
                found = True
            else:
                remaining.append((s, sc, d, dc, task))
        links.clear()
        links.extend(remaining)
        if not found:
            raise HTTPException(404, "link not found")
        return {"msg": f"unlinked {src_id}:{src_channel} -> {dest_id}:{dest_channel}"}

    @app.get("/links", operation_id="list_links")
    async def list_links():
        """List all active channel links."""
        return {
            "links": [
                {"src": s, "src_channel": sc, "dest": d, "dest_channel": dc}
                for s, sc, d, dc, _ in links
            ]
        }

    def _id_map() -> dict[int, str]:
        return {id(handle.coglet): cid for cid, (handle, _, _) in registry.items()}

    @app.get("/status", operation_id="runtime_status")
    async def status():
        """Show runtime status: tree, coglet list, and links."""
        coglets = []
        for cid, (handle, cog_dir, class_name) in registry.items():
            coglets.append({
                "id": cid,
                "class": class_name,
                "cog_dir": cog_dir,
                "children": len(handle.coglet._children),
                "channels": _channels_for(cid),
            })
        return {
            "tree": runtime.tree(id_map=_id_map()),
            "coglets": coglets,
            "links": [
                {"src": s, "src_channel": sc, "dest": d, "dest_channel": dc}
                for s, sc, d, dc, _ in links
            ],
        }

    @app.get("/stats/{coglet_id}", operation_id="channel_stats")
    async def channel_stats(coglet_id: str, channel: str | None = None):
        """Get message count stats (1s/5s/60s/1h/24h) and recent history."""
        handle = _lookup(coglet_id)[0]
        bus = handle.coglet._bus
        if channel:
            return {
                "channel": channel,
                "counts": bus.stats.counts(channel),
                "history": [_serialize(m) for m in bus.stats.history(channel, 10)],
            }
        return {"channels": bus.stats.all_counts()}

    @app.get("/history/{coglet_id}/{channel}", operation_id="channel_history")
    async def channel_history(coglet_id: str, channel: str, n: int = 10):
        """Get last N messages from a channel (outbound or inbound)."""
        handle = _lookup(coglet_id)[0]
        cog = handle.coglet
        # Check outbound (transmit) first, then inbound (listen)
        msgs = cog._bus.stats.history(channel, n)
        if not msgs:
            msgs = cog._inbound_stats.history(channel, n)
        return {"channel": channel, "messages": [_serialize(m) for m in msgs]}

    @app.get("/tree", operation_id="runtime_tree")
    async def tree():
        return {"tree": runtime.tree(id_map=_id_map())}

    @app.post("/shutdown", operation_id="shutdown_runtime")
    async def shutdown():
        async def _shutdown():
            await asyncio.sleep(0.5)
            for _, _, _, _, task in links:
                task.cancel()
            await runtime.shutdown()
            import os
            os.kill(os.getpid(), signal.SIGTERM)
        asyncio.create_task(_shutdown())
        return {"msg": "shutting down"}

    # --- UI (graph visualization) ---

    _ui_static = Path(__file__).parent / "ui" / "static"
    _ui_ws_clients: list[WebSocket] = []
    _ui_last_snapshot: str = ""
    _no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    def _discover_transmit_channels(cls: type) -> list[str]:
        """Discover transmit channels by scanning source for self.transmit("...") calls."""
        import ast, inspect, textwrap
        channels = set()
        for klass in cls.__mro__:
            try:
                src = inspect.getsource(klass)
            except (TypeError, OSError):
                continue
            try:
                tree = ast.parse(textwrap.dedent(src))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "transmit"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                    channels.add(node.args[0].value)
        return sorted(channels)

    # Cache: class -> transmit channels
    _transmit_cache: dict[type, list[str]] = {}

    def _mixin_info(cls: type) -> dict:
        """Extract mixin metadata: docstring, methods, file path."""
        import inspect
        doc = (cls.__doc__ or "").strip().split("\n")[0]  # first line
        # Public methods defined directly on this class (not inherited)
        methods = sorted(
            name for name, val in vars(cls).items()
            if callable(val) and not name.startswith("_")
        )
        try:
            filepath = inspect.getfile(cls)
        except (TypeError, OSError):
            filepath = ""
        return {"description": doc, "methods": methods, "file": filepath}

    # Cache: mixin class name -> info
    _mixin_cache: dict[str, dict] = {}

    def _get_mixin_infos(cog_cls: type) -> dict[str, dict]:
        """Get mixin info for all *Let mixins in a coglet class."""
        result = {}
        for klass in cog_cls.__mro__:
            name = klass.__name__
            if name.endswith("Let") and name != "Coglet":
                if name not in _mixin_cache:
                    _mixin_cache[name] = _mixin_info(klass)
                result[name] = _mixin_cache[name]
        return result

    def _get_mixin_state(cog) -> dict:
        """Extract runtime state from each mixin on a coglet."""
        state = {}
        # ProgLet — program table
        if hasattr(cog, 'programs'):
            progs = {}
            import inspect, textwrap
            for name, prog in cog.programs.items():
                fn_source = ""
                if prog.fn is not None:
                    try:
                        fn_source = textwrap.dedent(inspect.getsource(prog.fn))
                    except (TypeError, OSError):
                        fn_source = repr(prog.fn)
                system_text = ""
                if prog.system is not None:
                    if callable(prog.system):
                        try:
                            system_text = textwrap.dedent(inspect.getsource(prog.system))
                        except (TypeError, OSError):
                            system_text = "(dynamic system prompt)"
                    else:
                        system_text = str(prog.system)
                progs[name] = {
                    "executor": prog.executor,
                    "has_fn": prog.fn is not None,
                    "has_system": prog.system is not None,
                    "fn_source": fn_source,
                    "system_text": system_text,
                    "tools": prog.tools,
                    "config": {k: str(v) for k, v in prog.config.items()} if prog.config else {},
                }
            state["ProgLet"] = {"programs": progs}
        # TickLet — tick intervals
        if hasattr(cog, '_every_handlers'):
            ticks = []
            for method_name, interval, unit in cog._every_handlers:
                ticks.append({"method": method_name, "interval": interval, "unit": unit})
            state["TickLet"] = {"tickers": ticks}
        # SuppressLet — suppressed channels
        suppressed_ch = getattr(cog, '_suppressed_channels', None)
        suppressed_cmd = getattr(cog, '_suppressed_commands', None)
        if suppressed_ch is not None or suppressed_cmd is not None:
            state["SuppressLet"] = {
                "suppressed_channels": list(suppressed_ch) if suppressed_ch else [],
                "suppressed_commands": list(suppressed_cmd) if suppressed_cmd else [],
            }
        # LogLet — log level
        if hasattr(cog, '_log_level'):
            state["LogLet"] = {"level": cog._log_level}
        # MulLet — children count
        if hasattr(cog, '_mul_children'):
            state["MulLet"] = {"children_count": len(cog._mul_children)}
        # GitLet — repo info
        if hasattr(cog, '_git_repo'):
            state["GitLet"] = {"repo": str(getattr(cog, '_git_repo', ''))}
        return state

    def _ui_snapshot() -> dict:
        """Build a graph snapshot from the runtime registry."""
        id_map = _id_map()
        # Reverse map: id(coglet) -> registry cid
        obj_to_cid = {id(h.coglet): cid for cid, (h, _, _) in registry.items()}
        nodes = {}
        for cid, (handle, cog_dir, class_name) in registry.items():
            cog = handle.coglet
            mixins = [
                cls.__name__ for cls in type(cog).__mro__
                if cls.__name__.endswith("Let") and cls.__name__ != "Coglet"
            ]
            # Merge bus channels with statically discovered transmit channels
            cls = type(cog)
            if cls not in _transmit_cache:
                _transmit_cache[cls] = _discover_transmit_channels(cls)
            listen_chs = set(cog._listen_handlers.keys())
            bus_chs = cog._bus._subscribers
            # Output channels: bus channels + statically discovered, excluding @listen channels
            channels = {ch: len(subs) for ch, subs in bus_chs.items() if ch not in listen_chs}
            for ch in _transmit_cache[cls]:
                if ch not in channels and ch not in listen_chs:
                    channels[ch] = 0
            children = [obj_to_cid[id(ch.coglet)]
                        for ch in cog._children if id(ch.coglet) in obj_to_cid]
            parent = runtime._parents.get(id(cog))
            parent_id = obj_to_cid.get(id(parent)) if parent else None
            config = {}
            cfg = runtime._configs.get(id(cog))
            if cfg:
                config = {"restart": cfg.restart, "max_restarts": cfg.max_restarts,
                          "backoff_s": cfg.backoff_s}
            # Channel message counts per time window (outbound + inbound)
            ch_stats = cog._bus.stats.all_counts()
            for ch, counts in cog._inbound_stats.all_counts().items():
                ch_stats[ch] = counts
            label = cfg.label if cfg else ""
            mixin_state = _get_mixin_state(cog)
            nodes[cid] = {
                "node_id": cid,
                "class_name": class_name,
                "label": label,
                "mixins": mixins,
                "mixin_info": _get_mixin_infos(type(cog)),
                "channels": channels,
                "channel_stats": ch_stats,
                "listen_channels": list(cog._listen_handlers.keys()),
                "enact_commands": [cmd for cmd in cog._enact_handlers
                                   if cmd not in _INTERNAL_ENACT],
                "children": children,
                "parent_id": parent_id,
                "config": config,
                "mixin_state": mixin_state,
                "status": "running",
            }
        edges = [
            {"from": s, "to": d, "channel": f"{sc}->{dc}", "kind": "data",
             "src_channel": sc}
            for s, sc, d, dc, _ in links
        ]
        # Control edges: parent -> child for @enact commands
        for cid, node in nodes.items():
            if node["parent_id"] and node["enact_commands"]:
                edges.append({
                    "from": node["parent_id"], "to": cid,
                    "channel": ", ".join(node["enact_commands"]),
                    "kind": "control",
                })
        return {"nodes": nodes, "edges": edges}

    @app.get("/ui", operation_id="ui_index", include_in_schema=False)
    async def ui_index():
        html_path = _ui_static / "index.html"
        if not html_path.exists():
            raise HTTPException(404, "UI not found")
        return HTMLResponse(html_path.read_text(), headers=_no_cache)

    @app.get("/ui/graph", operation_id="ui_graph")
    async def ui_graph():
        """JSON snapshot of the runtime graph."""
        return _ui_snapshot()

    @app.websocket("/ui/ws")
    async def ui_ws(websocket: WebSocket):
        await websocket.accept()
        _ui_ws_clients.append(websocket)
        try:
            await websocket.send_json({"type": "snapshot", "data": _ui_snapshot()})
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    if msg.get("type") == "refresh":
                        await websocket.send_json({"type": "snapshot", "data": _ui_snapshot()})
                    elif msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "data": "invalid json"})
        except WebSocketDisconnect:
            pass
        except Exception:
            import traceback; traceback.print_exc()
        finally:
            if websocket in _ui_ws_clients:
                _ui_ws_clients.remove(websocket)

    @app.get("/ui/static/{path:path}", include_in_schema=False)
    async def ui_static(path: str):
        file_path = _ui_static / path
        if file_path.exists() and file_path.is_file():
            from starlette.responses import Response
            ct = "text/css" if path.endswith(".css") else "application/javascript"
            return Response(file_path.read_text(), media_type=ct, headers=_no_cache)
        raise HTTPException(404, "not found")

    async def _ui_broadcast():
        """Push graph snapshots to connected WebSocket clients."""
        nonlocal _ui_last_snapshot
        while True:
            await asyncio.sleep(0.5)
            if not _ui_ws_clients:
                continue
            snap = _ui_snapshot()
            snap_json = json.dumps(snap, default=str)
            if snap_json == _ui_last_snapshot:
                continue
            _ui_last_snapshot = snap_json
            msg = {"type": "snapshot", "data": snap}
            dead: list[WebSocket] = []
            for ws in _ui_ws_clients:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _ui_ws_clients.remove(ws)

    mcp = FastApiMCP(app, name="coglet-runtime", description="Coglet runtime MCP server")
    mcp.mount_http()

    return app


def start_server(port: int, trace_path: str | None = None, foreground: bool = False) -> None:
    if foreground:
        import uvicorn
        app = create_app(trace_path=trace_path)
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
        return

    import os, subprocess, sys, time
    cmd = [sys.executable, "-m", "coglet.cli", "runtime", "start", "--foreground",
           "--port", str(port)]
    if trace_path:
        cmd += ["--trace", trace_path]
    # Ensure the subprocess can find the same coglet package as the parent
    env = os.environ.copy()
    src_dir = str(Path(__file__).parent.parent)
    paths = env.get("PYTHONPATH", "").split(os.pathsep)
    if src_dir not in paths:
        paths.insert(0, src_dir)
    env["PYTHONPATH"] = os.pathsep.join(p for p in paths if p)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=env)
    # Wait briefly and check the process is alive and port is responding
    time.sleep(0.5)
    if proc.poll() is not None:
        print(f"error: runtime exited immediately (code {proc.returncode})")
        sys.exit(1)
    try:
        _get(port, "/status")
        print(f"coglet runtime started (pid={proc.pid}, port={port})")
    except Exception:
        print(f"coglet runtime started (pid={proc.pid}, port={port}) [not yet responding]")


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _post(port: int, path: str, **params) -> dict:
    import urllib.request
    import urllib.parse
    url = f"{_base_url(port)}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        sys.exit(f"error: {body.get('detail', body)}")
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _delete(port: int, path: str, **params) -> dict:
    import urllib.request
    import urllib.parse
    url = f"{_base_url(port)}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        sys.exit(f"error: {body.get('detail', body)}")
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _get(port: int, path: str) -> dict:
    import urllib.request
    url = f"{_base_url(port)}{path}"
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


def _observe_sse(port: int, coglet_id: str, channel: str, follow: bool) -> None:
    import urllib.request
    url = f"{_base_url(port)}/observe/{coglet_id}/{channel}"
    try:
        with urllib.request.urlopen(url) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if line.startswith("data: "):
                    print(line[6:])
                    if not follow:
                        return
    except KeyboardInterrupt:
        pass
    except urllib.error.URLError as e:
        sys.exit(f"error: cannot connect to runtime on port {port}: {e}")


# ---------------------------------------------------------------------------
# One-shot run
# ---------------------------------------------------------------------------

async def run_oneshot(cog_dir: Path, trace_path: str | None = None) -> None:
    import signal as sig
    base = load_cogbase(cog_dir)
    trace = CogletTrace(trace_path) if trace_path else None
    runtime = CogletRuntime(trace=trace)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (sig.SIGINT, sig.SIGTERM):
        loop.add_signal_handler(s, stop.set)

    await runtime.run(base)
    print(runtime.tree())
    await stop.wait()
    print("\nshutting down...")
    await runtime.shutdown()


# ---------------------------------------------------------------------------
# CLI (Click)
# ---------------------------------------------------------------------------

_port_option = click.option("--port", "-p", type=int, default=DEFAULT_PORT,
                            help=f"Runtime API port (default: {DEFAULT_PORT}).")


@click.group()
def main():
    """Manage coglet runtimes."""


# --- runtime ---

@main.group()
def runtime():
    """Manage the runtime daemon."""


@runtime.command()
@_port_option
@click.option("--trace", type=str, default=None, help="Path for trace recording.")
@click.option("--foreground", is_flag=True, help="Run in foreground (default: daemon).")
def start(port, trace, foreground):
    """Start the runtime server."""
    start_server(port, trace_path=trace, foreground=foreground)


@runtime.command()
@_port_option
def stop(port):
    """Stop the runtime server."""
    click.echo(_post(port, "/shutdown").get("msg"))


@runtime.command()
@_port_option
def status(port):
    """Show runtime status."""
    resp = _get(port, "/status")
    click.echo(resp["tree"])
    if resp["coglets"]:
        click.echo()
        for c in resp["coglets"]:
            chs = ", ".join(c.get("channels", []))
            click.echo(f"  {c['id']}  {c['class']}  children={c['children']}  channels=[{chs}]")
    if resp.get("links"):
        click.echo()
        for lk in resp["links"]:
            click.echo(f"  {lk['src']}:{lk['src_channel']} -> {lk['dest']}:{lk['dest_channel']}")
    if not resp["coglets"]:
        click.echo("\nno coglets running.")


# --- ui ---

@main.group()
def ui():
    """Manage the coglet UI."""


@ui.command("start")
@_port_option
def ui_start(port):
    """Open the UI in a browser."""
    _open_ui(port)


@ui.command("launch")
@_port_option
def ui_launch(port):
    """Open the UI in a browser."""
    _open_ui(port)


@ui.command("stop")
@_port_option
def ui_stop(port):
    """Stop the UI (served by the runtime)."""
    click.echo("UI is served by the runtime — use 'coglet runtime stop' to stop both.")


@ui.command("restart")
@_port_option
def ui_restart(port):
    """Restart the UI (served by the runtime)."""
    click.echo("UI is served by the runtime — restart the runtime to restart the UI.")


def _open_ui(port):
    import webbrowser
    url = f"http://127.0.0.1:{port}/ui"
    try:
        _get(port, "/status")
    except SystemExit:
        raise click.ClickException(
            f"runtime not running on port {port}. Start it with: coglet runtime start")
    webbrowser.open(url)
    click.echo(f"opened {url}")


# --- create ---

@main.command("create")
@_port_option
@click.argument("cog_dir", type=click.Path(exists=True, file_okay=False))
def create_cmd(port, cog_dir):
    """Spawn a coglet from a .cog directory."""
    resp = _post(port, "/create", cog_dir=str(Path(cog_dir).resolve()))
    click.echo(resp["id"])


# --- stop ---

@main.command("stop")
@_port_option
@click.argument("id")
def stop_cmd(port, id):
    """Stop a running coglet by ID."""
    click.echo(_post(port, f"/stop/{id}").get("msg"))


# --- transmit ---

@main.command()
@_port_option
@click.argument("target")
@click.argument("data", required=False, default=None)
def transmit(port, target, data):
    """Push data onto a coglet's channel (TARGET = id:channel)."""
    cid, ch = _parse_channel_ref(target)
    data_val = _parse_data(data)
    params = {}
    if data_val is not None:
        params["data"] = json.dumps(data_val) if not isinstance(data_val, str) else data_val
    click.echo(_post(port, f"/transmit/{cid}/{ch}", **params).get("msg"))


# --- observe ---

@main.command()
@_port_option
@click.argument("target")
@click.option("--follow", is_flag=True, help="Keep streaming.")
def observe(port, target, follow):
    """Subscribe to a coglet's channel output (TARGET = id:channel)."""
    cid, ch = _parse_channel_ref(target)
    _observe_sse(port, cid, ch, follow)


# --- enact ---

@main.command()
@_port_option
@click.argument("id")
@click.argument("command")
@click.argument("data", required=False, default=None)
def enact(port, id, command, data):
    """Send a command to a coglet's @enact handlers."""
    data_val = _parse_data(data)
    params = {"command": command}
    if data_val is not None:
        params["data"] = json.dumps(data_val) if not isinstance(data_val, str) else data_val
    click.echo(_post(port, f"/enact/{id}", **params).get("msg"))


# --- link ---

@main.command()
@_port_option
@click.argument("src")
@click.argument("dest", required=False, default=None)
def link(port, src, dest):
    """Wire channels (link SRC:CH DEST:CH) or list channels (link ID)."""
    if dest is None:
        resp = _get(port, f"/channels/{src}")
        click.echo(f"{resp['id']} ({resp['class']})")
        if resp["transmit"]:
            click.echo(f"  transmit: {', '.join(resp['transmit'])}")
        if resp["listen"]:
            click.echo(f"  listen:   {', '.join(resp['listen'])}")
        if not resp["transmit"] and not resp["listen"]:
            click.echo("  (no channels)")
    else:
        src_id, src_ch = _parse_channel_ref(src)
        dest_id, dest_ch = _parse_channel_ref(dest)
        resp = _post(port, "/link",
                     src_id=src_id, src_channel=src_ch,
                     dest_id=dest_id, dest_channel=dest_ch)
        click.echo(resp.get("msg"))


# --- unlink ---

@main.command()
@_port_option
@click.argument("src")
@click.argument("dest")
def unlink(port, src, dest):
    """Remove a channel link (SRC:CH DEST:CH)."""
    src_id, src_ch = _parse_channel_ref(src)
    dest_id, dest_ch = _parse_channel_ref(dest)
    resp = _delete(port, "/link",
                   src_id=src_id, src_channel=src_ch,
                   dest_id=dest_id, dest_channel=dest_ch)
    click.echo(resp.get("msg"))


# --- links ---

@main.command()
@_port_option
def links(port):
    """List all active channel links."""
    resp = _get(port, "/links")
    for lk in resp["links"]:
        click.echo(f"  {lk['src']}:{lk['src_channel']} -> {lk['dest']}:{lk['dest_channel']}")
    if not resp["links"]:
        click.echo("no links.")


# --- shell ---

@main.command()
@_port_option
def shell(port):
    """Interactive shell with tab-completion."""
    from coglet.shell import run_shell
    run_shell(port)


# --- run ---

@main.command()
@click.argument("cog_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--trace", type=str, default=None, help="Path for trace recording.")
def run(cog_dir, trace):
    """One-shot run (no daemon)."""
    asyncio.run(run_oneshot(Path(cog_dir), trace_path=trace))


if __name__ == "__main__":
    main()
