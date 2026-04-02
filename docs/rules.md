# Game Rules

## Objective

Maximize **per-cog score**. Score = total junctions held per step / max steps. Higher = better.

## Map & Duration

- **Map**: 88×88 grid with walls, ~65 junctions, ~200 extractors
- **Duration**: 10,000 steps, 8 agents per team
- **Scoring**: `score = junctions_held_per_step / max_steps` per cog — holding junctions longer matters more than late captures

## Core Mechanics

- **Junctions**: capturable nodes (neutral → friendly/enemy). Form networks via alignment distance
- **Resources**: carbon, oxygen, germanium, silicon — mined from extractors, deposited at hub, used to craft gear and hearts
- **Hearts**: consumable items for aligning/scrambling. Cost 7 of each element. Obtained at hub
- **Roles**: miner (harvest resources), aligner (capture neutral junctions, costs 1 heart), scrambler (neutralize enemy junctions, costs 1 heart)

## Key Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `JUNCTION_ALIGN_DISTANCE` | 15 | Agent must be within this range to align |
| `HUB_ALIGN_DISTANCE` | 25 | Hub can align junctions within this range |
| `JUNCTION_AOE_RANGE` | 10 | Junctions affect nearby junctions within this |
| `RETREAT_MARGIN` | 15 | Base HP safety margin |
| `DEPOSIT_THRESHOLD` | 12 | Miner deposits cargo at this amount |
| `TARGET_CLAIM_STEPS` | 30 | Junction claim expiry |
| `EXTRACTOR_MEMORY` | 600 | Steps to remember extractor locations |

## Team Coordination

**In tournament, your agents play on a team with agents controlled by OTHER policies.** You must perform well across all team compositions, not just a team of your own clones. The team shares a hub, shared inventory, and junctions — but each agent is controlled by its own independent policy instance.

### What You Can See About Teammates

Via `team_summary` (game-provided, read-only):
- `team_summary.members` — list of visible teammates with `entity_id`, `role` (inferred from gear: miner/aligner/scrambler/unknown), `position`, `status`
- `team_summary.shared_inventory` — hub resources (all team members deposit to the same pool)
- `team_summary.shared_objectives` — any shared objectives set by the game

Via `visible_entities` — any teammate in your 13×13 viewport appears as a `SemanticEntity` with:
- `attributes["role"]` — their current gear role
- `attributes["agent_id"]` — their agent ID
- `labels` — includes "friendly"
- Position, inventory visible on the entity

### Vibe Actions (Signaling)

Each action has an optional **vibe** component — a visual signal visible to any agent in the viewport. Current vibes:
- `change_vibe_miner` — signals "I'm mining"
- `change_vibe_aligner` — signals "I'm aligning"
- `change_vibe_scrambler` — signals "I'm scrambling"
- `change_vibe_heart` — signals "I'm getting hearts"
- `change_vibe_gear` — signals "I'm getting gear"
- `change_vibe_default` — neutral/retreat

Vibes are set as the second component of every action: `Action(name="move_north", vibe="change_vibe_aligner")`. Other agents in range can observe the vibe on the entity in their viewport.

**Currently our agent sets vibes based on current role/action but does NOT read teammate vibes.** This is a key improvement opportunity — reading teammate vibes enables:
- Avoiding duplicate targets (if teammate is heading to same junction)
- Complementary role selection (if 3 teammates are already aligning, switch to mining)
- Coordinated expansion (if teammate is aligning nearby, push further out)
