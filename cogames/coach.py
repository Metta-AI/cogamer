"""Coach: orchestration script for improving a player in cogames.

The Coach is NOT a Coglet — it's a script (or Claude Code session)
that creates a PlayerCoglet, registers it via GameLet, observes
results, and triggers improvements.
"""
from __future__ import annotations

import asyncio
from typing import Any

from coglet.runtime import CogletRuntime
from coglet.handle import CogletConfig, Command

from cogames.player import PlayerCoglet
from cogames.gamelet import GameLet


async def run_coach(
    repo_path: str,
    llm: Any,
    mission: str = "machina_1",
    season: str | None = None,
    mode: str = "play",
    num_rounds: int = 10,
    improve_every: int = 1,
) -> None:
    """Run the coach loop.

    1. Boot PlayerCoglet + PolicyCoglet
    2. Register via GameLet (play or tournament)
    3. Observe scores
    4. Trigger improvements
    5. Repeat
    """
    runtime = CogletRuntime()

    # Boot player
    player_handle = await runtime.run(
        CogletConfig(cls=PlayerCoglet, kwargs={
            "repo_path": repo_path,
            "llm": llm,
        })
    )
    player: PlayerCoglet = player_handle.coglet

    # Boot gamelet
    game_handle = await runtime.run(
        CogletConfig(cls=GameLet, kwargs={
            "policy_coglet": player.policy,
            "mode": mode,
            "mission": mission,
            "season": season,
        })
    )
    game: GameLet = game_handle.coglet

    if mode == "tournament":
        await game.upload()
        await game.submit()
        await game.start_polling()

    for round_idx in range(num_rounds):
        if mode == "play":
            await game.play()

        # Trigger improvement
        if (round_idx + 1) % improve_every == 0:
            await player_handle.guide(Command("improve"))

    if mode == "tournament":
        await game.stop_polling()

    await runtime.shutdown()


# --- Coach prompt template for Claude Code sessions ---

COACH_PROMPT = """
You are coaching a player in a Softmax cogames tournament.

## Setup
- Player: PlayerCoglet with PolicyCoglet (CodeLet function table)
- GameLet wraps cogames freeplay and tournament APIs

## API
```python
from cogames.coach import run_coach
from cogames.player import PlayerCoglet
from cogames.gamelet import GameLet

# Boot everything
runtime = CogletRuntime()
player_handle = await runtime.run(CogletConfig(cls=PlayerCoglet, kwargs={...}))
game_handle = await runtime.run(CogletConfig(cls=GameLet, kwargs={...}))

# Play locally
await game.play(mission="machina_1", render_mode="vibescope")

# Upload to tournament
await game.upload(name="my-policy-v1", season="cvc-2026")
await game.submit(season="cvc-2026")

# Observe results
async for score in player_handle.observe("score"):
    print(score)

# Improve policy
await player_handle.guide(Command("patch", {"step": new_step_fn}))
await player_handle.guide(Command("improve"))
```

## Loop
1. Register the player in freeplay via GameLet
2. Observe scores from practice games
3. Analyze what the player is doing wrong
4. Write new functions to improve the policy
5. Call player.enact("patch", {functions}) to apply
6. Repeat until scores improve
7. When ready, upload to tournament via GameLet
8. Continue observing and improving between rounds
"""
