from __future__ import annotations

from typing import Any, Callable

from coglet.coglet import Coglet, listen, enact
from coglet.codelet import CodeLet
from coglet.lifelet import LifeLet
from coglet.ticklet import TickLet, every


class PolicyCoglet(Coglet, CodeLet, LifeLet, TickLet):
    """Innermost execution layer for cogames.

    Holds a mutable function table (CodeLet) whose "step" function
    is called on each observation. Implements the bridge between
    Coglet channels and the cogames MultiAgentPolicy interface.

    The LLM can rewrite functions via @enact("register").
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.history: list[dict] = []

    @listen("obs")
    async def handle_obs(self, data: Any) -> None:
        step_fn = self.functions.get("step")
        if step_fn is None:
            return
        action = step_fn(data)
        await self.transmit("action", action)
        await self.tick()

    @listen("score")
    async def handle_score(self, data: Any) -> None:
        self.history.append({"type": "score", "data": data})
        await self.transmit("score", data)

    @listen("replay")
    async def handle_replay(self, data: Any) -> None:
        self.history.append({"type": "replay", "data": data})


class PolicyAdapter:
    """Adapts a PolicyCoglet to the cogames MultiAgentPolicy interface.

    cogames calls:
        policy = PolicyAdapter(policy_env_info, ...)
        agent = policy.agent_policy(agent_id)
        action = agent.step(obs)

    Under the hood this dispatches through the PolicyCoglet's channels.
    """

    def __init__(self, coglet: PolicyCoglet, policy_env_info: Any = None,
                 device: str = "cpu", **kwargs: Any):
        self._coglet = coglet
        self._policy_env_info = policy_env_info
        self._agents: dict[int, AgentAdapter] = {}

    def agent_policy(self, agent_id: int) -> AgentAdapter:
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentAdapter(self._coglet, agent_id)
        return self._agents[agent_id]

    def reset(self) -> None:
        self._coglet.history.clear()

    @property
    def short_names(self) -> list[str]:
        return ["coglet-policy"]


class AgentAdapter:
    """Per-agent adapter bridging cogames AgentPolicy.step() to PolicyCoglet."""

    def __init__(self, coglet: PolicyCoglet, agent_id: int):
        self._coglet = coglet
        self._agent_id = agent_id
        self._action_sub = coglet._bus.subscribe("action")

    def step(self, obs: Any) -> Any:
        """Synchronous step for cogames compatibility.

        Dispatches obs into the coglet's @listen("obs"), then
        reads the action from the "action" channel.
        """
        step_fn = self._coglet.functions.get("step")
        if step_fn is None:
            return None
        return step_fn(obs)

    def reset(self, simulation: Any = None) -> None:
        pass

    @property
    def infos(self) -> dict[str, Any]:
        return {}
