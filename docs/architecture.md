# Architecture

CvCPolicy is a **ProgLet** — a unified program table with two executor types:

```
CvCPolicy (MultiAgentPolicy)
  └── per-agent CvCPolicyImpl
       └── GameState (wraps CvcEngine)
       └── Program table (programs.py):
            ├── 31 code programs — fast Python functions (decision tree, pathfinding, roles)
            └── 1 LLM program ("analyze") — slow Claude call for strategic analysis
```

**Two speeds, one table.** The fast path (code programs) runs every tick: `desired_role()` → `step()` → role actions. The slow path (LLM program) runs every ~500 steps: `analyze` reviews game state and adjusts `resource_bias`. Both are entries in the same program dict, both are evolvable.

**The coach can improve both:**
- **Code programs** in `programs.py` — modify the Python functions (decision logic, scoring, thresholds)
- **LLM prompts** in `programs.py` — modify `_build_analysis_prompt()` and `_parse_analysis()` to change what the LLM sees and how its output is interpreted
- **Engine internals** in `agent/` — modify the underlying A*, targeting, pressure logic that programs delegate to

**The LLM can update programs during an episode** — the `analyze` program's output (currently just `resource_bias`) feeds back into GameState, influencing miner target selection in real-time. This is the coglet ProgLet pattern: programs observe, LLM reflects, programs adapt.

**Agents are fully independent. NO shared state between agents.** Each gets its own GameState, WorldModel, program table instance. They may run in separate processes against different opponents. Never use shared dicts, sets, or lists.

## Program Table (`programs.py`)

31 code programs + 1 LLM program, all evolvable by PCO:

| Category | Programs | What they do |
|----------|----------|-------------|
| **Query** | `hp`, `step_num`, `position`, `inventory`, `resource_bias`, `team_resources`, `resource_priority`, `nearest_hub`, `nearest_extractor`, `known_junctions`, `safe_distance`, `has_role_gear`, `team_can_afford_gear`, `needs_emergency_mining`, `is_stalled`, `is_oscillating` | Read-only state from GameState |
| **Action** | `action`, `move_to`, `hold`, `explore`, `unstick` | Movement via A* pathfinding |
| **Decision** | `desired_role`, `should_retreat`, `retreat`, `mine`, `align`, `scramble`, `step`, `summarize` | Compose queries + actions |
| **LLM** | `analyze` | Claude Sonnet reviews game state every ~500 steps, returns `resource_bias` + `analysis` |

## Decision Flow (per tick, per agent)

1. `process_obs()` → build MettagridState, update world model + junction memory
2. `desired_role()` program → pressure-based role allocation (miner/aligner/scrambler)
3. `step()` program → delegates to `engine._choose_action()`:
   hub_camp_heal → early_survival → wipeout_recovery → retreat → unstick → emergency_mine → acquire_gear → **role_action** → explore
4. `finalize_step()` → record navigation observation
5. Every ~500 steps: `analyze` LLM program → update `resource_bias`
6. Every ~500 steps: `summarize` program → collect experience snapshot for PCO

## Key Files

**Program table + policy** (`src/cogamer/cvc/`):
- `programs.py` — **the 32 programs** (code functions + LLM prompt/parser). Primary evolvable surface
- `cvc_policy.py` — CvCPolicy (MultiAgentPolicy), CvCPolicyImpl (per-agent dispatch), LLM executor, experience collection
- `game_state.py` — GameState adapter wrapping CvcEngine for program table access

**Engine** (`src/cogamer/cvc/agent/`) — infrastructure that programs delegate to:
- `main.py` — CvcEngine: main decision tree (`_choose_action`)
- `roles.py` — role actions (miner, aligner, scrambler)
- `navigation.py` — A* pathfinding, explore patterns, unstick
- `targeting.py` — target selection, claims, sticky targets
- `pressure.py` — role budgets, retreat thresholds
- `junctions.py` — junction memory, depot lookup
- `helpers/targeting.py` — scoring functions (aligner_target_score, scramble_target_score)
- `helpers/types.py` — constants, KnownEntity
- `helpers/resources.py` — resource/inventory queries

**PCO** (`src/cogamer/cvc/`) — the optimization loop:
- `pco_runner.py` — `run_pco_epoch()` orchestrator
- `learner.py` — CvCLearner (LLM proposes program patches)
- `critic.py` — CvCCritic (evaluates experience)
- `losses.py` — ResourceLoss, JunctionLoss, SurvivalLoss
- `constraints.py` — SyntaxConstraint, SafetyConstraint

## PCO (Program Conditioned Optimization)

PCO evolves the program table between episodes. The CvCLearner sees all 32 program source codes + game experience, and proposes patches as `{"program_name": {"type": "code", "source": "def ..."}}`. Patches are validated by SyntaxConstraint + SafetyConstraint before acceptance.

```python
import asyncio, json, glob, anthropic
from cvc.pco_runner import run_pco_epoch
from cvc.programs import all_programs

f = glob.glob('/tmp/coglet_learnings/*.json')[0]
experience = json.load(open(f))['snapshots']

result = asyncio.run(run_pco_epoch(
    experience=experience,
    programs=all_programs(),
    client=anthropic.Anthropic(),
    max_retries=2,
))
# result = {"accepted": bool, "signals": [...], "patch": {...}}
```

Valid GameState API for patches: `gs.hp`, `gs.position`, `gs.step_index`, `gs.role`, `gs.nearest_hub()`, `gs.known_junctions(pred)`, `gs.should_retreat()`, `gs.choose_action(role)`, `gs.miner_action()`, `gs.aligner_action()`, `gs.scrambler_action()`, `gs.move_to_known(entity)`, `gs.explore(role)`, `gs.has_role_gear(role)`, `gs.needs_emergency_mining()`, `gs.team_id()`

## Reference: alpha.0 (tournament rival)

The alpha.0 agent lives at `metta-ai/cogora` (`src/cvc/cogent/player_cog/policy/`). Key differences from our agent:

- **`RETREAT_MARGIN = 20`** (we use 15) — more conservative survival
- **Hotspot tracking**: Tracks scramble history per junction via `_shared_hotspots` counters. Aligners deprioritize junctions with high scramble counts (weight 8.0). We don't track scramble history at all
- **`_DEFAULT_NETWORK_WEIGHT = 0.5`** — small bonus for junctions near friendly network
- **Enemy AOE radius 20** for retreat detection (we use `JUNCTION_AOE_RANGE = 10`)
- **Cyborg architecture**: LLM reviews runtime telemetry and adjusts strategy directives. Detects stagnation (oscillation, target fixation, resource bias mismatch) and rewrites policy to break out
- Same pressure budget phases, same constants in helpers/types.py, same heart batching targets
