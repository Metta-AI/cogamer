# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Related Repos

- **metta-ai/cogos** — CogOS operating system
- **metta-ai/cogora** — Cogora platform

## Project Structure

```
src/cogamer/    # CoGamer: self-improving agent for CoGames (Improve, Player, Policy)
src/coglet/     # Framework: Coglet base class + mixins
src/cogweb/     # CogWeb: graph visualization UI (FastAPI + WebSocket + SVG)
tests/          # 200 unit + integration tests (pytest + pytest-asyncio)
docs/           # Architecture design docs
```

See [AGENTS.md](AGENTS.md) for detailed component reference and patterns.

## Architecture

Coglet is a framework for fractal asynchronous control of distributed agent systems, built on two primitives:

- **COG** (Create, Observe, Guide) — slow, reflective supervisor that spawns and manages LETs
- **LET** (Listen, Enact, Transmit) — fast, reactive executor that handles events

A Coglet is both: every COG is itself a LET under a higher COG, forming a recursive temporal hierarchy. The COG/LET boundary is a protocol contract, not a deployment boundary.

### Communication Model

- **Data plane**: `@listen(channel)` — receive data from named channels
- **Control plane**: `@enact(command_type)` — receive commands from supervising COG
- **Output**: `transmit(channel, data)` — push results outbound
- **Supervision**: `observe(handle, channel)`, `guide(handle, command)`, `create(base)`
- All communication is async, location-agnostic, fire-and-forget

### Mixins

LifeLet (lifecycle hooks), GitLet (repo-as-policy), LogLet (log stream), TickLet (`@every` periodic), ProgLet (unified program table with pluggable executors), MulLet (fan-out N children), SuppressLet (output gating), WebLet (CogWeb UI registration).

### Runtime Features

- `CogletRuntime.tree()` — ASCII visualization of the live supervision tree
- `CogletTrace` — jsonl event recording for post-mortem debugging
- Restart policy — `CogBase(restart="on_error", max_restarts=3, backoff_s=1.0)`
- `Coglet.on_child_error()` — parent decides restart/stop/escalate on child failure
- `TickLet.on_ticker_error()` — overridable hook for ticker exceptions

### CvC Player Stack

Improve (Claude Code) → PlayerCoglet (GitLet) → PolicyCoglet (ProgLet + LLM brain)

### Key Commands

```bash
# Run tests
PYTHONPATH=src/cogamer python -m pytest tests/ -v
```

See [IMPROVE.md](IMPROVE.md) for CvC agent coaching guide index.

### Docs

- [AGENTS.md](AGENTS.md) — Component reference for AI agents working with this codebase
- [README.md](README.md) — Project overview and quickstart
- [docs/rules.md](docs/rules.md) — Game rules, constants, team coordination
- [docs/architecture.md](docs/architecture.md) — Policy architecture, program table, PCO, alpha.0 reference
- [docs/strategy.md](docs/strategy.md) — What works, what to try, dead ends, learnings
- [docs/cogames.md](docs/cogames.md) — CLI setup, running, uploading, monitoring
- [docs/tools.md](docs/tools.md) — Development rules & constraints
