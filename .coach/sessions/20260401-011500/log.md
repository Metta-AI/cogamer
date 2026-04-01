# Session 45 Log

**Timestamp**: 2026-04-01 01:15:00
**Approach**: IntelligentDesign

## Status: WAITING

Submitted beta:v76 (freeplay) and beta:v77 (tournament).

## Change
Hub-proximal hotspot discount in aligner_target_score():
- hub_dist <= 10: hotspot_weight = 2.0 (was 8.0)
- hub_dist <= 15: hotspot_weight = 5.0 (was 8.0)
- hub_dist > 15: hotspot_weight = 8.0 (unchanged)

Rationale: hub-proximal junctions are the most valuable for scoring (fast cycling, safe retreat). They're also the most contested. Reducing the hotspot penalty near hub ensures we defend core territory while still avoiding distant contested junctions.

## Test Results (Self-Play)

| Seed | Previous | +Discount | Diff |
|------|----------|-----------|------|
| 42 | 1.87 | 2.07 | +0.20 |
| 43 | 2.71 | 2.40 | -0.31 |
| 44 | 0.60 | 0.62 | +0.02 |
| 45 | 1.24 | 2.00 | +0.76 |
| 46 | 1.23 | 1.23 | +0.00 |
| 47 | 1.81 | 1.09 | -0.72 |
| 48 | 0.80 | 1.83 | +1.03 |
| **Avg** | **1.47** | **1.61** | **+0.14 (+9.6%)** |

Combined improvement vs original baseline: **+32.5%** (1.21 → 1.61)

All changes in this agent version (v76/v77):
1. Hotspot tracking (deprioritize contested junctions)
2. Network proximity bonus (chain-building)
3. Junction memory 400→800
4. Hub-proximal hotspot discount

## Submissions
- Freeplay: beta:v76 (beta-cvc)
- Tournament: beta:v77 (beta-teams-tiny-fixed)
