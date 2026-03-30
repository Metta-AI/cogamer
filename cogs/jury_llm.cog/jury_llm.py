"""LLM-powered Jury — N jurors deliberate using an LLM brain.

Requires ANTHROPIC_API_KEY to be set. Will crash on startup if missing.

Each juror has a unique persona and uses LLMExecutor (via ProgLet)
to reason about the question.

Demonstrates:
  - LLMExecutor: real LLM reasoning via Anthropic API
  - ProgLet: program table with "llm" executor
  - MulLet: fan-out N jurors
  - LogLet: structured log stream
  - LifeLet: lifecycle hooks
"""

import os
import sys

import anthropic

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogBase, Command,
    Program, LLMExecutor, enact,
)
from coglet.mullet import MulLet

if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("error: ANTHROPIC_API_KEY is required. Set it and try again.")

CLIENT = anthropic.Anthropic()

PERSONAS = [
    "a strict empiricist who demands reproducible evidence",
    "a philosophical skeptic who questions all assumptions",
    "a practical engineer who trusts measurement and observation",
    "a historian who values the accumulated record of human knowledge",
    "a curious child who asks simple but penetrating questions",
]


def _parse_verdict(text: str) -> dict:
    """Parse LLM verdict text into structured vote."""
    lower = text.lower()
    if "vote: yes" in lower or "i vote yes" in lower:
        vote = "yes"
    elif "vote: no" in lower or "i vote no" in lower:
        vote = "no"
    else:
        vote = "yes" if lower.count("yes") > lower.count("no") else "no"
    return {"vote": vote, "reasoning": text.strip()}


class JurorCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """A juror that uses an LLM to reason about questions."""

    def __init__(self, juror_id: int = 0, persona: str = "", **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.persona = persona

    async def on_start(self):
        self.executors["llm"] = LLMExecutor(CLIENT)

        self.programs["deliberate"] = Program(
            executor="llm",
            system=lambda _ctx: (
                f"You are a juror on a deliberation panel. Your persona: {self.persona}. "
                f"Consider the question carefully from your unique perspective. "
                f"Provide your reasoning, then state your vote clearly as 'Vote: yes' or 'Vote: no'."
            ),
            parser=_parse_verdict,
            config={"max_turns": 1, "max_tokens": 300, "temperature": 0.7},
        )
        await self.log("info", f"juror-{self.juror_id} ({self.persona[:30]}...) seated")

    @enact("question")
    async def on_question(self, question: str):
        await self.log("debug", f"juror-{self.juror_id} deliberating on: {question}")
        result = await self.invoke("deliberate", question)
        await self.log("info", f"juror-{self.juror_id} votes {result['vote']}")
        await self.transmit("verdict", {
            "juror_id": self.juror_id,
            "persona": self.persona[:40],
            **result,
        })

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


class JuryCoglet(Coglet, LifeLet, MulLet):
    """Empanels N LLM-powered jurors and collects their votes."""

    def __init__(self, num_jurors: int = 5, question: str = "", **kwargs):
        super().__init__(**kwargs)
        self.num_jurors = num_jurors
        self.question = question

    async def on_start(self):
        print(f"[jury] empaneling {self.num_jurors} jurors")
        print(f"[jury] question: {self.question}")
        print()

        for i in range(self.num_jurors):
            persona = PERSONAS[i % len(PERSONAS)]
            handle = await self.create(CogBase(
                cls=JurorCoglet,
                kwargs={"juror_id": i, "persona": persona},
            ))
            self._mul_children.append(handle)

        # Subscribe before sending question
        subs = []
        for h in self._mul_children:
            subs.append(h.coglet._bus.subscribe("verdict"))

        # Pose question
        await self.guide_mapped(Command("question", self.question))

        # Collect verdicts
        verdicts = []
        for sub in subs:
            verdicts.append(await sub.get())

        # Tally
        yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
        no_votes = len(verdicts) - yes_votes
        result = "YES" if yes_votes > no_votes else "NO"

        print("[jury] === DELIBERATION ===")
        for v in verdicts:
            symbol = "+" if v["vote"] == "yes" else "-"
            print(f"  [{symbol}] juror-{v['juror_id']} ({v['persona']}):")
            for line in v["reasoning"].split(". "):
                if line.strip():
                    print(f"      {line.strip()}.")
            print()

        print(f"[jury] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
        await self.transmit("verdict", {
            "result": result, "yes": yes_votes, "no": no_votes,
        })

    async def on_stop(self):
        print("[jury] dismissed")
