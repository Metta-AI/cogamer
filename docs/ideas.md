# LLM Knob Ideas

The LLM currently adjusts 3 knobs every ~500 steps: `resource_bias`, `role`, `objective`. These are candidates for additional knobs, grouped by expected impact.

## High Value

### `aggression` (float 0-1)
Controls retreat/survival vs push tradeoff. Maps to:
- Retreat margin base (currently fixed 15 HP)
- Late-game HP bonus (+10/+15)
- In-enemy-AOE penalty (+10)
- Near-enemy-territory penalty (+5)

One knob, four effects. An aggressive LLM lowers all margins; a defensive one raises them. The LLM already sees HP, junction counts, and stall status — enough to judge when to be bold vs cautious.

### `pressure_split` ([aligners, scramblers])
Replace the step-based budget ladder with direct LLM allocation. Currently hardcoded as `(5, 0)` → `(5, 1)` → `(6, 1)` by step thresholds. The LLM sees junction counts (friendly/enemy/neutral) and team resources — it can decide "we need 3 scramblers to break their lead" or "all miners, we're broke."

Subsumes `objective` — `economy_bootstrap` is just `[0, 0]`, `expand` is `[6, 0]`, `defend` is `[3, 3]`.

### `deposit_threshold` (int)
Currently fixed at 12 with gear, 4 without. A high value means fewer hub trips but more risk of losing cargo on death. The LLM can see HP and safe_distance — it could lower the threshold when danger is high or raise it when mining is going well.

## Medium Value

### `heart_batch_target` (int)
Currently 3 for aligners, 2 for scramblers. Controls how long agents camp at hub restocking hearts before pushing out. Raising it means more durability per push but more time idle. The LLM could lower it when junctions are contested and speed matters.

### `target_stickiness` (float)
Currently `3.0` Manhattan distance advantage needed to switch targets. Low = more responsive to new opportunities, high = more committed to current target. Useful when the LLM detects oscillation — it could raise stickiness to stop agents flip-flopping.

### `explore_radius` (float multiplier)
Scale the explore offset distances. Currently fixed per-role (aligner ~22, miner ~40, scrambler ~51). A multiplier < 1.0 keeps agents closer to hub (safe), > 1.0 pushes them further (aggressive scouting). Naturally pairs with `aggression`.

## Lower Priority

### `hotspot_weight`
How much to avoid contested junctions (currently 8.0). Could help if the LLM notices agents keep dying at the same junction.

### `network_bonus`
Weight for chain-building (currently 0.5). Raise to encourage building connected junction networks instead of scattered captures.

### `emergency_threshold`
When to panic-mine (currently min_resource < 1). Could raise to 3 if the LLM sees resources trending down.

## Implementation Priority

Start with `aggression` and `pressure_split`. They cover the biggest strategic decisions (how cautious to be, how to allocate the team) and the LLM already has the context to set them. The prompt change is small — add two fields to the JSON schema, map them to existing constants in `budgets.py`. `deposit_threshold` and `heart_batch_target` are easy follow-ups once the plumbing is in place.
