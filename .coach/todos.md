# Coach TODO

## Current Priorities
- [ ] Fix 0.00 score catastrophic failures (2 out of 20 freeplay matches)
- [ ] Close the freeplay gap: beta 1.69 vs alpha.0 15.05
- [ ] Improve junction retention: friendly count drops from 10→1 after step 1500

## Improvement Ideas
- [ ] Investigate 0.00 score games — what causes total failure?
- [ ] Dynamic explore radius — expand search as network grows
- [ ] Better aligner cycling — reduce dead time between heart acquisition and junction capture
- [ ] Study alpha.0 match artifacts for strategy insights
- [ ] PCO evolution — run PCO epochs to evolve program table
- [ ] Network repair priority — when a chain junction is lost, prioritize recapturing it

## Dead Ends (Don't Retry)
- [x] Teammate-aware role adaptation — all agents see same state, causes thrashing in self-play
- [x] Economy-aware pressure budgets — no improvement over simple budgets
- [x] Retreat threshold tuning — always trades deaths for score regression
- [x] Heart batch target changes — 3 for aligners is the sweet spot
- [x] Outer explore ring at manhattan 35 — sends agents too far, they die
- [x] Remove alignment network filter — required by game mechanics
- [x] Expand alignment range +5 — causes targeting unreachable junctions
- [x] Remove scramblers entirely (SCRIMMAGE only) — confirmed twice in self-play, scramblers help
- [x] Resource-aware pressure budgets — too aggressive scaling
- [x] Spread miner resource bias — least-available targeting is better
- [x] Reorder aligner explore offsets — existing order works better
- [x] Increase claim penalty (12→25) — pushes aligners to suboptimal targets
- [x] More aligners (6) / fewer miners (2) — economy can't sustain
- [x] Wider A* margin (12→20) — slower computation wastes ticks
- [x] Emergency mining threshold 50 or 10 — hurts high-scoring seeds more than helps low ones

## Done
- [x] (ID) Hotspot decay + cap — prevent front-line avoidance spiral (session 37)
- [x] (ID) Hotspot tracking for junction scramble history (weight 8.0, matches alpha.0)
- [x] (ID) Improved scrambler budget: start at step 100, 2 scramblers after step 1000 (2.7x improvement)
- [x] Submitted beta:v33 (tournament), beta:v32 (freeplay)
- [x] Tournament season complete — beta:v7 is #1

## Testing Notes
- **ALWAYS test 5+ seeds** (42–46) and average
- Self-play (`-c 8`) has high variance — scores 0.00 to 8.66
- 1v1 (`-p A -p B`) gives more realistic scores
- Freeplay scores settle after 20 matches
