# CvC Engine Mechanics

Ground-truth mechanics from the mettagrid engine. The policy code is heuristics on top of these — this is what actually happens.

## Actions

The engine has only 4 actions: `noop`, `move`, `attack`, `change_vibe`.

There are no "align" or "scramble" actions. Alignment and scrambling are **handler-based mutations** triggered by the `move` action when landing on a junction. The handler checks gear and resources, not role or vibe.

## Gear

Gear is acquired at role-specific stations near the hub. Each type has concrete mechanical effects:

| Gear | Cost | Mechanical Effect |
|------|------|-------------------|
| **Miner** | C:1 O:1 G:3 S:1 | 10x extraction yield (10 vs 1 per visit), +40 cargo capacity |
| **Aligner** | C:3 O:1 G:1 S:1 | **Required** to align junctions (hard gate) |
| **Scrambler** | C:1 O:3 G:1 S:1 | **Required** to scramble junctions (hard gate), +200 HP |
| **Scout** | C:1 O:1 G:1 S:3 | +400 HP (500 max vs 100 base), +100 energy. No action-enabling effects. |

**Without aligner gear, you cannot capture junctions. Without scrambler gear, you cannot neutralize them.** These are engine-level hard gates, not policy preferences.

An agent can only hold one type of gear at a time (inventory limit of 1 across all gear items). Different agents on the same team carry different gear — a typical team has a mix of miners, aligners, and scramblers.

## Junctions

Junctions are the only thing that scores. They are static grid objects placed via Poisson distribution at density 0.3 (exact count varies by seed). They have no inventory, HP, or durability — their entire state is ownership tags.

### How Alignment Works

Walk onto a neutral or enemy-owned junction with **aligner gear + 1 heart**:

- The junction must be **within range of your existing network** — either within 15 cells (L2) of a junction you already own, or within 25 cells (L2) of your hub
- If you meet those requirements: 1 heart is consumed, your team's tag is added to the junction
- **You can align enemy-owned junctions directly.** You don't need to scramble first. The junction gets your team's tag while keeping the enemy's. Both teams score from it until someone scrambles. This is the fastest way to start scoring from a contested area (one agent, one step).
- You **cannot** re-align a junction you already own (filter prevents it — the noop `keep` handler fires instead)

### How Scrambling Works

Walk onto a junction owned by another team with **scrambler gear + 1 heart**:

- 1 heart is consumed
- The enemy team's ownership is removed
- If this junction was connecting other enemy junctions to their hub, **all downstream junctions are disconnected and lose ownership too** (cascade disconnection)

Scrambling doesn't give you the junction — it just takes it from the enemy. To own it yourself, an aligner must follow up and align it (or you align it directly in the first place).

### Handler Priority

When an agent walks onto a junction, handlers fire in **first-match order**: scramble handlers are checked before align handlers. Since each agent holds only one gear type, what happens depends on which gear that agent has:

- **Agent with aligner gear on enemy junction**: scramble filter fails (agent lacks scrambler gear) → align fires → **dual ownership** (both teams score)
- **Agent with scrambler gear on enemy junction**: scramble fires (first match) → **enemy ownership removed**, align never checked (agent lacks aligner gear anyway)
- **Agent with aligner gear on neutral junction**: scramble filter fails (junction has no team tag) → align fires → **you own it**
- **Agent with no gear**: all filters fail → nothing happens

### Shared Ownership

Tags are **boolean** (bitset), not scalar. A junction either has `team:X` or it doesn't — there's no stacking. But multiple different teams can each have their tag set simultaneously. In a 4-team game, a junction could score for all 4 teams at once.

**One scramble removes one team's ownership (1 heart).** Scramble handlers are per-team and fire first-match. If a junction has 3 enemy teams on it, you need 3 separate scramble steps (3 hearts) to clear all of them. Which enemy gets removed first is determined by **team definition order in the mission config** — handlers are registered per-team in Python dict insertion order, so the first-defined team's scramble handler is always checked first. This is a fixed priority (like port priority), not random or temporal.

