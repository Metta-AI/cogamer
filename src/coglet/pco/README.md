# pco — Proximal Coglet Optimizer

PPO expressed as a coglet graph. Every component of the training loop is a standard coglet.

## Architecture

```
ProximalCogletOptimizer (COG)
  ├── actor (created from config, updated via enact)
  ├── critic (created from config, updated via enact)
  ├── losses[] (plugged, observe-only)
  ├── constraints[] (plugged, observe-only)
  └── learner (plugged, observe-only)
```

## Loop (one epoch)

1. Guide actor to run rollout, collect experience
2. Feed experience to critic, collect evaluation
3. Feed (experience, evaluation) to each loss, collect signals
4. Feed (experience, evaluation, signals) to learner, collect patch
5. Feed patch to each constraint, collect accept/reject
6. If rejected: feed reason back to learner, retry (up to max_retries)
7. If accepted: guide(actor, patch) and guide(critic, patch) via enact("update")

## Files

| File | Class | Purpose |
|---|---|---|
| `optimizer.py` | ProximalCogletOptimizer | COG that orchestrates the loop |
| `loss.py` | LossCoglet | Base: listen(experience+evaluation) → transmit(signal) |
| `constraint.py` | ConstraintCoglet | Base: listen(update) → transmit(verdict) |
| `learner.py` | LearnerCoglet | Base: listen(context) → transmit(update) |

## Design

See [docs/design/proximal_coglet_optimizer.md](../../../docs/design/proximal_coglet_optimizer.md).
