# AGENTS.md

Documentation for AI agents working with the coglet codebase.

## Framework Overview

Coglet is a framework for fractal asynchronous control of distributed agent systems.
Every Coglet is simultaneously a **COG** (supervisor) and a **LET** (executor),
forming a recursive temporal hierarchy with the same protocol at every level.

## Source Layout

```
src/coglet/
├── __init__.py        # Package exports (all public types)
├── coglet.py          # Base Coglet class + @listen/@enact decorators
├── channel.py         # Channel, ChannelSubscription, ChannelBus (async pub/sub)
├── handle.py          # Command, CogletConfig, CogletHandle (child references)
├── runtime.py         # CogletRuntime (spawn, shutdown, tree, restart, tracing)
├── lifelet.py         # LifeLet mixin (on_start/on_stop lifecycle hooks)
├── ticklet.py         # TickLet mixin + @every decorator (periodic execution)
├── proglet.py         # ProgLet mixin (unified program table with pluggable executors)
├── llm_executor.py    # LLMExecutor (multi-turn LLM conversations with tool use)
├── gitlet.py          # GitLet mixin (repo-as-policy, git patches)
├── loglet.py          # LogLet mixin (separate log channel with levels)
├── mullet.py          # MulLet mixin (fan-out N children, scatter/gather)
├── suppresslet.py     # SuppressLet mixin (gate channels/commands)
├── weblet.py          # WebLet mixin + CogWebRegistry + CogWebSnapshot
└── trace.py           # CogletTrace (jsonl event recording)

src/cogweb/
├── __init__.py        # Package init
├── cli.py             # cogweb CLI (start/stop/restart/ui)
└── ui/
    ├── server.py      # CogWebUI — Starlette server (REST + WebSocket)
    ├── static/        # Legacy index.html + Vite build output (dist/)
    └── app/           # React Flow frontend source (Vite + TypeScript)
        ├── src/
        │   ├── App.tsx         # Main app — ReactFlow canvas + WebSocket glue
        │   ├── CogletNode.tsx  # Custom node with typed ports + status badge
        │   ├── Inspector.tsx   # Right panel — node detail + guide commands
        │   ├── useWebSocket.ts # WebSocket hook with auto-reconnect
        │   └── types.ts        # Wire types matching Python CogWebSnapshot
        ├── package.json
        └── vite.config.ts

cogames/               # CvC player: Coach, PlayerCoglet, PolicyCoglet
tests/                 # 220+ tests across unit + integration
docs/                  # Architecture and design docs
```

## Component Reference

### coglet.py — Base Coglet Class

The universal primitive. Every coglet has two interfaces:

**LET interface** (receiving and producing data):
- `@listen(channel)` — decorator, registers a method as data-plane handler
- `@enact(command_type)` — decorator, registers a method as control-plane handler
- `transmit(channel, data)` — async, pushes data to all channel subscribers
- `transmit_sync(channel, data)` — non-async variant

**COG interface** (managing children):
- `create(config) -> CogletHandle` — spawn a child coglet
- `observe(handle, channel)` — async iterator over child's channel output
- `guide(handle, command)` — fire-and-forget command to child's @enact handlers

**Supervision**:
- `on_child_error(handle, error) -> str` — returns "restart", "stop", or "escalate"

Handler discovery uses `__init_subclass__` to scan the MRO for decorated methods.
Both sync and async handlers are supported (checked via `hasattr(result, "__await__")`).

### channel.py — Async Pub/Sub

- `Channel` — single async queue, supports `put`/`get`/`async for`
- `ChannelSubscription` — independent subscriber with its own queue
- `ChannelBus` — per-coglet registry. `transmit()` pushes to all subscribers on a
  channel. Each `subscribe()` creates an independent queue (no message loss from
  slow consumers). Channels are created on demand via `_ensure_channel()`.

**Important**: subscribers must be created *before* transmit to receive data.
There is no replay/history — missed messages are gone.

### handle.py — Child References

