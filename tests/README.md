# tests

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

## Framework tests

| File | What it tests |
|---|---|
| `test_coglet.py` | Base Coglet, @listen/@enact dispatch, transmit |
| `test_channel.py` | ChannelBus pub/sub, subscriber isolation |
| `test_handle.py` | CogletHandle observe/guide, CogletConfig |
| `test_runtime.py` | CogletRuntime spawn/shutdown, restart, tree viz, tracing |
| `test_lifelet.py` | LifeLet on_start/on_stop hooks |
| `test_ticklet.py` | TickLet @every with time/tick units |
| `test_codelet.py` | CodeLet function table hot-swap |
| `test_gitlet.py` | GitLet repo-as-policy |
| `test_loglet.py` | LogLet separate log stream |
| `test_mullet.py` | MulLet fan-out/reduce |
| `test_suppresslet.py` | SuppressLet channel/command gating |
| `test_trace.py` | CogletTrace jsonl recording |
| `test_mixins.py` | Mixin composition and interaction |
| `test_integration.py` | Multi-coglet integration scenarios |
| `test_improvements.py` | Architectural improvement validations |

## PCO tests

| File | What it tests |
|---|---|
| `test_pco_loss.py` | LossCoglet base class |
| `test_pco_constraint.py` | ConstraintCoglet accept/reject |
| `test_pco_learner.py` | LearnerCoglet context → update |
| `test_pco_optimizer.py` | PCO core loop, retry, multi-epoch |
| `test_pco_integration.py` | End-to-end: teach actor target functions (odd/even, collatz, tax brackets, modular, constraint rejection) |
| `test_pco_synthesis.py` | Program synthesis: learner discovers formulas from examples (linear, quadratic, cipher, XOR, composed) |
