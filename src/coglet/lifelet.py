from __future__ import annotations

from typing import Any


class LifeLet:
    """Mixin: process lifecycle hooks.

    on_start() — called when the coglet process starts.
    on_stop()  — called on shutdown.
    Raising in either aborts the transition.
    """

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass
