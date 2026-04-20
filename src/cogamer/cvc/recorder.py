"""GameRecorder: per-step observable state log with query helpers.

Stores a StepRecord every tick from the agent's own observations.
The full log is iterable. Convenience query methods filter/aggregate
on top of the raw data.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from mettagrid.sdk.agent import MettagridState

from cogamer.cvc.agent import absolute_position, attr_int, attr_str, manhattan, team_id
from cogamer.cvc.agent.types import _ELEMENTS


@dataclass(slots=True)
class StepRecord:
    step: int
    position: tuple[int, int]
    hp: int
    inventory: dict[str, int]
    team_resources: dict[str, int]
    role_counts: dict[str, int]
    enemy_positions: list[tuple[int, int]]
    junction_owners: dict[tuple[int, int], str | None]


@dataclass(slots=True)
class JunctionEvent:
    step: int
    position: tuple[int, int]
    old_owner: str | None
    new_owner: str | None


class GameRecorder:
    """Per-step game state log from an agent's perspective.

    Iterable over StepRecord entries. Query methods are convenience
    filters — the raw log is the primary interface.
    """

    def __init__(self) -> None:
        self._records: list[StepRecord] = []
        self._junction_events: list[JunctionEvent] = []
        self._prev_junction_owners: dict[tuple[int, int], str | None] = {}
        self._positions: set[tuple[int, int]] = set()

    def reset(self) -> None:
        self._records.clear()
        self._junction_events.clear()
        self._prev_junction_owners.clear()
        self._positions.clear()

    def record_step(
        self,
        state: MettagridState,
        junctions: dict[tuple[int, int], tuple[str | None, int]],
        hub_position: tuple[int, int] | None,
    ) -> None:
        step = state.step or 0
        pos = absolute_position(state)
        team = team_id(state)

        self._positions.add(pos)

        # Inventory
        inventory = {k: int(v) for k, v in state.self_state.inventory.items()}

        # Team resources
        team_resources: dict[str, int] = {}
        if state.team_summary is not None:
            team_resources = {
                e: int(state.team_summary.shared_inventory.get(e, 0))
                for e in _ELEMENTS
            }

        # Role counts
        role_counts: dict[str, int] = {}
        if state.team_summary is not None:
            for member in state.team_summary.members:
                role_counts[member.role] = role_counts.get(member.role, 0) + 1

        # Enemy positions
        enemy_positions: list[tuple[int, int]] = []
        for entity in state.visible_entities:
            if entity.entity_type != "agent":
                continue
            if attr_str(entity, "team") == team:
                continue
            enemy_positions.append((
                attr_int(entity, "global_x", entity.position.x),
                attr_int(entity, "global_y", entity.position.y),
            ))

        # Junction snapshot (relative -> absolute)
        junction_owners: dict[tuple[int, int], str | None] = {}
        if hub_position is not None:
            for (dx, dy), (owner, _) in junctions.items():
                abs_pos = (hub_position[0] + dx, hub_position[1] + dy)
                junction_owners[abs_pos] = owner
                # Detect ownership changes
                prev_owner = self._prev_junction_owners.get(abs_pos)
                if prev_owner != owner:
                    self._junction_events.append(JunctionEvent(
                        step=step,
                        position=abs_pos,
                        old_owner=prev_owner,
                        new_owner=owner,
                    ))
            self._prev_junction_owners = dict(junction_owners)

        self._records.append(StepRecord(
            step=step,
            position=pos,
            hp=inventory.get("hp", 0),
            inventory=inventory,
            team_resources=team_resources,
            role_counts=role_counts,
            enemy_positions=enemy_positions,
            junction_owners=junction_owners,
        ))

    # ── Iteration ────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[StepRecord]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, index: int | slice) -> StepRecord | list[StepRecord]:
        return self._records[index]

    def steps(self, *, last_n: int | None = None) -> list[StepRecord]:
        if last_n is None:
            return list(self._records)
        return self._records[-last_n:]

    # ── Convenience queries ──────────────────────────────────────────

    def junction_events(self, *, last_n_steps: int | None = None, step: int = 0) -> list[JunctionEvent]:
        if last_n_steps is None:
            return list(self._junction_events)
        cutoff = step - last_n_steps
        return [e for e in self._junction_events if e.step >= cutoff]

    def junction_losses(self, *, team: str, last_n_steps: int | None = None, step: int = 0) -> list[JunctionEvent]:
        events = self.junction_events(last_n_steps=last_n_steps, step=step)
        return [e for e in events if e.old_owner == team and e.new_owner != team]

    def junction_gains(self, *, team: str, last_n_steps: int | None = None, step: int = 0) -> list[JunctionEvent]:
        events = self.junction_events(last_n_steps=last_n_steps, step=step)
        return [e for e in events if e.old_owner != team and e.new_owner == team]

    def enemy_sightings(
        self,
        *,
        near: tuple[int, int] | None = None,
        radius: int = 15,
        last_n: int | None = None,
    ) -> list[tuple[int, tuple[int, int]]]:
        """Returns (step, position) pairs for enemy sightings."""
        records = self._records if last_n is None else self._records[-last_n:]
        result: list[tuple[int, tuple[int, int]]] = []
        for r in records:
            for pos in r.enemy_positions:
                if near is not None and manhattan(near, pos) > radius:
                    continue
                result.append((r.step, pos))
        return result

    def unique_positions_visited(self) -> int:
        return len(self._positions)

    # ── Serialization ────────────────────────────────────────────────

    @staticmethod
    def _serialize_record(r: StepRecord) -> dict:
        return {
            "step": r.step,
            "position": list(r.position),
            "hp": r.hp,
            "inventory": r.inventory,
            "team_resources": r.team_resources,
            "role_counts": r.role_counts,
            "enemy_positions": [list(p) for p in r.enemy_positions],
            "junction_owners": {
                f"{x},{y}": owner for (x, y), owner in r.junction_owners.items()
            },
        }

    @staticmethod
    def _serialize_junction_event(e: JunctionEvent) -> dict:
        return {
            "step": e.step,
            "position": list(e.position),
            "old_owner": e.old_owner,
            "new_owner": e.new_owner,
        }

    def dump(self, path: str | Path) -> None:
        """Write game log to JSONL. One StepRecord per line."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for r in self._records:
                f.write(json.dumps(self._serialize_record(r)) + "\n")

    def dump_events(self, path: str | Path) -> None:
        """Write junction events to JSONL."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for e in self._junction_events:
                f.write(json.dumps(self._serialize_junction_event(e)) + "\n")
