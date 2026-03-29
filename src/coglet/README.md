# coglet framework

Fractal asynchronous control for distributed agent systems.

## Primitives

- **Coglet** (`coglet.py`) — base class. Every coglet is both a COG (supervisor) and a LET (executor).
- **@listen(channel)** — data plane: receive from named channels
- **@enact(command)** — control plane: receive commands from supervising COG
- **transmit(channel, data)** — push output
- **create(config)** — spawn a child coglet
- **observe(handle, channel)** — subscribe to a child's output
- **guide(handle, command)** — send command to a child

## Core

| File | Purpose |
|---|---|
| `coglet.py` | Base class, @listen/@enact decorators, handler discovery via MRO |
| `handle.py` | CogletHandle (opaque child ref), CogletConfig, Command |
| `channel.py` | Async pub/sub channels (ChannelBus, per-subscriber queues) |
| `runtime.py` | CogletRuntime: spawn, shutdown, restart, tree visualization, tracing |

## Mixins

| Mixin | File | Purpose |
|---|---|---|
| LifeLet | `lifelet.py` | on_start/on_stop lifecycle hooks |
| TickLet | `ticklet.py` | @every(interval, unit) periodic execution |
| CodeLet | `codelet.py` | Mutable function table, hot-swap via enact("register") |
| GitLet | `gitlet.py` | Repo-as-policy, patches as commits |
| LogLet | `loglet.py` | Separate log stream from transmit |
| MulLet | `mullet.py` | Fan-out N identical children with map/reduce |
| SuppressLet | `suppresslet.py` | Gate channels/commands on/off |

## Subpackages

- [`pco/`](pco/) — Proximal Coglet Optimizer (PPO as a coglet graph)
