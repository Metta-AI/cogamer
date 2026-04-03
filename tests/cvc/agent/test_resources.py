"""Tests for cvc.agent.resources — resource, inventory, and state query helpers."""

from __future__ import annotations

import pytest

from cvc.agent.resources import (
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


# ── absolute_position ──────────────────────────────────────────────────


def test_absolute_position(make_state):
    state = make_state(global_x=10, global_y=20)
    assert absolute_position(state) == (10, 20)


def test_absolute_position_defaults(make_state):
    state = make_state(global_x=0, global_y=0)
    assert absolute_position(state) == (0, 0)


# ── attr_int / attr_str ───────────────────────────────────────────────


def test_attr_int_present(make_semantic_entity):
    entity = make_semantic_entity(hp=42)
    assert attr_int(entity, "hp") == 42


def test_attr_int_missing_returns_default(make_semantic_entity):
    entity = make_semantic_entity()
    assert attr_int(entity, "missing") == 0
    assert attr_int(entity, "missing", 99) == 99


def test_attr_str_present(make_semantic_entity):
    entity = make_semantic_entity(team="team_0")
    assert attr_str(entity, "team") == "team_0"


def test_attr_str_missing(make_semantic_entity):
    entity = make_semantic_entity()
    assert attr_str(entity, "missing") is None


# ── has_role_gear ──────────────────────────────────────────────────────


def test_has_role_gear_true(make_state):
    state = make_state(inventory={"aligner": 1})
    assert has_role_gear(state, "aligner") is True


def test_has_role_gear_false(make_state):
    state = make_state()
    assert has_role_gear(state, "aligner") is False


def test_has_role_gear_zero(make_state):
    state = make_state(inventory={"miner": 0})
    assert has_role_gear(state, "miner") is False


# ── resource_total ─────────────────────────────────────────────────────


def test_resource_total_empty(make_state):
    state = make_state()
    assert resource_total(state) == 0


def test_resource_total_some(make_state):
    state = make_state(inventory={"carbon": 3, "oxygen": 2, "germanium": 1, "silicon": 4})
    assert resource_total(state) == 10


# ── deposit_threshold ──────────────────────────────────────────────────


def test_deposit_threshold_no_miner_gear(make_state):
    state = make_state()
    assert deposit_threshold(state) == 4


def test_deposit_threshold_with_miner_gear(make_state):
    state = make_state(inventory={"miner": 1})
    assert deposit_threshold(state) == 12


# ── team_id ────────────────────────────────────────────────────────────


def test_team_id_from_team_summary(make_state):
    state = make_state(team="team_0")
    assert team_id(state) == "team_0"


def test_team_id_without_team_summary(make_state):
    state = make_state(team="team_1", team_summary=None)
    assert team_id(state) == "team_1"


# ── team_min_resource ──────────────────────────────────────────────────


def test_team_min_resource_default(make_state):
    state = make_state()
    assert team_min_resource(state) == 10


def test_team_min_resource_one_low(make_state):
    state = make_state(shared_inventory={"germanium": 2})
    assert team_min_resource(state) == 2


def test_team_min_resource_no_team(make_state):
    state = make_state(team_summary=None)
    assert team_min_resource(state) == 0


# ── needs_emergency_mining ─────────────────────────────────────────────


def test_needs_emergency_mining_low(make_state):
    state = make_state(shared_inventory={"carbon": 0})
    assert needs_emergency_mining(state) is True


def test_needs_emergency_mining_ok(make_state):
    state = make_state()
    assert needs_emergency_mining(state) is False


def test_needs_emergency_mining_no_team(make_state):
    state = make_state(team_summary=None)
    assert needs_emergency_mining(state) is False


# ── resource_priority ──────────────────────────────────────────────────


def test_resource_priority_sorts_by_amount(make_state):
    state = make_state(shared_inventory={"carbon": 1, "oxygen": 3, "germanium": 2, "silicon": 4})
    result = resource_priority(state, resource_bias="carbon")
    assert result[0] == "carbon"  # lowest amount + bias


def test_resource_priority_bias_breaks_tie(make_state):
    state = make_state(shared_inventory={"carbon": 5, "oxygen": 5, "germanium": 5, "silicon": 5})
    result = resource_priority(state, resource_bias="silicon")
    assert result[0] == "silicon"


# ── inventory_signature ────────────────────────────────────────────────


def test_inventory_signature_sorted(make_state):
    state = make_state(inventory={"carbon": 3, "oxygen": 1})
    sig = inventory_signature(state)
    # Should be sorted by name
    names = [name for name, _ in sig]
    assert names == sorted(names)


# ── role_vibe ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["aligner", "miner", "scrambler", "scout"])
def test_role_vibe_known(role):
    assert role_vibe(role) == f"change_vibe_{role}"


def test_role_vibe_unknown():
    assert role_vibe("wizard") == "change_vibe_default"


# ── retreat_threshold ──────────────────────────────────────────────────


def test_retreat_threshold_base(make_state):
    state = make_state(step=100)
    thresh = retreat_threshold(state, "miner")
    assert isinstance(thresh, int)
    assert thresh > 0


def test_retreat_threshold_late_game_higher(make_state):
    early = retreat_threshold(make_state(step=100), "aligner")
    late = retreat_threshold(make_state(step=3000), "aligner")
    assert late > early


def test_retreat_threshold_no_gear_higher(make_state):
    with_gear = retreat_threshold(make_state(inventory={"miner": 1}), "miner")
    without_gear = retreat_threshold(make_state(), "miner")
    assert without_gear > with_gear


# ── phase_name ─────────────────────────────────────────────────────────


def test_phase_name_retreat_low_hp(make_state):
    state = make_state(hp=1)
    assert phase_name(state, "miner") == "retreat"


def test_phase_name_regear(make_state):
    state = make_state(hp=100)
    assert phase_name(state, "aligner") == "regear"


def test_phase_name_expand_with_gear(make_state):
    state = make_state(hp=100, inventory={"aligner": 1, "heart": 1})
    assert phase_name(state, "aligner") == "expand"


def test_phase_name_hearts_no_hearts(make_state):
    state = make_state(hp=100, inventory={"aligner": 1, "heart": 0})
    assert phase_name(state, "aligner") == "hearts"


def test_phase_name_economy(make_state):
    state = make_state(hp=100, inventory={"miner": 1, "carbon": 0})
    assert phase_name(state, "miner") == "economy"


def test_phase_name_deposit(make_state):
    state = make_state(hp=100, inventory={"miner": 1, "carbon": 5, "oxygen": 5, "germanium": 5, "silicon": 5})
    assert phase_name(state, "miner") == "deposit"


# ── team_can_afford_gear ───────────────────────────────────────────────


def test_team_can_afford_gear_enough(make_state):
    state = make_state(shared_inventory={"carbon": 20, "oxygen": 20, "germanium": 20, "silicon": 20})
    assert team_can_afford_gear(state, "aligner") is True


def test_team_can_afford_gear_not_enough(make_state):
    state = make_state(shared_inventory={"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0})
    assert team_can_afford_gear(state, "aligner") is False


def test_team_can_afford_gear_no_team(make_state):
    state = make_state(team_summary=None)
    assert team_can_afford_gear(state, "aligner") is False


# ── team_can_refill_hearts ─────────────────────────────────────────────


def test_team_can_refill_hearts_has_hearts(make_state):
    state = make_state(shared_inventory={"heart": 1})
    assert team_can_refill_hearts(state) is True


def test_team_can_refill_hearts_enough_resources(make_state):
    state = make_state(shared_inventory={"heart": 0, "carbon": 7, "oxygen": 7, "germanium": 7, "silicon": 7})
    assert team_can_refill_hearts(state) is True


def test_team_can_refill_hearts_not_enough(make_state):
    state = make_state(shared_inventory={"heart": 0, "carbon": 6, "oxygen": 7, "germanium": 7, "silicon": 7})
    assert team_can_refill_hearts(state) is False


def test_team_can_refill_hearts_no_team(make_state):
    state = make_state(team_summary=None)
    assert team_can_refill_hearts(state) is False


# ── heart_supply_capacity ──────────────────────────────────────────────


def test_heart_supply_capacity_with_hearts(make_state):
    state = make_state(shared_inventory={"heart": 3, "carbon": 14, "oxygen": 14, "germanium": 14, "silicon": 14})
    assert heart_supply_capacity(state) == 3 + 14 // 7  # 3 + 2 = 5


def test_heart_supply_capacity_no_team(make_state):
    state = make_state(team_summary=None)
    assert heart_supply_capacity(state) == 0


# ── should_batch_hearts ────────────────────────────────────────────────


def test_should_batch_hearts_near_hub_with_hearts(make_state):
    # Position at (44,44), hub at (44,44) → distance 0
    state = make_state(hp=100, inventory={"aligner": 1, "heart": 1}, global_x=44, global_y=44)
    result = should_batch_hearts(state, role="aligner", hub_position=(44, 44))
    # Depends on batch target and team heart supply
    assert isinstance(result, bool)


def test_should_batch_hearts_no_hub(make_state):
    state = make_state(inventory={"heart": 1})
    assert should_batch_hearts(state, role="aligner", hub_position=None) is False


def test_should_batch_hearts_no_hearts(make_state):
    state = make_state(inventory={"heart": 0})
    assert should_batch_hearts(state, role="aligner", hub_position=(44, 44)) is False


# ── heart_batch_target ─────────────────────────────────────────────────


def test_heart_batch_target_aligner(make_state):
    state = make_state()
    target = heart_batch_target(state, "aligner")
    assert isinstance(target, int)
    assert target > 0


def test_heart_batch_target_miner(make_state):
    state = make_state()
    assert heart_batch_target(state, "miner") == 0
