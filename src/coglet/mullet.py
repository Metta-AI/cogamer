"""MulLet mixin — fan-out N identical children with scatter/gather.

The parent COG creates N children via create_mul() and coordinates them with
map/reduce semantics. scatter() distributes events via the runtime channel
mechanism, gather() collects one result from each child.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from coglet.handle import CogBase, CogletHandle, Command

if TYPE_CHECKING:
    from coglet.coglet import Coglet


class MulLet:
    """Mixin: fan-out N identical children behind one CogletHandle.

    Must be mixed with Coglet to access create()/guide()/send().
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._mul_children: list[CogletHandle] = []

    async def create_mul(self, n: int, config: CogBase) -> None:
        for _ in range(n):
            handle: CogletHandle = await self.create(config)  # type: ignore[attr-defined]
            self._mul_children.append(handle)

    def map(self, event: Any) -> list[tuple[int, Any]]:
        """Route an incoming event to children. Default: broadcast to all."""
        return [(i, event) for i in range(len(self._mul_children))]

    def reduce(self, results: list[Any]) -> Any:
        """Aggregate child outputs. Default: return list as-is."""
        return results

    async def guide_mapped(self, command: Command) -> None:
        """Guide all children with the same command."""
        for handle in self._mul_children:
            await self.guide(handle, command)  # type: ignore[attr-defined]

    async def scatter(self, channel: str, event: Any) -> None:
        """Scatter an event to children via runtime.send()."""
        mappings = self.map(event)
        for child_idx, child_event in mappings:
            handle = self._mul_children[child_idx]
            await self.send(handle, channel, child_event)  # type: ignore[attr-defined]

    async def gather(self, channel: str) -> Any:
        """Collect one result from each child via observe_one(), then reduce."""
        futures = [h.observe_one(channel) for h in self._mul_children]
        results = [await f for f in futures]
        return self.reduce(results)
