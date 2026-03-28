# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Related Repos

- **metta-ai/cogos** — CogOS operating system
- **metta-ai/cogora** — Cogora platform

## Project Status

This repo is in early design phase — no source code yet, only architecture docs in `docs/`.

## Architecture

Coglet is a framework for fractal asynchronous control of distributed agent systems, built on two primitives:

- **COG** (Create, Observe, Guide) — slow, reflective supervisor that spawns and manages LETs
- **LET** (Listen, Enact, Transmit) — fast, reactive executor that handles events

A Coglet is both: every COG is itself a LET under a higher COG, forming a recursive temporal hierarchy. The COG/LET boundary is a protocol contract, not a deployment boundary.

### Communication Model

- **Data plane**: `@on_message(channel)` — receive data from named channels
- **Control plane**: `@on_enact(command_type)` — receive commands from supervising COG
- **Output**: `transmit(channel, result)` — push results outbound
- **Supervision**: `observe(let_id, channel)`, `guide(let_id, command)`, `create(config)`
- All communication is async, location-agnostic, fire-and-forget (guide has no return value; observe is the only feedback path)

### Mixins

Optional capabilities any Coglet can compose: LifeLet (lifecycle hooks), GitLet (repo-as-policy with git patches), LogLet (separate log stream), TickLet (`@every` decorator for periodic behavior), CodeLet (mutable function table), MulLet (fan-out N identical LETs behind one handle with map/reduce).

### Tournament System (`docs/tournament.md`)

Two independent hierarchies meeting at an interface boundary:

**User side**: Coach (Claude Code prompt) → PlayerCoglet (GitLet) → PolicyCoglet (CodeLet)

**Softmax side**: TournamentCoglet → MulLet(GameCoglets) → EpisodeCoglet → EnvCoglet + MulLet(players)

Key design points:
- Tournament and PlayGround share the same `register(policy_config) → CogletHandle` interface
- Round boundary is the sync point — Coach improves policy between rounds
- Games within a round run in parallel via MulLet
- Trust boundary: Softmax owns infrastructure; user policies run sandboxed inside it