- `Command(type, data)` — control-plane message sent via `guide()`
- `CogletConfig(cls, kwargs, restart, max_restarts, backoff_s)` — instantiation config.
  `restart` can be `"never"` (default), `"on_error"`, or `"always"`.
- `CogletHandle` — opaque reference to a running child. Exposes `observe(channel)`
  and `guide(command)`. The parent never accesses the child directly.

### runtime.py — Lifecycle Management

`CogletRuntime` manages the coglet tree:

- `spawn(config, parent)` — instantiate, call on_start, start tickers, return handle
- `run(config)` — spawn a root coglet (no parent)
- `shutdown()` — stop all coglets in reverse spawn order (LIFO)
- `tree()` — ASCII visualization of the live supervision hierarchy
- `handle_child_error(handle, error)` — consult parent's on_child_error, apply restart policy

**Tracing**: pass `CogletRuntime(trace=CogletTrace("path.jsonl"))` to record all
transmit/enact events. The runtime wraps each coglet's methods transparently.

**Restart**: on child error, the runtime asks the parent, then applies exponential
backoff (`backoff_s * 2^attempt`). The CogletHandle is preserved — it points to the
new instance after restart.

### Mixins

All mixins use cooperative multiple inheritance (`super().__init__(**kwargs)`).
Order in the class definition matters (MRO). Mixins that override Coglet methods
(like SuppressLet) must appear before Coglet in the MRO.

#### lifelet.py — Lifecycle Hooks
- `on_start()` — called by runtime after spawn. Raising aborts.
- `on_stop()` — called by runtime during shutdown.

#### ticklet.py — Periodic Execution
- `@every(interval, unit)` — decorator. Units: `"s"`, `"m"`, `"ticks"`
- Time-based tickers run as asyncio tasks. Tick-based require manual `self.tick()`.
- `on_ticker_error(method_name, error)` — called when a ticker raises. Override to
  customize. Default: log via LogLet if available. `CancelledError` is re-raised.

#### proglet.py — Unified Program Table
- `self.programs: dict[str, Program]` — named programs with pluggable executors
- `Program(executor, fn, system, tools, parser, config)` — unit of computation
- `Executor` protocol — pluggable backend (`CodeExecutor`, `LLMExecutor`)
- `@enact("register")` — register/replace programs at runtime via `guide()`
- `@enact("executor")` — register custom executors at runtime
- `await self.invoke(name, context)` — run a program by name

#### llm_executor.py — LLM Conversations
- `LLMExecutor(client)` — executor for multi-turn LLM conversations
- Supports tool use — programs can invoke other programs as LLM tools
- Supports callable system prompts — `system(context)` for dynamic prompts
- Configurable via `Program.config`: model, temperature, max_tokens, max_turns

#### gitlet.py — Repo-as-Policy
- `repo_path` — defaults to cwd
- `_git(*args)` — async subprocess wrapper
- `@enact("commit")` — apply a git patch as a commit
- `revert(n)`, `branch(name)`, `checkout(ref)` — git operations

#### loglet.py — Log Stream
- `log(level, data)` — transmits on `"log"` channel if level passes filter
- `@enact("log_level")` — change verbosity at runtime via `guide()`
- Levels: `debug`, `info`, `warn`, `error`

#### mullet.py — Fan-Out N Children
- `create_mul(n, config)` — spawn N identical children
- `map(event)` — route event to children (default: broadcast). Override for custom routing.
- `reduce(results)` — aggregate outputs (default: list). Override for custom aggregation.
- `scatter(channel, event)` — distribute via map()
- `gather(channel)` — collect one result from each child, then reduce()
- `guide_mapped(command)` — send same command to all children

#### suppresslet.py — Output Gating
- `@enact("suppress")` — suppress channels and/or commands: `{"channels": [...], "commands": [...]}`
- `@enact("unsuppress")` — restore suppressed channels/commands
- Overrides `transmit()` and `_dispatch_enact()` to gate output
- Meta-commands (suppress/unsuppress) always pass through
- Must appear before Coglet in MRO: `class MyLET(SuppressLet, Coglet): ...`

