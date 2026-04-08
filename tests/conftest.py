"""Shared test fixtures for CvC policy tests."""

from __future__ import annotations

import pytest

from cogamer.cvc.agent.types import KnownEntity
from mettagrid.sdk.agent import (
    GridPosition,
    MettagridState,
    SelfState,
    SemanticEntity,
    TeamMemberSummary,
    TeamSummary,
)
from mettagrid.sdk.agent.state import KnownWorldState

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")


@pytest.fixture
def make_state():
    """Factory for MettagridState with sensible defaults."""

    def _make(
        *,
        hp: int = 100,
        global_x: int = 44,
        global_y: int = 44,
        team: str = "team_0",
        step: int = 500,
        inventory: dict | None = None,
        shared_inventory: dict | None = None,
        visible_entities: list[SemanticEntity] | None = None,
        members: list[TeamMemberSummary] | None = None,
        team_summary: TeamSummary | None = ...,  # sentinel
    ) -> MettagridState:
        inv: dict[str, int] = {
            "hp": hp,
            "heart": 0,
            "carbon": 0,
            "oxygen": 0,
            "germanium": 0,
            "silicon": 0,
        }
        if inventory:
            inv.update(inventory)

        shared_inv: dict[str, int] = {
            "carbon": 10,
            "oxygen": 10,
            "germanium": 10,
            "silicon": 10,
            "heart": 5,
        }
        if shared_inventory:
            shared_inv.update(shared_inventory)

        if team_summary is ...:
            team_summary = TeamSummary(
                team_id=team,
                members=members or [],
                shared_inventory=shared_inv,
            )

        return MettagridState(
            game="cogsguard",
            step=step,
            self_state=SelfState(
                entity_id="agent_0",
                entity_type="agent",
                position=GridPosition(x=0, y=0),
                inventory=inv,
                attributes={"global_x": global_x, "global_y": global_y, "team": team},
            ),
            visible_entities=visible_entities or [],
            known_world=KnownWorldState(),
            team_summary=team_summary,
        )

    return _make


@pytest.fixture
def make_entity():
    """Factory for KnownEntity."""

    def _make(
        entity_type: str = "junction",
        x: int = 50,
        y: int = 50,
        team: str | None = None,
        owner: str | None = None,
        last_seen_step: int = 100,
        **attrs,
    ) -> KnownEntity:
        return KnownEntity(
            entity_type=entity_type,
            global_x=x,
            global_y=y,
            labels=(),
            team=team,
            owner=owner,
            last_seen_step=last_seen_step,
            attributes=attrs,
        )

    return _make


@pytest.fixture
def make_semantic_entity():
    """Factory for SemanticEntity (for WorldModel tests)."""

    def _make(
        entity_type: str = "junction",
        x: int = 50,
        y: int = 50,
        entity_id: str = "",
        **attrs,
    ) -> SemanticEntity:
        if not entity_id:
            entity_id = f"{entity_type}@{x},{y}"
        all_attrs: dict[str, str | int | float | bool] = {
            "global_x": x,
            "global_y": y,
        }
        all_attrs.update(attrs)
        return SemanticEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            position=GridPosition(x=x, y=y),
            labels=[],
            attributes=all_attrs,
        )

    return _make
