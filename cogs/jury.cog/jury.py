"""Jury — N jurors deliberate and vote on a question.

All components accept executor="code" (default, deterministic) or
executor="llm" (uses LLM via ProgLet's LLM executor).

All work flows through data channels.
"""

import hashlib
import json

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogBase, Command,
    Program, enact, listen,
)
from coglet.mullet import MulLet


PERSONAS = [
    ("pragmatist", "focus on practical outcomes", 0.6),
    ("skeptic", "question assumptions", 0.4),
    ("optimist", "see potential benefits", 0.6),
    ("conservative", "prefer proven approaches", 0.4),
    ("innovator", "favor new solutions", 0.55),
    ("analytical", "weigh data carefully", 0.5),
    ("principled", "apply core values", 0.45),
]


class JurorCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """A single juror that hears evidence and votes.

    Args:
        juror_id: unique juror index
        executor: "code" for deterministic, "llm" for LLM-based reasoning
    """

    def __init__(self, juror_id: int = 0, executor: str = "code", **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.executor_type = executor
        self.vote: str | None = None
        self.evidence: list[dict] = []

    async def on_start(self):
        persona, style, _ = PERSONAS[self.juror_id % len(PERSONAS)]
        # Register both executors; "deliberate" points to the active one
        self.programs["deliberate/code"] = Program(executor="code", fn=self._deliberate)
        self.programs["deliberate/llm"] = Program(
            executor="llm",
            system=lambda ctx: (
                f"You are juror #{self.juror_id}, a {persona} who tends to {style}.\n"
                f"Evidence heard:\n{self._format_evidence()}\n\n"
                f"Question: {ctx}\n\n"
                "Deliberate and respond with JSON: "
                '{"vote": "yes" or "no", "reasoning": "...", "persona": "' + persona + '"}'
            ),
            parser=lambda s: json.loads(s),
        )
        self.programs["deliberate"] = self.programs[f"deliberate/{self.executor_type}"]
        await self.log("info", f"juror-{self.juror_id} ({persona}) seated [{self.executor_type}]")

    def _format_evidence(self) -> str:
        if not self.evidence:
            return "(no evidence heard)"
        return "\n".join(
            f"- {e.get('side', 'unknown')}: {e.get('argument', str(e))}"
            for e in self.evidence
        )

    @listen("input")
    async def on_input(self, argument: dict):
        """Hear evidence."""
        self.evidence.append(argument)
        await self.log("debug", f"juror-{self.juror_id} heard {argument.get('side', 'evidence')}")

    @listen("question")
    async def on_question(self, question):
        """Receive the question — deliberate and vote."""
        if isinstance(question, dict):
            question = question.get("question", str(question))
        result = await self.invoke("deliberate", question or "")
        self.vote = result["vote"]
        await self.log("info", f"juror-{self.juror_id} ({result.get('persona', '?')}): {result['vote']}")
        await self.transmit("output", {"juror_id": self.juror_id, **result})

    def _deliberate(self, question) -> dict:
        """Deterministic deliberation (code executor)."""
        persona, style, base_lean = PERSONAS[self.juror_id % len(PERSONAS)]
        seed = f"{self.juror_id}{question}"
        if self.evidence:
            seed += "".join(e.get("argument", str(e))[:50] for e in self.evidence)
        h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
        noise = ((h % 100) - 50) / 200
        vote = "yes" if (base_lean + noise) > 0.5 else "no"

        if self.evidence:
            pro = next((e["argument"][:60] for e in self.evidence if e.get("side") == "prosecution"), "")
            con = next((e["argument"][:60] for e in self.evidence if e.get("side") == "defense"), "")
            reasoning = f"As a {persona} (I {style}), weighing pro ({pro}...) vs con ({con}...), I vote {vote.upper()}."
        else:
            reasoning = f"As a {persona} (I {style}), I {'support' if vote == 'yes' else 'oppose'} this."
        return {"vote": vote, "reasoning": reasoning, "persona": persona}

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


class JuryCoglet(Coglet, LifeLet, MulLet):
    """Empanels N jurors. All work flows through data channels.

    Args:
        executor: passed to each JurorCoglet
    """

    def __init__(self, num_jurors: int = 5, question: str = "",
                 expected_evidence: int = 2, executor: str = "code", **kwargs):
        super().__init__(**kwargs)
        self.num_jurors = num_jurors
        self.question = question
        self.expected_evidence = expected_evidence
        self.executor_type = executor
        self._pending_verdicts = []
        self._expected_count = 0
        self._evidence_count = 0
        self._held_question = None
        self._current_question = ""

    async def on_start(self):
        print(f"[jury] empaneling {self.num_jurors} jurors [{self.executor_type}]")

        for i in range(self.num_jurors):
            handle = await self.create(CogBase(
                cls=JurorCoglet, label=f"Juror {i}",
                kwargs={"juror_id": i, "executor": self.executor_type},
            ))
            self._mul_children.append(handle)

        for h in self._mul_children:
            self.link(self.handle, "to-jurors", h, "question")
            self.link(self.handle, "evidence", h, "input")
            self.link(h, "output", self.handle, "from-jurors")

        if self.question:
            self.expected_evidence = 0
            self._pending_verdicts = []
            self._expected_count = len(self._mul_children)
            self._held_question = self.question
            self._current_question = self.question
            print(f"[jury] question: {self.question}")
            await self._maybe_forward_question()

    @listen("input")
    async def on_input(self, question):
        if isinstance(question, dict):
            question = question.get("question", str(question))
        self._pending_verdicts = []
        self._expected_count = len(self._mul_children)
        self._held_question = question
        self._current_question = question
        self._evidence_count = 0
        print(f"[jury] received question: {question} (waiting for {self.expected_evidence} evidence)")
        await self._maybe_forward_question()

    @listen("evidence")
    async def on_evidence(self, data):
        self._evidence_count += 1
        side = data.get('side', '?') if isinstance(data, dict) else '?'
        print(f"[jury] evidence {self._evidence_count}/{self.expected_evidence}: {side}")
        await self._maybe_forward_question()

    async def _maybe_forward_question(self):
        if self._held_question and self._evidence_count >= self.expected_evidence:
            q = self._held_question
            self._held_question = None
            print(f"[jury] all evidence received, forwarding question to jurors")
            await self.transmit("to-jurors", q)

    @listen("from-jurors")
    async def on_juror_verdict(self, verdict):
        self._pending_verdicts.append(verdict)
        if len(self._pending_verdicts) >= self._expected_count and self._expected_count > 0:
            verdicts = self._pending_verdicts
            self._pending_verdicts = []
            self._expected_count = 0

            yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
            no_votes = len(verdicts) - yes_votes
            result = "YES" if yes_votes > no_votes else "NO"

            print(f"\n[jury] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
            for v in verdicts:
                symbol = "+" if v["vote"] == "yes" else "-"
                print(f"  [{symbol}] juror-{v['juror_id']}: {v['reasoning']}")

            await self.transmit("output", {
                "question": self._current_question,
                "result": result, "yes": yes_votes, "no": no_votes, "verdicts": verdicts,
            })

    async def on_stop(self):
        print("[jury] dismissed")
