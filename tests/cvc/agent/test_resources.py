"""Tests for cvc.agent.resources — resource, inventory, and state query helpers."""

from __future__ import annotations

import pytest

from cogamer.cvc.agent.resources import (
    absolute_position,
    attr_int,
    attr_str,
    deposit_threshold,
    has_role_gear,
    heart_batch_target,
    heart_supply_capacity,
    inventory_signature,
    needs_emergency_mining,
    phase_name,
    resource_priority,
    resource_total,
    retreat_threshold,
    role_vibe,
    should_batch_hearts,
    team_can_afford_gear,
    team_can_refill_hearts,
    team_id,
    team_min_resource,
)
from cogamer.cvc.agent.types import (
    _ELEMENTS,
    _EMERGENCY_RESOURCE_LOW,
    _GEAR_COSTS,
    _HEART_BATCH_TARGETS,
    _HP_THRESHOLDS,
)

# ── absolute_position ──────────────────────────────────────────────────


def test_absolute_position(make_state):
    state = make_state(global_x=10, global_y=20)
    assert absolute_position(state) == (10, 20)


def test_absolute_position_origin(make_state):
    state = make_state(global_x=0, global_y=0)
    assert absolute_position(state) == (0, 0)


def test_absolute_position_large_coordinates(make_state):
    state = make_state(global_x=999, global_y=888)
    assert absolute_position(state) == (999, 888)


# ── attr_int ─────────────────────────────────────────────────────────


def test_attr_int_present(make_semantic_entity):
    entity = make_semantic_entity(hp=42)
    assert attr_int(entity, "hp") == 42


def test_attr_int_missing_returns_zero(make_semantic_entity):
    entity = make_semantic_entity()
    assert attr_int(entity, "missing") == 0


def test_attr_int_missing_returns_custom_default(make_semantic_entity):
    entity = make_semantic_entity()
    assert attr_int(entity, "missing", 99) == 99


def test_attr_int_zero_value_not_default(make_semantic_entity):
    entity = make_semantic_entity(hp=0)
    assert attr_int(entity, "hp", 99) == 0


def test_attr_int_string_coercion(make_semantic_entity):
    entity = make_semantic_entity(hp="7")
    assert attr_int(entity, "hp") == 7


# ── attr_str ─────────────────────────────────────────────────────────


def test_attr_str_present(make_semantic_entity):
    entity = make_semantic_entity(team="team_0")
    assert attr_str(entity, "team") == "team_0"


def test_attr_str_missing_returns_none(make_semantic_entity):
    entity = make_semantic_entity()
    assert attr_str(entity, "missing") is None


def test_attr_str_coerces_int(make_semantic_entity):
    entity = make_semantic_entity(hp=42)
    assert attr_str(entity, "hp") == "42"


# ── has_role_gear ────────────────────────────────────────────────────


def test_has_role_gear_true(make_state):
    state = make_state(inventory={"aligner": 1})
    assert has_role_gear(state, "aligner") is True


def test_has_role_gear_positive_count(make_state):
    state = make_state(inventory={"miner": 3})
    assert has_role_gear(state, "miner") is True


def test_has_role_gear_false_missing(make_state):
    state = make_state()
    assert has_role_gear(state, "aligner") is False


def test_has_role_gear_false_zero(make_state):
    state = make_state(inventory={"miner": 0})
    assert has_role_gear(state, "miner") is False


def test_has_role_gear_different_roles(make_state):
    state = make_state(inventory={"scrambler": 1})
    assert has_role_gear(state, "scrambler") is True
    assert has_role_gear(state, "miner") is False


# ── resource_total ───────────────────────────────────────────────────


def test_resource_total_empty(make_state):
    state = make_state()
    assert resource_total(state) == 0


def test_resource_total_all_elements(make_state):
    state = make_state(inventory={"carbon": 3, "oxygen": 2, "germanium": 1, "silicon": 4})
    assert resource_total(state) == 10


