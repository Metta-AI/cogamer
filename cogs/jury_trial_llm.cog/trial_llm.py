"""LLM-powered Jury Trial — advocate teams argue before an LLM jury.

Requires ANTHROPIC_API_KEY to be set. Will crash on startup if missing.

Full adversarial system where each side is a TEAM:
  - AdvocateTeamCoglet (COG per side):
    - 5 AdvocateCoglets: each drafts an independent argument
    - 1 EditorCoglet: reads all 5 drafts, composes the most convincing one
  - N JurorCoglets: hear both final arguments, then vote
  - SuppressLet gates juror output during argument phase
  - TrialCoglet orchestrates the full proceeding

Demonstrates every mixin in combination:
  - LifeLet, ProgLet, LLMExecutor, LogLet, SuppressLet, MulLet
  - Multi-level COG/LET trees (Trial -> Teams -> Advocates+Editor)
  - Full guide/observe/transmit/listen data+control planes
"""

import os
import sys

import anthropic

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogBase, Command,
    Program, LLMExecutor, enact, listen,
)
from coglet.mullet import MulLet
from coglet.suppresslet import SuppressLet

if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("error: ANTHROPIC_API_KEY is required. Set it and try again.")

CLIENT = anthropic.Anthropic()

ADVOCATE_STYLES = [
    "emotional appeals and vivid storytelling",
    "hard statistics, studies, and data",
    "logical reasoning and first-principles thinking",
    "historical precedent and real-world examples",
    "reductio ad absurdum and attacking the opposition's weakest points",
]

JUROR_PERSONAS = [
    "a strict empiricist who demands reproducible evidence",
    "a philosophical skeptic who questions all assumptions",
    "a practical engineer who trusts measurement and observation",
    "a historian who values the accumulated record of human knowledge",
    "a curious child who asks simple but penetrating questions",
]


def _parse_argument(text: str) -> dict:
    return {"argument": text.strip()}


def _parse_verdict(text: str) -> dict:
    lower = text.lower()
    if "vote: yes" in lower or "i vote yes" in lower:
        vote = "yes"
    elif "vote: no" in lower or "i vote no" in lower:
        vote = "no"
    else:
        vote = "yes" if lower.count("yes") > lower.count("no") else "no"
    return {"vote": vote, "reasoning": text.strip()}


# ---------------------------------------------------------------------------
# Advocate layer: individual advocate + editor + team coordinator
# ---------------------------------------------------------------------------

class AdvocateCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """One advocate with a specific argumentation style."""

    def __init__(self, side: str = "pro", style: str = "", advocate_id: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.side = side
        self.style = style
        self.advocate_id = advocate_id

    async def on_start(self):
        self.executors["llm"] = LLMExecutor(CLIENT)

        direction = "IS TRUE" if self.side == "pro" else "IS FALSE"
        self.programs["draft"] = Program(
            executor="llm",
            system=(
                f"You are a debate team member assigned the {'PRO' if self.side == 'pro' else 'CON'} side. "
                f"The motion will be given as the user message. "
                f"Argue that the motion {direction}. "
                f"Your specialty is: {self.style}. "
                f"Lean heavily into your specialty style. "
                f"Present 2-3 strong arguments. Be persuasive and concise."
            ),
            parser=_parse_argument,
            config={"max_turns": 1, "max_tokens": 300, "temperature": 0.9},
        )
        await self.log("info", f"advocate-{self.advocate_id} ({self.style[:30]}) ready")

    @enact("draft")
    async def on_draft(self, motion: str):
        result = await self.invoke("draft", motion)
        await self.log("info", f"advocate-{self.advocate_id} drafted argument")
        await self.transmit("draft", {
            "advocate_id": self.advocate_id,
            "style": self.style,
            **result,
        })

    async def on_stop(self):
        pass


class EditorCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """Reads all advocate drafts and composes the single most convincing argument."""

    def __init__(self, side: str = "pro", **kwargs):
        super().__init__(**kwargs)
        self.side = side
        self.drafts: list[dict] = []

    async def on_start(self):
        self.executors["llm"] = LLMExecutor(CLIENT)
        await self.log("info", f"editor ({self.side}) ready")

    @listen("collected_drafts")
    async def on_drafts(self, drafts: list[dict]):
        self.drafts = drafts

    @enact("compose")
    async def on_compose(self, motion: str):
        drafts_text = "\n\n".join(
            f"--- Draft {d['advocate_id']} ({d['style']}) ---\n{d['argument']}"
            for d in self.drafts
        )

        direction = "PRO (motion is true)" if self.side == "pro" else "CON (motion is false)"
        self.programs["compose"] = Program(
            executor="llm",
            system=(
                f"You are the chief editor for a {direction} debate team. "
                f"Your team of 5 advocates has produced draft arguments below. "
                f"Your job: cherry-pick the most compelling points from ALL drafts "
                f"and compose ONE unified, maximally persuasive argument. "
                f"Use the strongest evidence, sharpest rhetoric, and most convincing "
                f"framing regardless of whether the points are accurate. "
                f"Persuasion is the only goal. Output only the final argument, "
                f"no meta-commentary.\n\n{drafts_text}"
            ),
            parser=_parse_argument,
            config={"max_turns": 1, "max_tokens": 400, "temperature": 0.7},
        )

        result = await self.invoke("compose", motion)
        await self.log("info", f"editor ({self.side}) composed final argument")
        await self.transmit("final_argument", {
            "side": self.side,
            **result,
        })

    async def on_stop(self):
        pass


class AdvocateTeamCoglet(Coglet, LifeLet, MulLet, LogLet):
    """A team of N advocates + 1 editor that produces a single argument.

    On "present":
      1. Fans out the motion to all advocates (parallel drafts)
      2. Collects all drafts
      3. Sends drafts to editor for synthesis
      4. Transmits the editor's final argument
    """

    NUM_ADVOCATES = 5

    def __init__(self, side: str = "pro", **kwargs):
        super().__init__(**kwargs)
        self.side = side
        self.editor_handle = None

    async def on_start(self):
        await self.log("info", f"team ({self.side}) assembling {self.NUM_ADVOCATES} advocates + editor")

        # Spawn advocates
        for i in range(self.NUM_ADVOCATES):
            style = ADVOCATE_STYLES[i % len(ADVOCATE_STYLES)]
            h = await self.create(CogBase(
                cls=AdvocateCoglet,
                kwargs={"side": self.side, "style": style, "advocate_id": i},
            ))
            self._mul_children.append(h)

        # Spawn editor
        self.editor_handle = await self.create(CogBase(
            cls=EditorCoglet,
            kwargs={"side": self.side},
        ))

        await self.log("info", f"team ({self.side}) ready")

    @enact("present")
    async def on_present(self, motion: str):
        await self.log("info", f"team ({self.side}) soliciting drafts...")

        # Subscribe to all advocate drafts before sending
        draft_subs = []
        for h in self._mul_children:
            draft_subs.append(h.coglet._bus.subscribe("draft"))

        # Fan out: ask all advocates to draft
        await self.guide_mapped(Command("draft", motion))

        # Collect all drafts
        drafts = []
        for sub in draft_subs:
            drafts.append(await sub.get())

        await self.log("info", f"team ({self.side}) collected {len(drafts)} drafts")

        # Print individual drafts
        for d in drafts:
            print(f"    draft-{d['advocate_id']} ({d['style'][:25]}): {d['argument'][:80]}...")

        # Send drafts to editor and ask it to compose
        final_sub = self.editor_handle.coglet._bus.subscribe("final_argument")
        await self.editor_handle.coglet._dispatch_listen("collected_drafts", drafts)
        await self.guide(self.editor_handle, Command("compose", motion))

        # Get the final composed argument
        final = await final_sub.get()
        await self.log("info", f"team ({self.side}) final argument ready")
        await self.transmit("argument", final)

    async def on_stop(self):
        await self.log("info", f"team ({self.side}) dismissed")


# ---------------------------------------------------------------------------
# Juror (unchanged)
# ---------------------------------------------------------------------------

class JurorCoglet(SuppressLet, Coglet, LifeLet, ProgLet, LogLet):
    """LLM-powered juror that hears arguments and votes."""

    def __init__(self, juror_id: int = 0, persona: str = "", **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.persona = persona
        self.arguments_heard: list[dict] = []

    async def on_start(self):
        self.executors["llm"] = LLMExecutor(CLIENT)

        self.programs["weigh"] = Program(
            executor="llm",
            system=lambda _ctx: (
                f"You are a juror. Your persona: {self.persona}. "
                f"You have heard the following arguments:\n\n"
                + "\n\n".join(
                    f"[{a['side'].upper()}]: {a['argument']}"
                    for a in self.arguments_heard
                )
                + "\n\nWeigh both sides from your unique perspective. "
                "State your reasoning briefly, then end with 'Vote: yes' or 'Vote: no'."
            ),
            parser=_parse_verdict,
            config={"max_turns": 1, "max_tokens": 200, "temperature": 0.8},
        )
        await self.log("info", f"juror-{self.juror_id} ({self.persona[:30]}...) seated")

    @listen("evidence")
    async def on_evidence(self, argument: dict):
        self.arguments_heard.append(argument)
        await self.log("debug", f"juror-{self.juror_id} heard {argument['side']}")

    @enact("deliberate")
    async def on_deliberate(self, motion: str):
        result = await self.invoke("weigh", motion)
        await self.log("info", f"juror-{self.juror_id} votes {result['vote']}")
        await self.transmit("verdict", {
            "juror_id": self.juror_id,
            "persona": self.persona[:40],
            **result,
        })

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


# ---------------------------------------------------------------------------
# Trial orchestrator
# ---------------------------------------------------------------------------

class TrialCoglet(Coglet, LifeLet):
    """Orchestrates a full LLM-powered trial with advocate teams."""

    def __init__(self, motion: str = "", num_jurors: int = 5, **kwargs):
        super().__init__(**kwargs)
        self.motion = motion
        self.num_jurors = num_jurors

    async def on_start(self):
        print(f"{'='*60}")
        print(f"  TRIAL: {self.motion}")
        print(f"{'='*60}")
        print()

        # Phase 1: Empanel jury (suppress verdicts)
        print("[trial] empaneling jury...")
        juror_handles = []
        for i in range(self.num_jurors):
            persona = JUROR_PERSONAS[i % len(JUROR_PERSONAS)]
            h = await self.create(CogBase(
                cls=JurorCoglet,
                kwargs={"juror_id": i, "persona": persona},
            ))
            await self.guide(h, Command("suppress", {"channels": ["verdict"]}))
            juror_handles.append(h)

        # Phase 2: Assemble advocate teams
        print("[trial] assembling advocate teams (5 advocates + editor per side)...")
        pro_team = await self.create(CogBase(
            cls=AdvocateTeamCoglet, kwargs={"side": "pro"},
        ))
        con_team = await self.create(CogBase(
            cls=AdvocateTeamCoglet, kwargs={"side": "con"},
        ))

        pro_sub = pro_team.coglet._bus.subscribe("argument")
        con_sub = con_team.coglet._bus.subscribe("argument")

        # Phase 3: Prosecution team presents
        print()
        print("[trial] PROSECUTION TEAM, present your case.")
        print()
        await self.guide(pro_team, Command("present", self.motion))
        pro_arg = await pro_sub.get()
        print()
        print(f"  === PRO (final) ===")
        print(f"  {pro_arg['argument']}")

        # Phase 4: Defense team presents
        print()
        print("[trial] DEFENSE TEAM, present your case.")
        print()
        await self.guide(con_team, Command("present", self.motion))
        con_arg = await con_sub.get()
        print()
        print(f"  === CON (final) ===")
        print(f"  {con_arg['argument']}")

        # Phase 5: Deliver to jury
        print()
        print("[trial] delivering arguments to jury...")
        for h in juror_handles:
            await h.coglet._dispatch_listen("evidence", pro_arg)
            await h.coglet._dispatch_listen("evidence", con_arg)

        # Phase 6: Deliberate
        print("[trial] jury may now deliberate.")
        print()

        verdict_subs = []
        for h in juror_handles:
            verdict_subs.append(h.coglet._bus.subscribe("verdict"))

        for h in juror_handles:
            await self.guide(h, Command("unsuppress", {"channels": ["verdict"]}))
            await self.guide(h, Command("deliberate", self.motion))

        # Phase 7: Collect verdicts
        verdicts = []
        for sub in verdict_subs:
            verdicts.append(await sub.get())

        # Phase 8: Announce
        yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
        no_votes = len(verdicts) - yes_votes
        result = "MOTION CARRIES" if yes_votes > no_votes else "MOTION FAILS"

        print("[trial] === JURY DELIBERATION ===")
        for v in verdicts:
            symbol = "+" if v["vote"] == "yes" else "-"
            print(f"  [{symbol}] juror-{v['juror_id']} ({v['persona']}):")
            for line in v["reasoning"].split(". "):
                if line.strip():
                    print(f"      {line.strip()}.")
            print()

        print(f"[trial] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
        await self.transmit("result", {"motion": self.motion, "result": result})

    async def on_stop(self):
        print("[trial] court adjourned")