#### weblet.py — CogWeb Graph Registration
- `WebLet` mixin — registers a coglet with `CogWebRegistry` on start, deregisters on stop
- Requires `cogweb: CogWebRegistry` kwarg. Inert (no-op) if not provided.
- `@enact("cogweb_status")` — set node status from COG or UI
- `CogWebRegistry` — collects live coglet references, builds fresh snapshots on demand
- `CogWebSnapshot` — serializable graph: `{nodes: {id: CogWebNode}, edges: [...]}`
- `CogWebNode` — per-node metadata: class_name, mixins, channels, listen_channels,
  enact_commands, children, parent_id, config, status, updated_at

### trace.py — Event Recording

- `CogletTrace(path)` — open a jsonl file for writing
- `record(coglet_type, op, target, data)` — append one event
- `close()` — flush and close
- `CogletTrace.load(path)` — static, load trace for inspection

Each line: `{"t": <seconds_since_start>, "coglet": "ClassName", "op": "transmit"|"enact", "target": "<channel_or_command>", "data": ...}`

## CogWeb — Graph Visualizer

CogWeb is a browser-based graph visualizer and control panel for live coglet
supervision trees. It renders the graph using [React Flow](https://reactflow.dev/)
with real-time WebSocket updates from the coglet runtime.

### CLI

```bash
cogweb start [--port 8787] [--open]   # auto-build frontend + start server
cogweb stop  [--port 8787]            # stop the server
cogweb restart [--port 8787]          # stop + rebuild + start
cogweb ui [--port 8787]               # open browser (auto-starts if needed)
```

- `start` auto-builds the React Flow frontend (`npm install` + `npm run build`)
  if `static/dist/index.html` doesn't exist. Subsequent starts skip the build.
- PID files stored in `~/.cogweb/cogweb-{port}.pid`.
- Registered as `console_scripts` entry point; also runnable via `python -m cogweb.cli`.

### Architecture

```
coglet runtime
    |
    v
CogWebRegistry       <-- WebLet mixins register on_start, deregister on_stop
    |
    v
CogWebUI (Starlette)
    ├── GET  /            serves React Flow SPA (dist/index.html)
    ├── GET  /api/graph   returns CogWebSnapshot as JSON
    └── WS   /ws          pushes snapshots every 500ms + accepts control commands
                |
                v
         React Flow app (browser)
              ├── CogletNode.tsx   — custom node with typed ports
              ├── Inspector.tsx    — right panel for node detail + guide commands
              └── useWebSocket.ts  — auto-reconnect WebSocket hook
```

### WebSocket Protocol

Messages from server to client:

| Type | Payload | When |
|---|---|---|
| `snapshot` | `{nodes: {...}, edges: [...]}` | Every 500ms if changed, or on connect |
| `pong` | — | Response to client ping |
| `guide_result` | `{node_id, ok, error?}` | After client sends guide command |
| `status_updated` | `{node_id, status}` | After client changes status |
| `error` | `{data: "message"}` | On bad input |

Messages from client to server:

| Type | Payload | Purpose |
|---|---|---|
| `refresh` | — | Request immediate snapshot |
| `ping` | — | Keep-alive |
| `guide` | `{node_id, command, data?}` | Send `@enact` command to a coglet |
| `set_status` | `{node_id, status}` | Change node status (running/stopped/error) |

### Data Model

`CogWebSnapshot.to_dict()` returns:

```json
{
  "nodes": {
    "MyClass_7f1234abcdef": {
      "node_id": "MyClass_7f1234abcdef",
      "class_name": "MyClass",
      "mixins": ["LifeLet", "TickLet", "WebLet"],
      "channels": {"result": 2, "log": 1},
      "listen_channels": ["obs", "config"],
      "enact_commands": ["reload", "cogweb_status"],
      "children": ["Worker_7f5678..."],
      "parent_id": null,
      "config": {"restart": "on_error", "max_restarts": 3, "backoff_s": 1.0},
      "status": "running",
      "updated_at": 12345.678
    }
  },
  "edges": [
    {"from": "MyClass_7f1234...", "to": "Worker_7f5678...", "channel": "child", "kind": "control"}
  ]
}
```

### Enabling CogWeb on Your Coglets

```python
from coglet import Coglet, CogletConfig, CogletRuntime, LifeLet
from coglet.weblet import CogWebRegistry, WebLet
from cogweb.ui import CogWebUI

class MyNode(Coglet, WebLet, LifeLet):
    async def on_start(self):
        await self.create(CogletConfig(cls=Worker, kwargs={"cogweb": self._cogweb}))

class Worker(Coglet, WebLet, LifeLet):
    pass

# Boot
registry = CogWebRegistry()
runtime = CogletRuntime()
await runtime.spawn(CogletConfig(cls=MyNode, kwargs={"cogweb": registry}))

# Start UI
ui = CogWebUI(registry, port=8787)
await ui.start()   # non-blocking
```

Key points:
- Pass the **same** `CogWebRegistry` instance to all coglets via `kwargs={"cogweb": registry}`
- Children inherit the registry if you forward `self._cogweb` in `create()` kwargs
- `WebLet` is inert if `cogweb=None` — coglets run normally without visualization

### Frontend Development

```bash
cd src/cogweb/ui/app
npm install
npm run dev         # Vite dev server with hot reload (proxies /api + /ws to :8787)
npm run build       # Production build -> ../static/dist/
```

The Vite dev server (`npm run dev`) proxies API and WebSocket requests to
`localhost:8787`, so run the Python server in parallel during development.

### Key Files for Agents

When modifying CogWeb:
- **Server logic**: `src/cogweb/ui/server.py` — add new WS message types here
- **CLI**: `src/cogweb/cli.py` — add new subcommands here
- **Node rendering**: `src/cogweb/ui/app/src/CogletNode.tsx` — modify node appearance
- **Inspector panel**: `src/cogweb/ui/app/src/Inspector.tsx` — add control actions
- **Wire types**: `src/cogweb/ui/app/src/types.ts` — must match Python `CogWebSnapshot`
- **Data model**: `src/coglet/weblet.py` — `CogWebNode`, `CogWebSnapshot`, `CogWebRegistry`
- **Tests**: `tests/test_cogweb_ui.py` (server), `tests/test_cogweb_cli.py` (CLI)

After changing TypeScript, rebuild with `cd src/cogweb/ui/app && npm run build`.

## Testing

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

220+ tests, organized by component:
- `test_channel.py` — Channel, ChannelSubscription, ChannelBus
- `test_coglet.py` — Coglet base, decorators, dispatch, COG interface
- `test_handle.py` — Command, CogletConfig, CogletHandle
- `test_runtime.py` — spawn, shutdown, tree, trace, restart
- `test_mixins.py` — LifeLet, TickLet, ProgLet, GitLet, LogLet, MulLet
- `test_improvements.py` — SuppressLet, tree, trace, ticker errors, restart, on_child_error
- `test_integration.py` — multi-layer hierarchies, cross-mixin interactions
- `test_weblet.py` — CogWebRegistry, CogWebSnapshot, WebLet mixin
- `test_cogweb_ui.py` — REST API, WebSocket, guide commands, status changes
- `test_cogweb_cli.py` — CLI argument parsing, PID management

## Key Patterns

**Subscribe before transmit**: Channel subscribers must exist before `transmit()` is
called. There is no replay buffer. In tests, create subscriptions before triggering
actions that transmit.

**MRO matters**: when mixing SuppressLet with Coglet, SuppressLet must come first
so its `transmit()` override intercepts before Coglet's.

**Fire-and-forget**: `guide()` has no return value. The COG learns only by observing
subsequent transmissions from the child.

**Recursive protocol**: the same COG/LET protocol works at every level. A 3-level
tree (Root -> Mid -> Leaf) uses the exact same create/observe/guide/listen/enact/transmit
primitives throughout.

**CogWeb registry forwarding**: when creating children that should appear in CogWeb,
forward `self._cogweb` in the kwargs: `CogletConfig(cls=Child, kwargs={"cogweb": self._cogweb})`.
