# Query Match History

See `docs/mechanics.md` for ground-truth engine mechanics (gear effects, action handlers, scoring).

After running a game, per-agent game logs are dumped to `/tmp/coglet_learnings/` as JSONL files:
- `{game_id}_a{agent_id}.jsonl` — one JSON record per game step
- `{game_id}_a{agent_id}_events.jsonl` — junction ownership changes

## CLI Query Tool

```bash
# Summary of a game
python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl summary

# Last 20 records
python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl tail 20

# Filter records matching a condition
python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl filter "r['hp'] < 20"

# Arbitrary Python expression (full power)
python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl eval "len([r for r in records if r['hp'] == 0])"
python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl eval "[(r['step'], r['team_resources']['carbon']) for r in records[::100]]"
python tools/query_game.py /tmp/coglet_learnings/game_123_a0.jsonl eval "len([e for e in events if e['old_owner'] == 'team_1'])"
```

The `eval` command has `records` (list of step dicts) and `events` (junction events) in scope. Write any Python you want.

## Record Fields

Each step record has:
- `step` — game step number
- `position` — `[x, y]`
- `hp` — agent HP
- `inventory` — all inventory items (resources, hearts, gear, hp)
- `team_resources` — `{carbon: N, oxygen: N, germanium: N, silicon: N}`
- `role_counts` — `{miner: N, aligner: N, ...}`
- `enemy_positions` — `[[x, y], ...]` visible enemies that step
- `junction_owners` — `{"x,y": owner, ...}` all known junctions

Junction events have: `step`, `position`, `old_owner`, `new_owner`.

## In-Policy Access

During gameplay, the recorder is on `gs.recorder`. It stores `StepRecord` objects and is iterable:

```python
# Iterate all steps
for record in gs.recorder:
    print(record.step, record.hp, record.team_resources)

# Last 100 steps
for record in gs.recorder.steps(last_n=100):
    ...

# Index/slice
latest = gs.recorder[-1]
total_steps = len(gs.recorder)

# Convenience queries
losses = gs.recorder.junction_losses(team=team, last_n_steps=200, step=gs.step_index)
gains = gs.recorder.junction_gains(team=team, last_n_steps=200, step=gs.step_index)
sightings = gs.recorder.enemy_sightings(near=(x, y), radius=15, last_n=100)
cells = gs.recorder.unique_positions_visited()
```
