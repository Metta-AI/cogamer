from __future__ import annotations

from typing import Any

from coglet.coglet import Coglet, listen, enact
from coglet.gitlet import GitLet
from coglet.lifelet import LifeLet
from coglet.ticklet import TickLet, every
from coglet.handle import CogletConfig, CogletHandle, Command

from cogames.policy import PolicyCoglet


class PlayerCoglet(Coglet, GitLet, LifeLet, TickLet):
    """COG over PolicyCoglet.

    Supervises a PolicyCoglet. Accumulates scores and replays.
    Periodically (or on Coach command) triggers LLM to generate
    patches from history, then applies them to the policy.
    """

    def __init__(self, repo_path: str | None = None,
                 llm: Any = None,
                 improve_interval_m: int = 10,
                 **kwargs: Any) -> None:
        super().__init__(repo_path=repo_path, **kwargs)
        self.llm = llm
        self.history: list[dict] = []
        self._policy_handle: CogletHandle | None = None
        self._improve_interval_m = improve_interval_m

    async def on_start(self) -> None:
        self._policy_handle = await self.create(
            CogletConfig(cls=PolicyCoglet)
        )

    @property
    def policy(self) -> PolicyCoglet:
        if self._policy_handle is None:
            raise RuntimeError("PlayerCoglet not started")
        return self._policy_handle.coglet

    @listen("score")
    async def handle_score(self, data: Any) -> None:
        self.history.append({"type": "score", "data": data})

    @listen("replay")
    async def handle_replay(self, data: Any) -> None:
        self.history.append({"type": "replay", "data": data})

    @listen("logs")
    async def handle_logs(self, data: Any) -> None:
        self.history.append({"type": "logs", "data": data})

    @enact("patch")
    async def handle_patch(self, patch: Any) -> None:
        """Coach (Claude Code) can direct improvements via patches."""
        if self._policy_handle is None:
            raise RuntimeError("PlayerCoglet not started")
        await self.guide(
            self._policy_handle,
            Command("register", patch)
        )

    @enact("improve")
    async def handle_improve(self, _: Any = None) -> None:
        """Trigger an improvement cycle using LLM."""
        if not self.history or self.llm is None:
            return
        patch = await self._generate_patch()
        if patch and self._policy_handle is not None:
            await self.guide(
                self._policy_handle,
                Command("register", patch)
            )
            self.history.clear()

    async def _generate_patch(self) -> dict[str, Any] | None:
        """Ask LLM to generate improved functions from history."""
        if self.llm is None:
            return None
        # LLM interface: takes history, returns dict of function name -> callable
        if hasattr(self.llm, "generate_patch"):
            result = self.llm.generate_patch(self.history)
            if hasattr(result, "__await__"):
                result = await result
            return result
        return None
