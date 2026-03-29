# Coglet

Fractal asynchronous control for distributed agent systems.

## What is Coglet?

Coglet is a framework built on two primitives:

- **COG** (Create, Observe, Guide) — slow, reflective supervisor
- **LET** (Listen, Enact, Transmit) — fast, reactive executor

Every Coglet is both: a LET under its parent COG, and a COG over its children. This forms a recursive temporal hierarchy where layers share a uniform interface and differ only in cadence and scope.

## Project Structure

```
src/coglet/          # Framework
  coglet.py          # Base class + @listen/@enact/transmit decorators
  channel.py         # Async pub/sub channel bus
  handle.py          # CogletHandle, CogletConfig, Command
  runtime.py         # CogletRuntime — boots and manages Coglet trees
  lifelet.py         # LifeLet mixin — on_start/on_stop lifecycle
  ticklet.py         # TickLet mixin — @every periodic scheduling
  codelet.py         # CodeLet mixin — mutable function table
  gitlet.py          # GitLet mixin — repo-as-policy with git patches
  loglet.py          # LogLet mixin — separate log stream
  mullet.py          # MulLet mixin — fan-out N children behind one handle

src/cogweb/          # CogWeb graph visualizer
  cli.py             # cogweb CLI (start/stop/restart/ui/build)
  ui/
    server.py        # Starlette server (REST + WebSocket)
    app/             # React Flow frontend (Vite + TypeScript)
    static/          # Legacy index.html + built assets (dist/)

cogames/             # CvC (Cogs vs Clips) game player
  cvc/
    cvc_policy.py    # PolicyCoglet: LLM brain + Python heuristic
    policy/
      anthropic_pilot.py  # CogletAgentPolicy — optimized per-agent heuristic
      semantic_cog.py     # Base semantic policy from cogora (~1300 lines)
      helpers/            # Geometry, resources, targeting, types
  coach.py           # Coach: orchestrates games, maintains changelog
  player.py          # PlayerCoglet: GitLet COG over PolicyCoglets
  gamelet.py         # GameLet: bridge to cogames CLI
  setup_policy.py    # Tournament sandbox setup (installs anthropic SDK)

docs/                # Architecture design docs
  coglet.md          # COG/LET primitives, communication model, mixins
  tournament.md      # Tournament system hierarchy and pseudocode
```

## Quick Start

### Framework

```python
from coglet.coglet import Coglet, listen, enact
from coglet.lifelet import LifeLet
from coglet.ticklet import TickLet, every

class MyCoglet(Coglet, LifeLet, TickLet):
    async def on_start(self):
        print("started")

    @listen("obs")
    async def handle_obs(self, data):
        await self.transmit("action", self.decide(data))

    @enact("reload")
    async def reload(self, config):
        self.load(config)

    @every(10, "s")
    async def heartbeat(self):
        await self.transmit("status", "alive")
```

### Play a CvC Game

```bash
cogames play -m machina_1 -p class=cvc.cvc_policy.CogletPolicy -c 8 --seed 42
```

### Upload to Tournament

```bash
cogames upload -p class=cvc.cvc_policy.CogletPolicy -n coglet-v0 \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py --season beta-cvc
```

## CogWeb — Graph Visualizer

CogWeb is a browser-based graph visualizer for live coglet supervision trees. It provides a Visio-style node editor built on [React Flow](https://reactflow.dev/) with real-time WebSocket updates.

### Quick Start

```bash
cogweb start              # auto-builds frontend, starts server on :8787
cogweb start --port 9000  # custom port
cogweb stop               # stop the server
cogweb restart             # rebuild + restart
cogweb ui                 # open browser (auto-starts if needed)
```

Or use directly from Python:

```python
from coglet.weblet import CogWebRegistry
from cogweb.ui import CogWebUI

registry = CogWebRegistry()
ui = CogWebUI(registry, host="0.0.0.0", port=8787)
await ui.start()
```

### Features

- **Visio-style nodes** — cards with typed ports: blue for `@listen`, red for `@enact`, green for `transmit`
- **Live updates** — WebSocket pushes graph snapshots every 500ms; React diffs
- **Inspector panel** — click a node to see mixins, handlers, channels, children, config
- **Guide commands** — send `@enact` commands to any coglet directly from the UI
- **Hierarchical layout** — auto-arranges supervision tree; drag to override
- **Snap-to-grid, minimap, zoom controls, dark theme**

### How It Works

1. Coglets mix in `WebLet` and pass a shared `CogWebRegistry`
2. `WebLet.on_start()` registers the coglet; `on_stop()` deregisters it
3. `CogWebRegistry.snapshot()` builds a `CogWebSnapshot` from live state
4. `CogWebUI` (Starlette server) serves the React Flow frontend and pushes snapshots via WebSocket
5. The browser renders the graph, and can send `guide` commands back through the WebSocket

### WebSocket Protocol

| Direction | Message | Purpose |
|---|---|---|
| Server -> Client | `{"type": "snapshot", "data": {...}}` | Full graph state |
| Client -> Server | `{"type": "refresh"}` | Request fresh snapshot |
| Client -> Server | `{"type": "guide", "node_id": "...", "command": "...", "data": ...}` | Send command to coglet |
| Client -> Server | `{"type": "set_status", "node_id": "...", "status": "error"}` | Change node status |
| Client -> Server | `{"type": "ping"}` | Keep-alive |

## Architecture

See [docs/coglet.md](docs/coglet.md) for the full architecture design.

### LET Interface

| Decorator | Plane | Purpose |
|---|---|---|
| `@listen(channel)` | Data | Handle messages from a named channel |
| `@enact(command_type)` | Control | Handle commands from supervising COG |
| `transmit(channel, data)` | Output | Push results outbound |

### COG Interface

| Method | Purpose |
|---|---|
| `create(config)` | Spawn a child Coglet |
| `observe(handle, channel)` | Subscribe to a child's transmit stream |
| `guide(handle, command)` | Send a command to a child (fire-and-forget) |

### Mixins

| Mixin | Purpose |
|---|---|
| **LifeLet** | `on_start()` / `on_stop()` lifecycle hooks |
| **TickLet** | `@every(interval, unit)` periodic scheduling |
| **CodeLet** | `self.functions: dict[str, Callable]` — mutable at runtime |
| **GitLet** | Repo-as-policy — patches applied as git commits |
| **LogLet** | Separate log stream from transmit stream |
| **MulLet** | Fan-out N identical children with map/reduce |

## CvC Player Stack

```
Coach (Claude Code session — NOT a Coglet)
  ├── Runs games via cogames CLI
  ├── Reads learnings from PolicyCoglet
  ├── Maintains changelog (coach_log.jsonl)
  └── Commits improvements to repo

PlayerCoglet (GitLet COG)
  └── Manages PolicyCoglets across games
      └── Reads learnings, accumulates experience

PolicyCoglet (CogletPolicy)
  ├── Python heuristic (CogletAgentPolicy) — handles every step
  ├── LLM brain (Claude) — analyzes ~14x per episode
  └── Writes learnings to disk on episode end
```

### How Scoring Works

CvC runs 10,000 steps per episode with 8 agents per team. Only 5 actions exist: noop + 4 cardinal moves. All interactions happen through movement (walking into extractors, junctions, enemies). Score = aligned junctions held per tick.

The Python heuristic handles fast-path decisions (role assignment, pathfinding, resource gathering, junction alignment). The LLM brain runs every ~500-1000 steps to analyze strategy and log insights. The Coach reads these post-game and commits code improvements.
