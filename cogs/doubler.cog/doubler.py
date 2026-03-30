"""Doubler — listens on 'input', doubles the value, transmits on 'output'."""

from coglet import Coglet, LifeLet, listen


class DoublerCoglet(Coglet, LifeLet):
    async def on_start(self):
        print("[doubler] started")

    @listen("input")
    async def on_input(self, n):
        result = n * 2
        await self.transmit("output", result)

    async def on_stop(self):
        print("[doubler] stopped")