This means **aligners and scramblers serve fundamentally different purposes**:
- **Aligners add your scoring** — walk onto any junction (neutral or enemy) near your network
- **Scramblers remove enemy scoring** — and can cascade-disconnect entire branches

An aligner-only strategy lets you score but never reduces enemy score. A scrambler denying a bridge junction can wipe an entire enemy branch in one step.

### The Network

Your junctions only score if they're **connected to your hub through a chain of friendly junctions**. The engine computes this as a BFS (breadth-first search) from your hub:

1. Start at hub
2. Find all your junctions within 25 cells (L2 distance)
3. From each of those, find more of your junctions within 25 cells
4. Continue until no more are reachable
5. Only connected junctions get the network tag that scores

If a junction in the middle of a chain is scrambled, everything beyond it loses network connectivity and **stops scoring immediately**. The ownership tags are also removed via cascade.

**Distance is L2 (Euclidean), not Manhattan.** `dr² + dc² ≤ radius²`. At radius 15: a junction 10 north and 10 east (L2 ~14.1) IS reachable, but 11 north and 11 east (L2 ~15.6) is NOT. The policy code uses Manhattan distance for approximation, which can overestimate what's actually in range.

**Alignment range vs network range**: you can only align a junction within 15 cells (L2) of an existing network junction, or 25 cells of your hub. The network BFS uses 25 cells for all edges. So a junction can be in your network but too far from its neighbors for a NEW junction to be aligned between them.

### Strategic Implications

- **Chain-building matters**: expand outward from hub or existing frontier. An isolated alignment wastes a heart if you can't connect it.
- **Bridge junctions are the highest-value scramble targets**: one scramble can cascade-disconnect an entire branch. Identify which of your junctions are bridges and defend them.
- **Hub proximity is king**: close junctions are easier to connect, cheaper to defend, and harder for enemies to isolate.
- **Dual ownership is a real tactic**: an aligner can start scoring from an enemy junction in one step. Whether to align (start scoring, enemy keeps scoring) or scramble first (deny enemy, need two agents for full capture) is a real decision.
- **Contested junctions drain hearts**: each align/scramble costs 1 heart (crafted for 28 resources total). A junction flipping repeatedly is a resource sink — consider whether it's worth contesting or better to expand elsewhere.
- **L2 distance creates gaps**: diagonal chains are unreliable. Linear chains along corridors are safer than diagonal leaps across open space.

## Mining / Extraction

Extractors are **finite** — each starts with 200 resources and is removed from the grid when depleted. No regeneration.

- **Without miner gear**: `withdraw` 1 resource per visit (200 visits to deplete)
- **With miner gear**: `withdraw` 10 resources per visit (20 visits to deplete)

Any agent can mine. Miner gear also grants +40 cargo capacity (carry more before depositing at hub).

Extractors are placed via Poisson distribution at density 0.3, one type per element (carbon, oxygen, germanium, silicon). Since they're finite, depleting an extractor near enemy territory permanently denies that resource — a viable denial strategy.

## HP, Energy, and Combat

HP and energy are both plain inventory resources — there is no special HP or energy "system" in the engine.

**HP:**
- Depleted by combat (attack handler), AOE effects, and passive drain (`regen: -1` per tick)
- At HP=0, the agent is NOT removed from the grid — it stays and can still move. But the `hp_death` on_tick handler fires every tick while HP < 1, executing `ClearInventoryMutation` on configured inventory groups.
- **On death (HP=0), gear and hearts are destroyed.** In standard CvC: `destroy_items = ["gear", "heart"]`. This wipes all gear (aligner, scrambler, miner, scout) and all hearts from inventory. Since align requires `aligner=1` and scramble requires `scrambler=1`, **HP=0 effectively hard-gates all role-specific actions** until the agent returns to hub, heals, and re-equips.
- This is configurable per-mission via `DamageVariant.destroy_items`, `GearVariant.destroy_gear_on_death`, and `HeartVariant`. Standard missions use defaults (destroy both).
- Max HP comes from inventory limits (base 100), modified by gear (scrambler +200, scout +400)
- **Hearts** restore HP and are consumed by align/scramble actions. Crafted at hub for 7 of each element.

