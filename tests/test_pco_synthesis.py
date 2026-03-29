"""PCO program synthesis test: learner generates and tests Python code.

The learner doesn't know the target function's structure. It works like an LLM:
1. Observe errors — what inputs are wrong and by how much
2. Generate candidate expressions from a grammar
3. Test each candidate against all known (input, expected) pairs
4. Keep the best, refine next epoch

Target functions are chosen to require discovering non-obvious structure.
The learner searches through combinations of arithmetic operations.
"""

import asyncio
import itertools
import operator

import pytest

from coglet import Coglet, CogletConfig, CogletRuntime, enact, listen
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.learner import LearnerCoglet
from coglet.pco.loss import LossCoglet
from coglet.pco.optimizer import ProximalCogletOptimizer


# ── Shared components ──────────────────────────────────────


class FnActor(Coglet):
    def __init__(self, *, inputs, target, **kwargs):
        super().__init__(**kwargs)
        self.fn = lambda x: x
        self._inputs = inputs
        self._target = target

    @enact("run")
    async def run_rollout(self, data):
        results = [
            {"input": x, "output": self.fn(x), "expected": self._target(x)}
            for x in self._inputs
        ]
        await self.transmit("experience", {"results": results})

    @enact("update")
    async def apply_update(self, patch):
        self.fn = patch["fn"]


class ErrorCritic(Coglet):
    @listen("experience")
    async def evaluate(self, experience):
        errors = [r for r in experience["results"] if r["output"] != r["expected"]]
        await self.transmit("evaluation", {
            "errors": errors,
            "correct": len(experience["results"]) - len(errors),
            "total": len(experience["results"]),
        })

    @enact("update")
    async def apply_update(self, patch):
        pass


class ErrorCountLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        return {
            "name": "error_count",
            "magnitude": len(evaluation["errors"]),
        }


class MeanAbsErrorLoss(LossCoglet):
    """Average absolute error — gives gradient-like signal even when
    the correct count doesn't change between candidates."""

    async def compute_loss(self, experience, evaluation):
        results = experience["results"]
        if not results:
            return {"name": "mae", "magnitude": 0}
        total = sum(abs(r["output"] - r["expected"]) for r in results)
        return {"name": "mae", "magnitude": total / len(results)}


class AlwaysAccept(ConstraintCoglet):
    async def check(self, patch):
        return {"accepted": True}


async def run_pco(*, target, inputs, learner, epochs, losses=None, constraints=None):
    runtime = CogletRuntime()
    handle = await runtime.spawn(CogletConfig(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogletConfig(cls=FnActor, kwargs=dict(inputs=inputs, target=target)),
            critic_config=CogletConfig(cls=ErrorCritic),
            losses=losses or [ErrorCountLoss()],
            constraints=constraints or [AlwaysAccept()],
            learner=learner,
        ),
    ))
    pco = handle.coglet
    results = await pco.run(num_epochs=epochs)
    actor = pco._actor_handle.coglet
    await runtime.shutdown()
    return results, actor


# ── Program synthesis learner ─────────────────────────────


class Expression:
    """A candidate program: a composition of operations on x."""

    def __init__(self, ops: list[tuple[str, int]], name: str = ""):
        self.ops = ops  # list of (op_name, constant)
        self.name = name or self._auto_name()

    def _auto_name(self) -> str:
        parts = ["x"]
        for op, c in self.ops:
            if op == "+":
                parts.append(f"+ {c}")
            elif op == "*":
                parts.append(f"* {c}")
            elif op == "%":
                parts.append(f"% {c}")
            elif op == "//":
                parts.append(f"// {c}")
            elif op == "**":
                parts.append(f"** {c}")
            elif op == "^":
                parts.append(f"^ {c}")
        return " ".join(parts)

    def __call__(self, x: int) -> int:
        result = x
        for op, c in self.ops:
            if op == "+":
                result = result + c
            elif op == "*":
                result = result * c
            elif op == "%":
                result = result % c
            elif op == "//":
                result = result // c if c != 0 else result
            elif op == "**":
                result = int(result ** c)
            elif op == "^":
                result = result ^ c
        return result

    def score(self, examples: list[dict]) -> int:
        """Number of examples this expression gets correct."""
        correct = 0
        for e in examples:
            try:
                if self(e["input"]) == e["expected"]:
                    correct += 1
            except (OverflowError, ZeroDivisionError, ValueError):
                pass
        return correct

    def mae(self, examples: list[dict]) -> float:
        """Mean absolute error — lower is better."""
        total = 0
        for e in examples:
            try:
                total += abs(self(e["input"]) - e["expected"])
            except (OverflowError, ZeroDivisionError, ValueError):
                total += 1000
        return total / max(len(examples), 1)


