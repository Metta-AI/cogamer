# Coach TODO

## Current Priorities
- [ ] Monitor beta:v30 freeplay results and beta:v31 tournament advancement
- [ ] Test with 1v1 mode (`cogames run -c 16`) to validate against real opponents
- [ ] Investigate removing scramblers for cooperative scoring (both teams' scramblers reduce total junctions)

## Improvement Ideas
- [ ] Read teammate vibes for more nuanced coordination (beyond position-based)
- [ ] Map topology analysis — understand wall patterns to improve exploration
- [ ] Dynamic role switching — let agents switch roles based on game state
- [ ] LLM brain integration — use analyze prompt for real-time strategic adaptation
- [ ] PCO evolution — run PCO epochs to evolve program table
- [ ] Better junction discovery — agents may miss junctions behind walls
- [ ] Adaptive role allocation based on game phase (not just step count)
- [ ] Late-game optimization — shift more to aligners after step 5000

## Dead Ends (Don't Retry)
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
- [x] Wider enemy AOE radius 15 for retreat — agents retreat too much, avg 1.83 vs 2.10
- [x] Delay scramblers to step 500 — avg 0.99 vs 2.10, opponent builds unchallenged

## Testing Notes
- **ALWAYS test 1v1 with `cogames run -c 16 -p A -p B`** not just scrimmage
- Scrimmage (`-c 8`) is self-play where one policy controls all agents — inflated scores
- Previous "remove scramblers" test was scrimmage only — retest in 1v1 for cooperative scoring

## Done
- [x] Establish baseline: 1.31 on machina_1 (seed 42)
- [x] Remove LLM resource herding: 1.31 → 1.72
- [x] Full ProgLet policy (GameState wraps engine): 1.76
- [x] PCO pipeline validated (learner proposes patches)
- [x] Session 5: tested retreat/budget/heart tuning — no improvement found
- [x] Session 6: fixed 4-agent role allocation (0.00 → ~0.95), submitted v13
- [x] Session 7: fixed coglet imports for tournament bundle, limited emergency mining
- [x] Session 8: shared junction memory + wider exploration (0.95 → 1.65 avg, v16)
- [x] Session 9: fixed role misassignment bug (1.65 → 6.18 avg, v17)
- [x] Session 10: chain-aware junction scoring (6.18 → 8.74 avg, v18)
- [x] Session 11: exhaustive parameter search — no improvement found, v18 is well-tuned
- [x] Session 12: emergency mining threshold tests — no improvement found
- [x] Session 13: CRITICAL FIX — agent_id normalization (% 8) for tournament mode (1v1 avg 18.38, v19)
- [x] Session 36: teammate-aware aligner targeting (+30% avg self-play), submitted v26/v27
- [x] Session 37 (ID): Fix double role-adjustment + wider enemy retreat + junction memory 400→600 (+11% self-play, v30/v31)
