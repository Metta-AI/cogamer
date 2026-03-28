# Coglet Implementation Design

## Layout

```
src/coglet/
    coglet.py     # Coglet base, @listen, @enact, transmit, COG methods
    channel.py    # ChannelBus, async channel primitives
    runtime.py    # CogletRuntime — lifecycle, dispatch, scheduling
    handle.py     # CogletHandle, CogletConfig
    lifelet.py    # on_start, on_stop (process lifecycle)
    ticklet.py    # @every decorator
    codelet.py    # mutable function table
    gitlet.py     # repo-as-policy
    loglet.py     # separate log stream
    mullet.py     # fan-out N children with map/reduce

cogames/
    gamelet.py    # GameLet — cogames freeplay + tournament bridge
    player.py     # PlayerCoglet (COG, GitLet)
    policy.py     # PolicyCoglet (CodeLet, MultiAgentPolicy adapter)
    coach.py      # Coach orchestration (not a Coglet)
```

## 1. Framework (`src/coglet/`)

### coglet.py — Base class

`Coglet` is the universal primitive. Decorators register handlers at class definition time via `__init_subclass__`.

- `@listen(channel)` — register a data-plane handler
- `@enact(command_type)` — register a control-plane handler
- `transmit(channel, data)` — push to outbound ChannelBus

COG methods (available on all Coglets, used when supervising children):
- `create(config) -> CogletHandle` — spawn child coglet
- `observe(handle, channel) -> AsyncIterator` — subscribe to child's transmit stream
- `guide(handle, command)` — fire-and-forget command to child's @enact

### channel.py — Async channel primitives

`ChannelBus` — per-Coglet outbound channel registry. `transmit(channel, data)` pushes to the named channel's queue. Subscribers (parent COG via `observe`) get an `AsyncIterator`.

Backed by `asyncio.Queue`. Bounded optional (default unbounded).

### handle.py — CogletHandle, CogletConfig

`CogletConfig` — dataclass describing how to instantiate a Coglet (class, kwargs, capabilities).

`CogletHandle` — opaque reference to a running child. Used by parent COG for `observe` and `guide`. Contains the child's ChannelBus reference and command intake.

### runtime.py — CogletRuntime

Boots and manages a Coglet tree on asyncio.

- `run(config) -> CogletHandle` — instantiate, wire channels, call on_start, schedule ticks
- `shutdown()` — on_stop in reverse order, cancel tasks

### lifelet.py — LifeLet

Mixin. `on_start()` called when process starts. `on_stop()` called on shutdown. Raising aborts the transition.

### ticklet.py — TickLet

Mixin. `@every(interval, unit)` decorator. Time-based units ("s", "m") use asyncio timers. Tick-based ("ticks") requires manual `tick()` calls.

### codelet.py — CodeLet

Mixin. `self.functions: dict[str, Callable]`. Auto-registers `@enact("register")` to update the function table.

### gitlet.py — GitLet

Mixin. `self.repo_path`. Auto-registers `@enact("commit")` to apply patches via subprocess git. Rollback via `git revert`.

### loglet.py — LogLet

Mixin. `self.log(level, data)` pushes to a "log" channel separate from transmit. COG controls verbosity via `guide(handle, Command("log_level", level))`.

### mullet.py — MulLet

Mixin. Fan-out N identical children behind one CogletHandle.

- `create(n, config) -> CogletHandle`
- Abstract `map(event) -> list[(child_id, event)]`
- Abstract `reduce(results) -> result`

## 2. CoGames Integration (`cogames/`)

### gamelet.py — GameLet

Bridge between Coglet world and cogames world. Two modes:

**Play mode**: Runs local episodes. Wraps `cogames play` or direct mettagrid rollout API. Feeds obs/scores/replays into Coglet channels.

**Tournament mode**: Uses `TournamentServerClient` to upload policy bundles, submit to seasons, poll for match results. Exposes `observe("score")`, `observe("replay")`, `observe("leaderboard")`.

### policy.py — PolicyCoglet

`Coglet + CodeLet`. The innermost execution layer.

- `@listen("obs")` → calls `self.functions["step"](obs)` → `transmit("action", action)`
- Implements `MultiAgentPolicy` interface so cogames can instantiate it directly
- LLM rewrites functions via `@enact("register")`

### player.py — PlayerCoglet

`Coglet + GitLet`. COG over PolicyCoglet.

- `observe(policy, "action")` to watch behavior
- `@listen("score")`, `@listen("replay")` to accumulate history
- `@every(N, "m")` triggers LLM to generate patches from history
- `guide(policy, Command("commit", patch))` to improve policy
- `@enact("patch")` allows Coach to direct improvements

### coach.py — Coach

Not a Coglet. A script/prompt that:
1. Creates PlayerCoglet
2. Registers it via GameLet (playground or tournament)
3. Observes scores/replays
4. Analyzes performance
5. Calls `player.enact(patch)` to improve
6. Repeats

## 3. Implementation Order

1. coglet.py + channel.py + handle.py (core primitives)
2. runtime.py + lifelet.py (boot and lifecycle)
3. ticklet.py + codelet.py (needed by player)
4. mullet.py (needed by gamelet for parallel episodes)
5. loglet.py + gitlet.py (player mixins)
6. cogames/policy.py (PolicyCoglet + MultiAgentPolicy adapter)
7. cogames/gamelet.py (cogames bridge)
8. cogames/player.py (PlayerCoglet)
9. cogames/coach.py (orchestration)