def test_resource_total_partial(make_state):
    state = make_state(inventory={"carbon": 5})
    assert resource_total(state) == 5


def test_resource_total_ignores_non_elements(make_state):
    state = make_state(inventory={"carbon": 1, "heart": 99, "miner": 1})
    assert resource_total(state) == 1


# ── deposit_threshold ────────────────────────────────────────────────


def test_deposit_threshold_no_gear(make_state):
    state = make_state()
    assert deposit_threshold(state) == 4


def test_deposit_threshold_with_miner_gear(make_state):
    state = make_state(inventory={"miner": 1})
    assert deposit_threshold(state) == 12


def test_deposit_threshold_other_gear_irrelevant(make_state):
    state = make_state(inventory={"aligner": 1})
    assert deposit_threshold(state) == 4


# ── team_id ──────────────────────────────────────────────────────────


def test_team_id_from_team_summary(make_state):
    state = make_state(team="team_0")
    assert team_id(state) == "team_0"


def test_team_id_from_team_summary_different_team(make_state):
    state = make_state(team="team_1")
    assert team_id(state) == "team_1"


def test_team_id_without_team_summary(make_state):
    state = make_state(team="team_1", team_summary=None)
    assert team_id(state) == "team_1"


def test_team_id_no_team_no_summary(make_state):
    state = make_state(team="", team_summary=None)
    assert team_id(state) == ""


# ── team_min_resource ────────────────────────────────────────────────


def test_team_min_resource_all_equal(make_state):
    state = make_state(shared_inventory={"carbon": 10, "oxygen": 10, "germanium": 10, "silicon": 10})
    assert team_min_resource(state) == 10


def test_team_min_resource_one_low(make_state):
    state = make_state(shared_inventory={"germanium": 2})
    assert team_min_resource(state) == 2