class SynthesisLearner(LearnerCoglet):
    """Program synthesis by generate-and-test.

    Each epoch:
    1. Collect all (input, expected) examples from experience
    2. Generate candidate expressions (expanding search each epoch)
    3. Score each candidate against examples
    4. Keep the best as the new actor function

    The search space grows each epoch: depth 1, then 2, then 3 ops.
    This mimics an LLM exploring different hypotheses.
    """

    OPS = ["+", "*", "%", "//", "**", "^"]
    CONSTANTS = [-3, -2, -1, 0, 1, 2, 3, 4, 5, 7, 10, 13, 17]

    def __init__(self, *, max_depth: int = 3, **kwargs):
        super().__init__(**kwargs)
        self._max_depth = max_depth
        self._epoch = 0
        self._best: Expression | None = None
        self._best_score = -1
        self._all_examples: list[dict] = []

    async def learn(self, experience, evaluation, signals):
        self._epoch += 1

        # Accumulate examples across epochs
        for r in experience["results"]:
            key = r["input"]
            if not any(e["input"] == key for e in self._all_examples):
                self._all_examples.append(
                    {"input": r["input"], "expected": r["expected"]}
                )

        # Expand search depth each epoch
        depth = min(self._epoch, self._max_depth)

        # Generate and test candidates
        for candidate in self._generate(depth):
            score = candidate.score(self._all_examples)
            if score > self._best_score:
                self._best_score = score
                self._best = candidate
            elif score == self._best_score and self._best is not None:
                # Tiebreak on MAE
                if candidate.mae(self._all_examples) < self._best.mae(self._all_examples):
                    self._best = candidate

        fn = self._best if self._best is not None else Expression([])
        return {"fn": fn}

    def _generate(self, depth: int):
        """Generate all expressions up to given depth."""
        # Depth 0: identity
        yield Expression([], name="x")

        for d in range(1, depth + 1):
            for combo in itertools.product(
                [(op, c) for op in self.OPS for c in self.CONSTANTS],
                repeat=d,
            ):
                # Skip useless: multiply by 0, add 0, mod by 0/1, etc.
                ops = list(combo)
                if any(op == "//" and c == 0 for op, c in ops):
                    continue
                if any(op == "%" and c in (0, 1) for op, c in ops):
                    continue
                if any(op == "**" and c > 3 for op, c in ops):
                    continue
                yield Expression(ops)


# ═══════════════════════════════════════════════════════════
# Test 6: Hidden formula — learner must discover x*3 + 7
# Simple enough to find at depth 2 but not guessable.
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_synthesis_linear():
    target = lambda x: x * 3 + 7
    inputs = list(range(0, 20, 2))

    results, actor = await run_pco(
        target=target,
        inputs=inputs,
        learner=SynthesisLearner(max_depth=2),
        losses=[ErrorCountLoss(), MeanAbsErrorLoss()],
        epochs=3,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[-1] == 0
    for x in inputs:
        assert actor.fn(x) == target(x)
    # Also test on unseen inputs — true generalization
    for x in [1, 3, 5, 7, 99]:
        assert actor.fn(x) == target(x), f"generalization failed: f({x})"


# ═══════════════════════════════════════════════════════════
# Test 7: Quadratic — learner must discover x**2 + 1
# Requires depth 2: (** 2) then (+ 1).
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_synthesis_quadratic():
    target = lambda x: x ** 2 + 1
    inputs = list(range(0, 10))

    results, actor = await run_pco(
        target=target,
        inputs=inputs,
        learner=SynthesisLearner(max_depth=2),
        losses=[ErrorCountLoss(), MeanAbsErrorLoss()],
        epochs=3,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[-1] == 0
    for x in inputs:
        assert actor.fn(x) == target(x)
    # Generalize
    for x in [10, 15, 20]:
        assert actor.fn(x) == target(x)


# ═══════════════════════════════════════════════════════════
# Test 8: Modular cipher — (x * 5 + 3) % 17
# Requires depth 3: (* 5) (+ 3) (% 17).
# Non-obvious — output looks random but has structure.
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_synthesis_modular_cipher():
    target = lambda x: (x * 5 + 3) % 17
    inputs = list(range(0, 17))

    results, actor = await run_pco(
        target=target,
        inputs=inputs,
        learner=SynthesisLearner(max_depth=3),
        losses=[ErrorCountLoss(), MeanAbsErrorLoss()],
        epochs=4,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[-1] == 0
    for x in inputs:
        assert actor.fn(x) == target(x)


# ═══════════════════════════════════════════════════════════
# Test 9: XOR mask — x ^ 13
# Bitwise operation — not discoverable by arithmetic alone.
# Learner must try the ^ operator.
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_synthesis_xor():
    target = lambda x: x ^ 13
    inputs = list(range(0, 20))

    results, actor = await run_pco(
        target=target,
        inputs=inputs,
        learner=SynthesisLearner(max_depth=2),
        losses=[ErrorCountLoss(), MeanAbsErrorLoss()],
        epochs=3,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[-1] == 0
    for x in inputs:
        assert actor.fn(x) == target(x)


# ═══════════════════════════════════════════════════════════
# Test 10: Composed ops — (x + 2) * 3 // 4
# Requires chaining 3 ops in the right order.
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_synthesis_composed():
    target = lambda x: (x + 2) * 3 // 4
    inputs = list(range(0, 20))

    results, actor = await run_pco(
        target=target,
        inputs=inputs,
        learner=SynthesisLearner(max_depth=3),
        losses=[ErrorCountLoss(), MeanAbsErrorLoss()],
        epochs=4,
    )

    errors = [r["signals"][0]["magnitude"] for r in results]
    assert errors[-1] == 0
    for x in inputs:
        assert actor.fn(x) == target(x)
