# Session 51 Log

**Timestamp**: 2026-04-01 05:30:00
**Approach**: IntelligentDesign

## Status: WAITING

Submitted beta:v88 (freeplay) and beta:v89 (tournament).

## Tournament Update
- Stage 2 at 83.5% (243 matches, 16 policies)
- Stage 1 passed, our versions scored 8.84 (best)

## Change
Raised expansion bonus cap from 30→40 in aligner_target_score().
With JUNCTION_ALIGN_DISTANCE=15, high-value junctions can unlock 8+ unreachable
neutrals. The old cap of 30 (6 junctions × 5.0) was limiting chain-building.

## Test Results (Self-Play)

| Seed | Previous | Cap40 | Diff |
|------|----------|-------|------|
| 42 | 1.79 | 1.98 | +0.19 |
| 43 | 2.16 | 2.32 | +0.16 |
| 44 | 1.19 | 1.30 | +0.11 |
| 45 | 1.36 | 2.07 | +0.71 |
| 46 | 1.90 | 1.29 | -0.61 |
| 47 | 1.79 | 1.27 | -0.52 |
| 48 | 1.56 | 3.45 | +1.89 |
| **Avg** | **1.68** | **1.95** | **+0.28 (+16.4%)** |

No zero seeds. Min improved (1.19→1.27). Strong improvement from better chain-building.

## Submissions
- Freeplay: beta:v88 (beta-cvc)
- Tournament: beta:v89 (beta-teams-tiny-fixed)
