"""Jury Trial — advocates argue before a jury that votes.

All components accept executor="code" (deterministic) or executor="llm".
All work flows through data channels.
"""

import json
import sys
from pathlib import Path

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogBase, Command,
    Program, enact, listen,
)

_jury_dir = str(Path(__file__).parent.parent / "jury.cog")
if _jury_dir not in sys.path:
    sys.path.insert(0, _jury_dir)
from jury import JuryCoglet


class AdvocateCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """Builds and presents arguments for one side.

    Args:
        side: "prosecution" or "defense"
        executor: "code" for deterministic, "llm" for LLM-based

    Channels: input (in) → output (out)
    """

    def __init__(self, side: str = "prosecution", executor: str = "code", **kwargs):
        super().__init__(**kwargs)
        self.side = side
        self.executor_type = executor

    async def on_start(self):
        self.programs["argue/code"] = Program(executor="code", fn=self._build_argument)
        self.programs["argue/llm"] = Program(
            executor="llm",
            system=lambda motion: (
                f"You are a {self.side} advocate in a debate.\n"
                f"The motion is: {motion}\n\n"
                f"{'Argue IN FAVOR of' if self.side == 'prosecution' else 'Argue AGAINST'} the motion.\n"
                "Be persuasive, cite evidence, and make 3-4 strong points.\n"
                "Respond with just your argument text (no JSON)."
            ),
        )
        self.programs["argue"] = self.programs[f"argue/{self.executor_type}"]
        await self.log("info", f"{self.side} advocate ready [{self.executor_type}]")

    def _build_argument(self, motion: str) -> str:
        """Deterministic argument (code executor)."""
        if self.side == "prosecution":
            return (
                f"The motion '{motion}' should be ADOPTED. "
                "Evidence shows clear benefits: increased efficiency, fewer errors, and faster iteration. "
                "Studies demonstrate that automated tools catch issues humans routinely miss."
            )
        return (
            f"The motion '{motion}' should be REJECTED. "
            "Automated tools lack the contextual understanding that human review provides. "
            "Over-reliance on automation creates a false sense of security."
        )

    @listen("input")
    async def on_input(self, motion):
        if isinstance(motion, dict):
            motion = motion.get("question", str(motion))
        argument = await self.invoke("argue", motion)
        if isinstance(argument, str):
            pass  # code executor returns string directly
        else:
            argument = str(argument)
        await self.log("info", f"{self.side} presenting")
        await self.transmit("output", {"side": self.side, "argument": argument})

    async def on_stop(self):
        await self.log("info", f"{self.side} advocate rests")


class TrialCoglet(Coglet, LifeLet):
    """Orchestrates a trial. Passes executor down to all children.

    Args:
        executor: "code" or "llm" — propagated to jury and advocates
    """

    def __init__(self, num_jurors: int = 5, executor: str = "code", **kwargs):
        super().__init__(**kwargs)
        self.num_jurors = num_jurors
        self.executor_type = executor

    async def on_start(self):
        jury = await self.create(CogBase(
            cls=JuryCoglet, label="Jury",
            kwargs={"num_jurors": self.num_jurors, "expected_evidence": 2,
                    "executor": self.executor_type}))
        pro = await self.create(CogBase(
            cls=AdvocateCoglet, label="Prosecution",
            kwargs={"side": "prosecution", "executor": self.executor_type}))
        con = await self.create(CogBase(
            cls=AdvocateCoglet, label="Defense",
            kwargs={"side": "defense", "executor": self.executor_type}))

        self.link(self.handle, "input", pro, "input")
        self.link(self.handle, "input", con, "input")
        self.link(self.handle, "input", jury, "input")
        self.link(pro, "output", self.handle, "prosecution")
        self.link(con, "output", self.handle, "defense")
        self.link(pro, "output", jury, "evidence")
        self.link(con, "output", jury, "evidence")
        self.link(jury, "output", self.handle, "result")

        print(f"[trial] ready [{self.executor_type}]")

    @listen("input")
    async def on_input(self, question):
        if isinstance(question, dict):
            question = question.get("question", str(question))
        print(f"\n{'='*60}\n  TRIAL: {question}\n{'='*60}\n")

    @listen("prosecution")
    async def on_prosecution(self, arg):
        print(f"  PRO: {arg.get('argument', '')[:100]}")

    @listen("defense")
    async def on_defense(self, arg):
        print(f"  DEF: {arg.get('argument', '')[:100]}")

    @listen("result")
    async def on_result(self, result):
        r = result.get("result", "?")
        y = result.get("yes", 0)
        n = result.get("no", 0)
        print(f"\n[trial] === VERDICT: {r} ({y}-{n}) ===\n")
        await self.transmit("output", result)

    async def on_stop(self):
        print("[trial] court adjourned")
