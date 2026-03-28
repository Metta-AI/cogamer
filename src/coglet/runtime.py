from __future__ import annotations

import asyncio
from typing import Any

from coglet.coglet import Coglet
from coglet.handle import CogletConfig, CogletHandle
from coglet.lifelet import LifeLet
from coglet.ticklet import TickLet


class CogletRuntime:
    """Boots and manages a Coglet tree on asyncio."""

    def __init__(self):
        self._handles: list[CogletHandle] = []
        self._coglets: list[Coglet] = []

    def _instantiate(self, config: CogletConfig) -> Coglet:
        coglet = config.cls(**config.kwargs)
        coglet._runtime = self
        return coglet

    async def spawn(self, config: CogletConfig, parent: Coglet | None = None) -> CogletHandle:
        coglet = self._instantiate(config)
        handle = CogletHandle(coglet)
        self._handles.append(handle)
        self._coglets.append(coglet)

        if isinstance(coglet, LifeLet):
            await coglet.on_start()

        if isinstance(coglet, TickLet):
            await coglet._start_tickers()

        return handle

    async def run(self, config: CogletConfig) -> CogletHandle:
        """Boot a root coglet and return its handle."""
        return await self.spawn(config)

    async def shutdown(self) -> None:
        """Stop all coglets in reverse order."""
        for coglet in reversed(self._coglets):
            if isinstance(coglet, TickLet):
                await coglet._stop_tickers()
            if isinstance(coglet, LifeLet):
                await coglet.on_stop()
        self._coglets.clear()
        self._handles.clear()
