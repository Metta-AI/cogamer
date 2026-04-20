"""GameState: thin adapter wrapping CogletAgentPolicy engine.

Wraps the engine internally for its A* pathfinder, world model, stall
detection, targeting, and all role-specific action logic.  Programs call
GameState methods which delegate to the engine's working infrastructure.
"""

from __future__ import annotations

from typing import Any

from cogamer.cvc.agent import (
    KnownEntity,
    absolute_position,
    has_role_gear,
    inventory_signature,
    is_usable_recent_extractor,
    manhattan,
    needs_emergency_mining,
    resource_priority,
    team_can_afford_gear,
    team_id,
    within_alignment_network,
    _GEAR_COSTS,
    _ELEMENTS,
    _JUNCTION_ALIGN_DISTANCE,
)
from cogamer.cvc.agent.coglet_policy import CogletAgentPolicy
from cogamer.cvc.agent.world_model import WorldModel
from cogamer.cvc.recorder import GameRecorder
from cogames.sdk.cogsguard import CogsguardSemanticSurface
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent import MettagridState
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

_COGSGUARD_SURFACE = CogsguardSemanticSurface()


class GameState:
    """Thin adapter over CogletAgentPolicy — one per agent per episode.

    Programs read properties and call action methods here; everything
    delegates to the engine's proven A* pathfinding and role logic.
    """

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        *,
        agent_id: int,
        shared_junctions: dict[tuple[int, int], tuple[str | None, int]] | None = None,
        shared_claims: dict[tuple[int, int], tuple[int, int]] | None = None,
    ) -> None:
        self.engine = CogletAgentPolicy(
            policy_env_info,
            agent_id=agent_id,
            world_model=WorldModel(),
            shared_junctions=shared_junctions,
            shared_claims=shared_claims,
        )
        self.agent_id = agent_id
        self.role: str = "miner"
        self.mg_state: MettagridState | None = None
        self.recorder = GameRecorder()

        # Expose action validation info for backward compat
        self.action_names: set[str] = set(policy_env_info.action_names)
        self.vibe_actions: set[str] = set(policy_env_info.vibe_action_names)
        self.fallback: str = "noop" if "noop" in self.action_names else policy_env_info.action_names[0]

    # ── Observation processing ────────────────────────────────────────

    def process_obs(self, obs: AgentObservation) -> MettagridState:
        """Process observation using engine internals, but skip _choose_action.

        Mirrors the first half of CvcEngine.evaluate_state():
        build state, update world model, update junctions, navigation
        counters, stall detection, directive setup.
        """
        engine = self.engine

        engine._step_index += 1
        state = _COGSGUARD_SURFACE.build_state_with_events(
            obs,
            policy_env_info=engine.policy_env_info,
            step=engine._step_index,
            previous_state=engine._previous_state,
        )

        # World model update
        engine._world_model.update(state)
        engine._update_junctions(state)
        current_pos = absolute_position(state)

        # Navigation infrastructure
        engine._update_temp_blocks(current_pos)
        engine._update_stall_counter(state, current_pos)

        # Reset per-tick targeting
        engine._current_target_position = None
        engine._current_target_kind = None

        # Collect events
        engine._events.extend(state.recent_events)

        # Set up directive (resource bias, etc.) — mirrors evaluate_state
        directive = engine._sanitize_macro_directive(engine._macro_directive(state))
        engine._current_directive = directive
        engine._resource_bias = (
            engine._default_resource_bias if directive.resource_bias is None else directive.resource_bias
        )

        # Store for bookkeeping at end of step
        self.mg_state = state

        # Record events for query tooling (hub already computed by _update_junctions)
        hub = getattr(engine, "_last_hub", None)
        hub_pos = hub.position if hub else None
        self.recorder.record_step(state, engine._junctions, hub_pos)

        return state

    def finalize_step(self, summary: str) -> None:
        """Bookkeep after action selection — mirrors end of evaluate_state."""
        engine = self.engine
        state = self.mg_state
        if state is None:
            return
        current_pos = absolute_position(state)
        engine._record_navigation_observation(current_pos, summary)
        engine._previous_state = state
        engine._last_global_pos = current_pos
        engine._last_inventory_signature = inventory_signature(state)

    # ── Properties delegating to engine/state ─────────────────────────

    @property
    def step_index(self) -> int:
        return self.engine._step_index

    @step_index.setter
    def step_index(self, value: int) -> None:
        self.engine._step_index = value

    @property
    def hp(self) -> int:
        if self.mg_state is None:
            return 0
        return int(self.mg_state.self_state.inventory.get("hp", 0))

    @property
    def position(self) -> tuple[int, int]:
        if self.mg_state is None:
            return (0, 0)
        return absolute_position(self.mg_state)

    @property
    def resource_bias(self) -> str:
        return self.engine._resource_bias

    @resource_bias.setter
    def resource_bias(self, value: str) -> None:
        self.engine._resource_bias = value

    @property
    def world_model(self) -> WorldModel:
        return self.engine._world_model

    @property
    def stalled_steps(self) -> int:
        return self.engine._stalled_steps

    @stalled_steps.setter
    def stalled_steps(self, value: int) -> None:
        self.engine._stalled_steps = value

    @property
    def oscillation_steps(self) -> int:
        return self.engine._oscillation_steps

    @oscillation_steps.setter
    def oscillation_steps(self, value: int) -> None:
        self.engine._oscillation_steps = value

    @property
    def explore_index(self) -> int:
        return self.engine._explore_index

    @explore_index.setter
    def explore_index(self, value: int) -> None:
        self.engine._explore_index = value

    # ── Delegate infrastructure methods to engine ─────────────────────

    def move_to_known(
        self, entity: KnownEntity, *, summary: str = "move", vibe: str | None = None
    ) -> tuple[Action, str]:
        """A* pathfinding to a known entity."""
        assert self.mg_state is not None
        return self.engine._move_to_known(self.mg_state, entity, summary=summary, vibe=vibe)

    def move_to_position(
        self, target: tuple[int, int], *, summary: str = "move", vibe: str | None = None
    ) -> tuple[Action, str]:
        """A* pathfinding to a position."""
        assert self.mg_state is not None
        return self.engine._move_to_position(self.mg_state, target, summary=summary, vibe=vibe)

    def hold(self, *, summary: str = "hold", vibe: str | None = None) -> tuple[Action, str]:
        return self.engine._hold(summary=summary, vibe=vibe)

    def nearest_hub(self) -> KnownEntity | None:
        assert self.mg_state is not None
        return self.engine._nearest_hub(self.mg_state)

    def nearest_friendly_depot(self) -> KnownEntity | None:
        assert self.mg_state is not None
        return self.engine._nearest_friendly_depot(self.mg_state)

    def explore(self, role: str = "miner") -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._explore_action(self.mg_state, role=role, summary="explore")

    def unstick(self, role: str = "miner") -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._unstick_action(self.mg_state, role)

    def should_retreat(self) -> bool:
        assert self.mg_state is not None
        safe_target = self.nearest_hub()
        return self.engine._should_retreat(self.mg_state, self.role, safe_target)

    def desired_role(self, objective: str | None = None) -> str:
        assert self.mg_state is not None
        return self.engine._desired_role(self.mg_state, objective=objective)

    def miner_action(self, summary_prefix: str = "") -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._miner_action(self.mg_state, summary_prefix=summary_prefix)

    def aligner_action(self) -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._aligner_action(self.mg_state)

    def scrambler_action(self) -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._scrambler_action(self.mg_state)

    def acquire_role_gear(self, role: str) -> tuple[Action, str]:
        assert self.mg_state is not None
        return self.engine._acquire_role_gear(self.mg_state, role)

    def choose_action(self, role: str) -> tuple[Action, str]:
        """Full engine decision tree — delegates to engine._choose_action."""
        assert self.mg_state is not None
        return self.engine._choose_action(self.mg_state, role)

    # ── Helper delegates ──────────────────────────────────────────────

    def has_role_gear(self, role: str) -> bool:
        assert self.mg_state is not None
        return has_role_gear(self.mg_state, role)

    def team_can_afford_gear(self, role: str) -> bool:
        assert self.mg_state is not None
        return team_can_afford_gear(self.mg_state, role)

    def needs_emergency_mining(self) -> bool:
        assert self.mg_state is not None
        return needs_emergency_mining(self.mg_state)

    def resource_priority(self) -> list[str]:
        assert self.mg_state is not None
        return resource_priority(self.mg_state, resource_bias=self.resource_bias)

    def nearest_extractor(self, resource: str) -> KnownEntity | None:
        assert self.mg_state is not None
        current_pos = absolute_position(self.mg_state)
        return self.world_model.nearest(
            position=current_pos,
            entity_type=f"{resource}_extractor",
            predicate=lambda e: is_usable_recent_extractor(e, step=self.step_index),
        )

    def known_junctions(self, predicate: Any = None) -> list[KnownEntity]:
        assert self.mg_state is not None
        if predicate is None:
            predicate = lambda e: True  # noqa: E731
        return self.engine._known_junctions(self.mg_state, predicate=predicate)

    def known_entities(self, entity_type: str | None = None) -> list[KnownEntity]:
        """All entities the agent has ever seen, optionally filtered by type."""
        return self.world_model.entities(entity_type=entity_type)

    def nearest_entity(
        self,
        entity_type: str | None = None,
        position: tuple[int, int] | None = None,
    ) -> KnownEntity | None:
        """Nearest known entity, optionally filtered by type. Defaults to agent's current position."""
        if position is None:
            assert self.mg_state is not None
            position = absolute_position(self.mg_state)
        return self.world_model.nearest(position=position, entity_type=entity_type)

    def team_id(self) -> str:
        assert self.mg_state is not None
        return team_id(self.mg_state)

    def teammate_roles(self) -> list[KnownEntity]:
        """Last observed state for each teammate ever seen.

        Role is in entity.attributes["role"]. Position updates when
        the teammate re-enters viewport. Check .last_seen_step for freshness.
        """
        assert self.mg_state is not None
        return self.world_model.agents(team=team_id(self.mg_state))

    def enemy_agents(self) -> list[KnownEntity]:
        """Last observed state for each enemy agent ever seen."""
        assert self.mg_state is not None
        own_team = team_id(self.mg_state)
        return [a for a in self.world_model.agents() if a.team != own_team]

    def teammate_role_counts(self) -> dict[str, int]:
        """Role distribution across all teammates ever observed."""
        counts: dict[str, int] = {}
        for entity in self.teammate_roles():
            role = str(entity.attributes.get("role", "unknown"))
            counts[role] = counts.get(role, 0) + 1
        return counts

    def agent_sightings(self, entity_id: str, *, last_n: int | None = None) -> list[KnownEntity]:
        """Full sighting history for one agent."""
        return self.world_model.agent_sightings(entity_id, last_n=last_n)

    def sightings_near(
        self,
        position: tuple[int, int],
        *,
        radius: int = 15,
        team: str | None = None,
        last_n_steps: int | None = None,
    ) -> list[KnownEntity]:
        """All agent sightings within radius of a position, optionally recent only."""
        since = 0 if last_n_steps is None else self.step_index - last_n_steps
        return self.world_model.sightings_near(position, radius=radius, team=team, since_step=since)

    # ── Junction Contestedness ───────────────────────────────────────

    def junction_churn(self, position: tuple[int, int], last_n_steps: int = 500) -> int:
        """Ownership changes at this junction in the last N steps."""
        events = self.recorder.junction_events(last_n_steps=last_n_steps, step=self.step_index)
        return sum(1 for e in events if e.position == position)

    def contested_junctions(self, last_n_steps: int = 500, min_changes: int = 2) -> list[tuple[tuple[int, int], int]]:
        """Junctions ranked by churn (descending). High churn = resource sink."""
        events = self.recorder.junction_events(last_n_steps=last_n_steps, step=self.step_index)
        counts: dict[tuple[int, int], int] = {}
        for e in events:
            counts[e.position] = counts.get(e.position, 0) + 1
        return sorted(
            ((pos, n) for pos, n in counts.items() if n >= min_changes),
            key=lambda t: -t[1],
        )

    # ── Game Tempo ───────────────────────────────────────────────────

    def junction_balance(self) -> tuple[int, int, int]:
        """(friendly, enemy, neutral) junction counts from shared junction dict."""
        assert self.mg_state is not None
        team = team_id(self.mg_state)
        friendly = enemy = neutral = 0
        for (owner, _step) in self.engine._junctions.values():
            if owner is None:
                neutral += 1
            elif owner == team:
                friendly += 1
            else:
                enemy += 1
        return (friendly, enemy, neutral)

    def junction_trend(self, last_n_steps: int = 500) -> int:
        """Net junction gains minus losses. Positive = gaining ground."""
        assert self.mg_state is not None
        team = team_id(self.mg_state)
        gains = self.recorder.junction_gains(team=team, last_n_steps=last_n_steps, step=self.step_index)
        losses = self.recorder.junction_losses(team=team, last_n_steps=last_n_steps, step=self.step_index)
        return len(gains) - len(losses)

    # ── Resource Gap ─────────────────────────────────────────────────

    def resource_gap(self, role: str) -> dict[str, int]:
        """Per-element shortfall for gear. Empty dict if affordable."""
        assert self.mg_state is not None
        costs = _GEAR_COSTS.get(role)
        if costs is None:
            return {}
        inventory = {} if self.mg_state.team_summary is None else self.mg_state.team_summary.shared_inventory
        gap: dict[str, int] = {}
        for resource, needed in costs.items():
            have = int(inventory.get(resource, 0))
            if have < needed:
                gap[resource] = needed - have
        return gap

    def mining_trips_needed(self, role: str) -> int:
        """Estimated mining trips to afford gear (10 per trip with miner gear, 1 without)."""
        assert self.mg_state is not None
        gap = self.resource_gap(role)
        if not gap:
            return 0
        worst = max(gap.values())
        yield_per_trip = 10 if has_role_gear(self.mg_state, "miner") else 1
        return (worst + yield_per_trip - 1) // yield_per_trip

    # ── Threat Assessment ────────────────────────────────────────────

    def enemy_activity(self, position: tuple[int, int], radius: int = 15, last_n_steps: int = 200) -> int:
        """Enemy sighting count near position in recent history."""
        assert self.mg_state is not None
        own_team = team_id(self.mg_state)
        since = self.step_index - last_n_steps
        sightings = self.world_model.sightings_near(position, radius=radius, since_step=since)
        return sum(1 for s in sightings if s.team != own_team)

    def safest_target(self, candidates: list[KnownEntity], last_n_steps: int = 200) -> KnownEntity | None:
        """Candidate with lowest nearby enemy activity."""
        if not candidates:
            return None
        return min(candidates, key=lambda c: self.enemy_activity(c.position, last_n_steps=last_n_steps))

    # ── Network Topology ─────────────────────────────────────────────

    def frontier_junctions(self) -> list[KnownEntity]:
        """Neutral junctions within alignment range of our network — capturable now."""
        assert self.mg_state is not None
        team = team_id(self.mg_state)
        friendly = self.known_junctions(predicate=lambda e: e.owner == team)
        hub = self.nearest_hub()
        sources: list[KnownEntity] = list(friendly)
        if hub is not None:
            sources.append(hub)
        neutrals = self.known_junctions(predicate=lambda e: e.owner is None)
        return [j for j in neutrals if within_alignment_network(j.position, sources)]

    def isolated_junctions(self) -> list[KnownEntity]:
        """Our junctions with no adjacent friendly junction — vulnerable to cascade disconnect."""
        assert self.mg_state is not None
        team = team_id(self.mg_state)
        friendly = self.known_junctions(predicate=lambda e: e.owner == team)
        positions = {j.position for j in friendly}
        result = []
        for j in friendly:
            has_neighbor = any(
                manhattan(j.position, other) <= _JUNCTION_ALIGN_DISTANCE
                for other in positions
                if other != j.position
            )
            if not has_neighbor:
                result.append(j)
        return result

    # ── Heart Economy ─────────────────────────────────────────────────

    def heart_pressure(self) -> tuple[int, int]:
        """(hearts_held, hearts_craftable_from_hub). Each heart costs 7 of every element."""
        assert self.mg_state is not None
        held = int(self.mg_state.self_state.inventory.get("heart", 0))
        if self.mg_state.team_summary is None:
            return (held, 0)
        inventory = self.mg_state.team_summary.shared_inventory
        hub_hearts = int(inventory.get("heart", 0))
        min_resource = min(int(inventory.get(e, 0)) for e in _ELEMENTS)
        return (held, hub_hearts + min_resource // 7)

    # ── Role Gap ─────────────────────────────────────────────────────

    def role_gap(self) -> dict[str, int]:
        """Desired minus actual role counts. Positive = underserved.

        WARNING: Use as a soft signal, not a hard constraint. If multiple
        agents independently force-switch to fill a gap on the same tick,
        they overshoot and create the opposite gap, causing a role-cycling
        loop. Prefer gentle nudges (e.g. only switch if gap >= 2) and
        hysteresis (don't switch back within N steps of switching).
        """
        assert self.mg_state is not None
        desired = self.engine._pressure_budgets(self.mg_state)
        actual = self.teammate_role_counts()
        roles = set(desired) | set(actual)
        return {r: desired.get(r, 0) - actual.get(r, 0) for r in roles}

    # ── Spatial Basics ───────────────────────────────────────────────

    def distance_to(self, target: tuple[int, int]) -> int:
        """Manhattan distance from current position."""
        return manhattan(self.position, target)

    def entities_within(
        self,
        position: tuple[int, int],
        radius: int,
        entity_type: str | None = None,
    ) -> list[KnownEntity]:
        """All known entities within Manhattan radius of a position."""
        return self.world_model.entities(
            entity_type=entity_type,
            predicate=lambda e: manhattan(position, e.position) <= radius,
        )

    # ── Reset ─────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all state between episodes."""
        self.engine.reset()
        self.recorder.reset()
        self.mg_state = None
        self.role = "miner"
