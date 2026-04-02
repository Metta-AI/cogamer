# Development Rules & Constraints

1. **No shared state between agents.** Each agent gets its own WorldModel, claims dict, junctions dict. Sharing causes 0.00 score
2. **One change at a time.** Isolate what works vs what breaks
3. **Test across 5+ seeds.** A single seed is meaningless
4. **Local scores lie.** Self-play inflates scores. Validate in freeplay before tournament
5. **Revert on regression.** If average score drops, revert immediately
6. **Tournament has action timeout.** Keep per-step computation fast