def test_team_min_resource_zero(make_state):
    state = make_state(shared_inventory={"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0})
    assert team_min_resource(state) == 0


def test_team_min_resource_no_team(make_state):
    state = make_state(team_summary=None)
    assert team_min_resource(state) == 0


def test_team_min_resource_uneven(make_state):
    state = make_state(shared_inventory={"carbon": 100, "oxygen": 3, "germanium": 50, "silicon": 7})
    assert team_min_resource(state) == 3


# ── needs_emergency_mining ───────────────────────────────────────────


def test_needs_emergency_mining_below_threshold(make_state):
    state = make_state(shared_inventory={"carbon": 0})
    assert needs_emergency_mining(state) is True


def test_needs_emergency_mining_at_threshold(make_state):
    inv = {e: _EMERGENCY_RESOURCE_LOW for e in _ELEMENTS}
    state = make_state(shared_inventory=inv)
    assert needs_emergency_mining(state) is False


def test_needs_emergency_mining_above_threshold(make_state):
    state = make_state()
    assert needs_emergency_mining(state) is False


def test_needs_emergency_mining_no_team(make_state):
    state = make_state(team_summary=None)
    assert needs_emergency_mining(state) is False


def test_needs_emergency_mining_one_element_low(make_state):
    inv = {e: 10 for e in _ELEMENTS}
    inv["silicon"] = 0
    state = make_state(shared_inventory=inv)
    assert needs_emergency_mining(state) is True


# ── resource_priority ────────────────────────────────────────────────


def test_resource_priority_lowest_first(make_state):
    state = make_state(shared_inventory={"carbon": 1, "oxygen": 3, "germanium": 2, "silicon": 4})
    result = resource_priority(state, resource_bias="carbon")
    assert result[0] == "carbon"
    assert result[-1] == "silicon"


def test_resource_priority_bias_breaks_tie(make_state):
    state = make_state(shared_inventory={"carbon": 5, "oxygen": 5, "germanium": 5, "silicon": 5})
    result = resource_priority(state, resource_bias="silicon")
    assert result[0] == "silicon"


def test_resource_priority_all_elements_present(make_state):
    state = make_state()
    result = resource_priority(state, resource_bias="carbon")
    assert set(result) == set(_ELEMENTS)
    assert len(result) == len(_ELEMENTS)


def test_resource_priority_alphabetical_tiebreaker(make_state):
    state = make_state(shared_inventory={"carbon": 5, "oxygen": 5, "germanium": 5, "silicon": 5})
    result = resource_priority(state, resource_bias="nonexistent")
    # All have same amount and none is bias, so alphabetical order
    assert result == sorted(_ELEMENTS)


def test_resource_priority_no_team(make_state):
    state = make_state(team_summary=None)
    result = resource_priority(state, resource_bias="carbon")
    # All zero, bias element first
    assert result[0] == "carbon"


# ── inventory_signature ──────────────────────────────────────────────


def test_inventory_signature_sorted_by_name(make_state):
    state = make_state(inventory={"carbon": 3, "oxygen": 1})
    sig = inventory_signature(state)
    names = [name for name, _ in sig]
    assert names == sorted(names)


def test_inventory_signature_returns_tuple_of_tuples(make_state):
    state = make_state()
    sig = inventory_signature(state)
    assert isinstance(sig, tuple)
    for item in sig:
        assert isinstance(item, tuple)
        assert len(item) == 2


def test_inventory_signature_includes_all_inventory(make_state):
    state = make_state(inventory={"carbon": 5, "silicon": 3})
    sig = inventory_signature(state)
    sig_dict = dict(sig)
    assert sig_dict["carbon"] == 5
    assert sig_dict["silicon"] == 3


def test_inventory_signature_deterministic(make_state):
    state = make_state(inventory={"carbon": 1, "oxygen": 2})
    assert inventory_signature(state) == inventory_signature(state)


# ── role_vibe ────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["aligner", "miner", "scrambler", "scout"])
def test_role_vibe_known(role):
    assert role_vibe(role) == f"change_vibe_{role}"


def test_role_vibe_unknown():
    assert role_vibe("wizard") == "change_vibe_default"


def test_role_vibe_empty_string():
    assert role_vibe("") == "change_vibe_default"


# ── retreat_threshold ────────────────────────────────────────────────


def test_retreat_threshold_base_values(make_state):
    for role, base in _HP_THRESHOLDS.items():
        if role == "unknown":
            continue
        state = make_state(step=100, inventory={role: 1})
        # Early game with gear: just the base threshold
        assert retreat_threshold(state, role) == base


def test_retreat_threshold_no_gear_adds_10(make_state):
    for role in ("miner", "aligner", "scrambler", "scout"):
        with_gear = retreat_threshold(make_state(step=100, inventory={role: 1}), role)
        without_gear = retreat_threshold(make_state(step=100), role)
        assert without_gear == with_gear + 10


def test_retreat_threshold_late_game_aligner(make_state):
    state_early = make_state(step=100, inventory={"aligner": 1})
    state_late = make_state(step=3000, inventory={"aligner": 1})
    assert retreat_threshold(state_late, "aligner") == retreat_threshold(state_early, "aligner") + 15


def test_retreat_threshold_late_game_scrambler(make_state):
    state_early = make_state(step=100, inventory={"scrambler": 1})
    state_late = make_state(step=3000, inventory={"scrambler": 1})
    assert retreat_threshold(state_late, "scrambler") == retreat_threshold(state_early, "scrambler") + 15


def test_retreat_threshold_late_game_miner(make_state):
    state_early = make_state(step=100, inventory={"miner": 1})
    state_late = make_state(step=3000, inventory={"miner": 1})
    assert retreat_threshold(state_late, "miner") == retreat_threshold(state_early, "miner") + 10


def test_retreat_threshold_late_game_scout_no_bonus(make_state):
    state_early = make_state(step=100, inventory={"scout": 1})
    state_late = make_state(step=3000, inventory={"scout": 1})
    # Scout is not in aligner/scrambler/miner late-game bonus
    assert retreat_threshold(state_late, "scout") == retreat_threshold(state_early, "scout")


def test_retreat_threshold_step_boundary(make_state):
    # Exactly at 2500
    state_at = make_state(step=2500, inventory={"aligner": 1})
    state_below = make_state(step=2499, inventory={"aligner": 1})
    assert retreat_threshold(state_at, "aligner") > retreat_threshold(state_below, "aligner")


def test_retreat_threshold_combined_late_no_gear(make_state):
    # Late game + no gear: base + late bonus + 10
    base = _HP_THRESHOLDS["aligner"]
    state = make_state(step=3000)
    assert retreat_threshold(state, "aligner") == base + 15 + 10


# ── phase_name ───────────────────────────────────────────────────────


def test_phase_name_retreat_low_hp(make_state):
    state = make_state(hp=1)
    assert phase_name(state, "miner") == "retreat"


def test_phase_name_regear_no_gear(make_state):
    # HP high, no gear, team can afford
    state = make_state(hp=100)
    assert phase_name(state, "aligner") == "regear"


def test_phase_name_fund_gear_cant_afford(make_state):
    # HP high, no gear, team cannot afford
    state = make_state(
        hp=100,
        shared_inventory={"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0},
    )
    assert phase_name(state, "aligner") == "fund_gear"


def test_phase_name_fund_gear_miner_skips(make_state):
    # Miner never gets fund_gear, goes straight to regear
    state = make_state(
        hp=100,
        shared_inventory={"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0},
    )
    assert phase_name(state, "miner") == "regear"


def test_phase_name_hearts_aligner_no_hearts(make_state):
    state = make_state(hp=100, inventory={"aligner": 1, "heart": 0})
    assert phase_name(state, "aligner") == "hearts"


def test_phase_name_hearts_scrambler_no_hearts(make_state):
    state = make_state(hp=100, inventory={"scrambler": 1, "heart": 0})
    assert phase_name(state, "scrambler") == "hearts"


def test_phase_name_miner_no_hearts_check(make_state):
    # Miner does not check hearts
    state = make_state(hp=100, inventory={"miner": 1, "heart": 0, "carbon": 0})
    assert phase_name(state, "miner") == "economy"


def test_phase_name_expand(make_state):
    state = make_state(hp=100, inventory={"aligner": 1, "heart": 1})
    assert phase_name(state, "aligner") == "expand"


def test_phase_name_pressure(make_state):
    state = make_state(hp=100, inventory={"scrambler": 1, "heart": 1})
    assert phase_name(state, "scrambler") == "pressure"


def test_phase_name_economy(make_state):
    state = make_state(hp=100, inventory={"miner": 1, "carbon": 0})
    assert phase_name(state, "miner") == "economy"


def test_phase_name_deposit(make_state):
    state = make_state(hp=100, inventory={"miner": 1, "carbon": 5, "oxygen": 5, "germanium": 5, "silicon": 5})
    assert phase_name(state, "miner") == "deposit"


def test_phase_name_deposit_threshold_boundary(make_state):
    # Exactly at deposit threshold (12 with miner gear)
    state = make_state(hp=100, inventory={"miner": 1, "carbon": 3, "oxygen": 3, "germanium": 3, "silicon": 3})
    assert phase_name(state, "miner") == "deposit"


def test_phase_name_deposit_below_threshold(make_state):
    # Just below deposit threshold
    state = make_state(hp=100, inventory={"miner": 1, "carbon": 3, "oxygen": 3, "germanium": 3, "silicon": 2})
    assert phase_name(state, "miner") == "economy"


def test_phase_name_scout_explore(make_state):
    state = make_state(hp=100, inventory={"scout": 1})
    assert phase_name(state, "scout") == "explore"


# ── heart_batch_target ───────────────────────────────────────────────


def test_heart_batch_target_aligner(make_state):
    state = make_state()
    assert heart_batch_target(state, "aligner") == _HEART_BATCH_TARGETS["aligner"]


def test_heart_batch_target_scrambler(make_state):
    state = make_state()
    assert heart_batch_target(state, "scrambler") == _HEART_BATCH_TARGETS["scrambler"]


def test_heart_batch_target_miner_zero(make_state):
    state = make_state()
    assert heart_batch_target(state, "miner") == 0


def test_heart_batch_target_scout_zero(make_state):
    state = make_state()
    assert heart_batch_target(state, "scout") == 0


def test_heart_batch_target_unknown_role_zero(make_state):
    state = make_state()
    assert heart_batch_target(state, "wizard") == 0


# ── team_can_afford_gear ─────────────────────────────────────────────


@pytest.mark.parametrize("role", list(_GEAR_COSTS.keys()))
def test_team_can_afford_gear_enough(make_state, role):
    state = make_state(shared_inventory={"carbon": 20, "oxygen": 20, "germanium": 20, "silicon": 20})
    assert team_can_afford_gear(state, role) is True


@pytest.mark.parametrize("role", list(_GEAR_COSTS.keys()))
def test_team_can_afford_gear_not_enough(make_state, role):
    state = make_state(shared_inventory={"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0})
    assert team_can_afford_gear(state, role) is False


def test_team_can_afford_gear_exact_cost(make_state):
    # Aligner costs: carbon=3, oxygen=1, germanium=1, silicon=1
    costs = _GEAR_COSTS["aligner"]
    state = make_state(shared_inventory=costs)
    assert team_can_afford_gear(state, "aligner") is True


def test_team_can_afford_gear_one_short(make_state):
    costs = dict(_GEAR_COSTS["aligner"])
    # Reduce one resource below cost
    first_resource = next(iter(costs))
    costs[first_resource] -= 1
    state = make_state(shared_inventory=costs)
    assert team_can_afford_gear(state, "aligner") is False


def test_team_can_afford_gear_no_team(make_state):
    state = make_state(team_summary=None)
    assert team_can_afford_gear(state, "aligner") is False


def test_team_can_afford_gear_unknown_role(make_state):
    state = make_state()
    assert team_can_afford_gear(state, "wizard") is True


# ── team_can_refill_hearts ───────────────────────────────────────────


def test_team_can_refill_hearts_has_hearts(make_state):
    state = make_state(shared_inventory={"heart": 1})
    assert team_can_refill_hearts(state) is True


def test_team_can_refill_hearts_many_hearts(make_state):
    state = make_state(shared_inventory={"heart": 10})
    assert team_can_refill_hearts(state) is True


def test_team_can_refill_hearts_enough_resources(make_state):
    state = make_state(
        shared_inventory={"heart": 0, "carbon": 7, "oxygen": 7, "germanium": 7, "silicon": 7},
    )
    assert team_can_refill_hearts(state) is True


def test_team_can_refill_hearts_one_element_short(make_state):
    state = make_state(
        shared_inventory={"heart": 0, "carbon": 6, "oxygen": 7, "germanium": 7, "silicon": 7},
    )
    assert team_can_refill_hearts(state) is False


def test_team_can_refill_hearts_all_short(make_state):
    state = make_state(
        shared_inventory={"heart": 0, "carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0},
    )
    assert team_can_refill_hearts(state) is False


def test_team_can_refill_hearts_no_team(make_state):
    state = make_state(team_summary=None)
    assert team_can_refill_hearts(state) is False


# ── heart_supply_capacity ────────────────────────────────────────────


def test_heart_supply_capacity_hearts_plus_resource_ratio(make_state):
    state = make_state(
        shared_inventory={"heart": 3, "carbon": 14, "oxygen": 14, "germanium": 14, "silicon": 14},
    )
    # 3 + 14 // 7 = 3 + 2 = 5
    assert heart_supply_capacity(state) == 5


def test_heart_supply_capacity_no_hearts(make_state):
    state = make_state(
        shared_inventory={"heart": 0, "carbon": 21, "oxygen": 21, "germanium": 21, "silicon": 21},
    )
    assert heart_supply_capacity(state) == 0 + 21 // 7  # 3


def test_heart_supply_capacity_no_resources(make_state):
    state = make_state(
        shared_inventory={"heart": 5, "carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0},
    )
    assert heart_supply_capacity(state) == 5


def test_heart_supply_capacity_min_resource_used(make_state):
    state = make_state(
        shared_inventory={"heart": 0, "carbon": 100, "oxygen": 100, "germanium": 100, "silicon": 7},
    )
    # min resource is 7, 7 // 7 = 1
    assert heart_supply_capacity(state) == 1


def test_heart_supply_capacity_no_team(make_state):
    state = make_state(team_summary=None)
    assert heart_supply_capacity(state) == 0


# ── should_batch_hearts ──────────────────────────────────────────────


def test_should_batch_hearts_no_hub(make_state):
    state = make_state(inventory={"heart": 1})
    assert should_batch_hearts(state, role="aligner", hub_position=None) is False


def test_should_batch_hearts_no_hearts(make_state):
    state = make_state(inventory={"heart": 0})
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is False


def test_should_batch_hearts_already_at_batch_target(make_state):
    target = _HEART_BATCH_TARGETS["aligner"]
    state = make_state(
        hp=100,
        inventory={"aligner": 1, "heart": target},
        global_x=44,
        global_y=44,
    )
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is False


def test_should_batch_hearts_above_batch_target(make_state):
    target = _HEART_BATCH_TARGETS["aligner"]
    state = make_state(
        hp=100,
        inventory={"aligner": 1, "heart": target + 5},
        global_x=44,
        global_y=44,
    )
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is False


def test_should_batch_hearts_too_far_from_hub(make_state):
    state = make_state(
        hp=100,
        inventory={"aligner": 1, "heart": 1},
        global_x=44,
        global_y=44,
    )
    # Hub at (50, 50) → manhattan distance = 12
    assert should_batch_hearts(state, role="aligner", hub_position=(50, 50)) is False


def test_should_batch_hearts_team_cant_refill(make_state):
    state = make_state(
        hp=100,
        inventory={"aligner": 1, "heart": 1},
        global_x=44,
        global_y=44,
        shared_inventory={"heart": 0, "carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0},
    )
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is False


def test_should_batch_hearts_all_conditions_met(make_state):
    # 1 heart < batch target(3), near hub, team can refill
    state = make_state(
        hp=100,
        inventory={"aligner": 1, "heart": 1},
        global_x=44,
        global_y=44,
        shared_inventory={"heart": 5, "carbon": 10, "oxygen": 10, "germanium": 10, "silicon": 10},
    )
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is True


def test_should_batch_hearts_adjacent_to_hub(make_state):
    # Distance 1 from hub (should still work)
    state = make_state(
        hp=100,
        inventory={"aligner": 1, "heart": 1},
        global_x=44,
        global_y=45,
        shared_inventory={"heart": 5, "carbon": 10, "oxygen": 10, "germanium": 10, "silicon": 10},
    )
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is True


def test_should_batch_hearts_distance_2_from_hub(make_state):
    # Distance 2 → too far
    state = make_state(
        hp=100,
        inventory={"aligner": 1, "heart": 1},
        global_x=44,
        global_y=46,
        shared_inventory={"heart": 5, "carbon": 10, "oxygen": 10, "germanium": 10, "silicon": 10},
    )
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is False


def test_should_batch_hearts_role_without_batch_target(make_state):
    # Miner has batch target 0, so hearts >= 0 means hearts >= batch_target → returns False
    state = make_state(
        hp=100,
        inventory={"miner": 1, "heart": 1},
        global_x=44,
        global_y=44,
    )
    assert should_batch_hearts(state, role="miner", hub_position=(44, 44)) is False
