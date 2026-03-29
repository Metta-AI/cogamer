# Coach TODO

## Current Priorities
- [ ] Check tournament results for coglet-v0:v12 (and v11)
- [ ] If tournament scores are low, consider reverting 2-scrambler change

## Improvement Ideas
- [ ] Tune scrambler vs aligner ratio further (try 2 aligners + 3 scramblers)
- [ ] Make pressure budgets resource-aware (reduce when resources critically low)
- [ ] Reduce late-game heart batch targets (currently escalates to 6, try capping at 4)
- [ ] Investigate high death count (~6-8 per agent) — improve retreat timing
- [ ] Try adaptive scrambler count based on enemy junction presence
- [ ] Optimize aligner target scoring — current hub_penalty may be too aggressive
- [ ] Increase A* pathfinding bound margin (12→20) to reduce stuck time
- [ ] Try `pickup` evaluation mode for more realistic testing
- [ ] Explore making early-game ramp-up faster (reduce hub camp heal from 20 to 5 steps)

## Done
- [x] Establish baseline scores (avg 1.84 local, 3-episode seed 42)
- [x] Double scrambler allocation (1→2) — neutral locally (~1.55)
- [x] Adaptive deposit threshold (deposit at 6 when resources low) — 1.82 avg, lower variance
