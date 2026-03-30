"""Counter — generates incrementing numbers. Thin wrapper around GeneratorCoglet."""

import sys
from pathlib import Path

from coglet import Coglet, LifeLet, TickLet, ProgLet, LogLet, Program, every

_gen_dir = str(Path(__file__).parent.parent / "generator.cog")
if _gen_dir not in sys.path:
    sys.path.insert(0, _gen_dir)
from generator import GeneratorCoglet


class CounterCoglet(GeneratorCoglet):
    """Generates incrementing numbers on the output channel.

    Args:
        start: starting number (default 0)
        end: ending number (default 1000)
        interval_s: seconds between numbers (default 1)
    """

    def __init__(self, start: int = 0, end: int = 1000, interval_s: int = 1, **kwargs):
        super().__init__(
            prompt=f"numbers from {start} to {end}",
            interval_s=interval_s,
            executor="code",
            **kwargs,
        )
        self.start = start
        self.end = end
        self._seed_list = [str(i) for i in range(start, end)]
