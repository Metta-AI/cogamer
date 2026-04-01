# Session 48 Log

**Timestamp**: 2026-04-01 03:15:00
**Approach**: IntelligentDesign

## Status: WAITING

Submitted beta:v90 (freeplay) and beta:v91 (tournament).

## Change
Increased aligner target network_bonus weight from 0.5 → 2.0 per nearby friendly junction (max 8.0 vs 2.0).
Creates denser, more defensible junction chains.

Also investigated scrambler targeting bug (missing friendly_junctions in sticky comparison) — fix caused -12.9% regression due to excessive target switching, reverted.

## Test Results (Self-Play, 8 seeds)

| Seed | Baseline | Network 2.0 | Diff |
|------|----------|-------------|------|
| 42 | 0.00 | 12.26 | +12.26 |
| 43 | 8.76 | 7.63 | -1.13 |
| 44 | 6.18 | 9.30 | +3.12 |
| 45 | 9.78 | 7.82 | -1.96 |
| 46 | 6.42 | 9.87 | +3.45 |
| 47 | 9.97 | 11.31 | +1.34 |
| 48 | 5.33 | 7.68 | +2.35 |
| 49 | 10.63 | 20.22 | +9.59 |
| **Avg** | **7.13** | **10.76** | **+50.9%** |

## Submissions
- Freeplay: beta:v90 (beta-cvc)
- Tournament: beta:v91 (beta-teams-tiny-fixed)

## Notes
- Seed 42 was 0.00 baseline (all agents HP=0 by step 500) — network bonus fixed this completely
- Remote had concurrent changes: expansion cap 30→40, scramble weight 4→6, miner stall 12→8
- Our change was rebased on top of those
