"""Printer — listens on 'input' and prints each value."""

from coglet import Coglet, LifeLet, listen


class PrinterCoglet(Coglet, LifeLet):
    def __init__(self, label: str = "printer", **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.received = 0

    async def on_start(self):
        print(f"[printer:{self.label}] started")

    @listen("input")
    async def on_input(self, value):
        self.received += 1
        print(f"[printer:{self.label}] #{self.received}: {value}")
        await self.transmit("output", {"label": self.label, "n": self.received, "value": value})

    async def on_stop(self):
        print(f"[printer:{self.label}] stopped after {self.received} events")
