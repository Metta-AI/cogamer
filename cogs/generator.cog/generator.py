"""Generator — generates items on a topic at a regular interval.

Configurable with a prompt describing what to generate.
Supports code (cycles through seed list) and llm (generates via LLM) executors.

Tracks responses on "input" and logs {prompt, response, time_s} on "log".

    generator = await self.create(CogBase(
        cls=GeneratorCoglet, label="Question Generator",
        kwargs={"prompt": "interesting questions about AI", "interval_s": 30}
    ))
"""

import json
import time

from coglet import (
    Coglet, LifeLet, TickLet, ProgLet, LogLet,
    Program, listen, every,
)

# Seed lists for code executor, keyed by topic keywords
SEED_ITEMS = {
    "question": [
        "Should AI replace code review?",
        "Is remote work better than office work?",
        "Should programming languages have garbage collection?",
        "Is open source software more secure than proprietary?",
        "Should children learn to code before they learn to read?",
        "Is social media a net positive for society?",
        "Should self-driving cars be allowed on all roads?",
        "Is cryptocurrency the future of money?",
        "Should robots have legal rights?",
        "Is space colonization worth the investment?",
        "Should we ban facial recognition technology?",
        "Is universal basic income a good idea?",
        "Should voting be mandatory?",
        "Is nuclear energy the best path to carbon neutrality?",
        "Should internet access be a human right?",
        "Is pineapple acceptable on pizza?",
        "Is tabs better than spaces?",
        "Should we colonize Mars before fixing Earth?",
        "Is dark mode objectively better than light mode?",
        "Should cats be allowed to vote?",
    ],
    "default": [
        "Item 1", "Item 2", "Item 3", "Item 4", "Item 5",
        "Item 6", "Item 7", "Item 8", "Item 9", "Item 10",
    ],
}


class GeneratorCoglet(Coglet, LifeLet, TickLet, ProgLet, LogLet):
    """Generates items on a topic at regular intervals.

    Args:
        prompt: what to generate (e.g. "interesting questions about AI")
        interval_s: seconds between generations (default 30)
        executor: "code" or "llm"

    Channels:
        output (out) — generated items
        input (in)   — responses (for tracking timing)
        log (out)    — {prompt, item, response, time_s} records
    """

    def __init__(self, prompt: str = "interesting questions",
                 interval_s: int = 30, executor: str = "code", **kwargs):
        super().__init__(**kwargs)
        self.prompt = prompt
        self.interval_s = interval_s
        self.executor_type = executor
        self.count = 0
        self._pending = {}  # item -> send_time
        self._seed_list = self._pick_seed_list()

    def _pick_seed_list(self) -> list[str]:
        """Pick seed list based on prompt keywords."""
        prompt_lower = self.prompt.lower()
        for key, items in SEED_ITEMS.items():
            if key in prompt_lower:
                return items
        return SEED_ITEMS["default"]

    async def on_start(self):
        self.programs["generate/code"] = Program(executor="code", fn=self._generate_code)
        self.programs["generate/llm"] = Program(
            executor="llm",
            system=lambda ctx: (
                f"Generate one {self.prompt}.\n"
                f"This is item #{ctx['count']}.\n"
                f"Previous items: {ctx.get('previous', 'none')}\n\n"
                "Respond with just the item text, nothing else."
            ),
        )
        self.programs["generate"] = self.programs[f"generate/{self.executor_type}"]
        await self.log("info", f"generator started: '{self.prompt}' every {self.interval_s}s [{self.executor_type}]")

    def _generate_code(self, ctx) -> str:
        """Code executor: cycle through seed list."""
        idx = ctx["count"] % len(self._seed_list)
        return self._seed_list[idx]

    @every(30, "s")
    async def _tick(self):
        await self.generate()

    async def generate(self):
        """Generate and transmit one item."""
        self.count += 1
        ctx = {"count": self.count, "previous": list(self._pending.keys())[-3:]}
        item = await self.invoke("generate", ctx)
        if not isinstance(item, str):
            item = str(item)
        self._pending[item] = time.time()
        await self.log("info", f"#{self.count}: {item[:80]}")
        await self.transmit("output", item)

    @listen("input")
    async def on_input(self, response):
        """Receive a response, match to pending item, log timing."""
        # Try to find the matching pending item
        item = None
        send_time = None

        # Check if response contains a reference to the original item
        if isinstance(response, dict):
            for key in ("question", "item", "prompt"):
                if key in response:
                    candidate = response[key]
                    if candidate in self._pending:
                        item = candidate
                        send_time = self._pending.pop(candidate)
                        break

        # Fallback: pop oldest pending
        if item is None and self._pending:
            item, send_time = next(iter(self._pending.items()))
            del self._pending[item]

        elapsed = time.time() - send_time if send_time else 0
        entry = {
            "item": item or "?",
            "response": response if isinstance(response, dict) else str(response),
            "time_s": round(elapsed, 2),
        }
        await self.log("info", f"response in {elapsed:.1f}s")
        await self.transmit("log", entry)

    async def on_stop(self):
        await self.log("info", f"stopped after {self.count} items")