**Energy:**
- The `EnergyVariant` configures `consumed_resources = {"energy": 4}` on the move action.
- However, `ActionConfig.consumed_resources` is **defined but never enforced** in the C++ action execution path — no engine code reads the field during action processing. Energy appears to be dead infrastructure.
- Scout gear adds +100 max energy, but if energy isn't enforced, this has no mechanical effect.

**Combat:**
- **Attack**: triggered by `move` onto another agent. Weapon power from attacker's inventory, armor from defender's inventory + vibe bonus.
- **Vibe armor bonus**: if the defender's current vibe matches a defense resource, that resource gets bonus armor value. This is the only mechanical effect vibes have.

## Vibes

Vibes are a state variable on agents: `change_vibe_miner`, `change_vibe_aligner`, `change_vibe_scrambler`, `change_vibe_heart`, `change_vibe_gear`, `change_vibe_default`.

Mechanical effects:
- **Armor bonus** in combat (matching vibe boosts defense resource value)
- **Observable** by other agents in viewport (13×13)
- **Reward shaping** uses vibes to identify specialization

Vibes do NOT determine whether align or scramble fires. Vibes do NOT restrict actions. Vibes do NOT affect mining yield or junction capture.

## Scoring

Per-tick reward per agent:

```
reward = (num_junctions_with_net_tag - 1) / max_steps
```

The `-1` subtracts the hub (which also has the `net:` tag). Score accumulates over all 10,000 steps — a junction held for 5,000 steps contributes half as much as one held for the full game. Only `net:` tagged junctions count; aligned but disconnected junctions score zero. No points for kills, mining, or exploration.

## Observation Model

- **Viewport**: 13×13 cells centered on the agent
- **visible_entities**: all entities in viewport (agents, junctions, extractors, hubs, resources)
- **team_summary.shared_inventory**: authoritative hub resource state (global to team)
- **team_summary.members**: visible teammates only (viewport-local subset)

## Map

- 88×88 grid with walls and corridors
- 1 hub per team (spawn point, resource storage, gear crafting, heart crafting)
- Junctions scattered across map (capturable nodes)
- Extractors for each element type (carbon, oxygen, germanium, silicon)
- 10,000 steps per game, 8 agents per team

## Death (HP=0)

The agent stays on the grid but loses everything useful:

1. `hp_death` handler fires every tick while HP < 1
2. `ClearInventoryMutation` destroys all items in the "gear" limit (aligner, scrambler, miner, scout) and "heart" limit
3. Agent can still `move` and `noop` — it's not frozen
4. To recover: move back to hub, heal (hub has heart crafting), re-acquire gear at role station

**Strategic implication**: death is expensive. You lose gear (6 resources to re-craft) + hearts + all the steps spent traveling back and re-equipping. Miners lose cargo too. Keeping agents alive is almost always better than aggressive play that risks HP=0.

## Scout Viability

Scout gear grants +400 HP (500 max vs 100 base) — 5x the base, more than scrambler's 300 max. Energy +100 is likely irrelevant (see energy note above). Scout unlocks no actions: can't align, can't scramble, mines at 1x.

What scouts *can* do: survive. A scout takes 5x the punishment before dying and losing gear. Possible niches:
- **Blockers**: park on a contested junction or chokepoint, absorb attacks, buy time for aligners
- **Deep explorers**: map distant regions without retreating to hub for healing
- **Bait/tank**: draw enemy scramblers into wasting attacks on a high-HP target

The tradeoff is opportunity cost — that gear slot and 6 resources could have been a miner (10x extraction), aligner (junction capture), or scrambler (junction denial + 200 HP). Scout needs a strategy that specifically exploits raw HP to justify the slot.
