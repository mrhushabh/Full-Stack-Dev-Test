"""The dataset inconsistencies, pinned as tests.

These assert against the specific records that differ in the provided files. If
someone later "tidies" the normalization layer away, these fail loudly rather than
letting a silently-zero cost reach a customer's estimate.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


def test_all_records_load(repo):
    assert len(repo.equipment) == 30
    assert len(repo.customers) == 10
    assert len(repo.labor_rates) == 11


@pytest.mark.parametrize(
    "equipment_id,expected",
    [
        ("EQ012", Decimal("275")),  # snake_case `base_cost` in the source
        ("EQ028", Decimal("680")),  # snake_case `base_cost` in the source
        ("EQ011", Decimal("850")),  # camelCase `baseCost`, the majority spelling
        ("EQ001", Decimal("3200")),
    ],
)
def test_cost_normalized_across_both_spellings(repo, equipment_id, expected):
    assert repo.equipment_by_id(equipment_id).cost == expected


def test_every_equipment_item_has_a_cost(repo):
    """No item may end up with a null or zero cost through a missed alias."""
    assert all(e.cost > 0 for e in repo.equipment)


def test_customer_with_snake_case_fields(repo):
    """CUST008 uses `property_type` and `sqft` where every other record does not."""
    customer = repo.customer_by_id("CUST008")
    assert customer.property_type.value == "residential"
    assert customer.square_footage == 2750


def test_every_customer_has_property_type_and_footage(repo):
    assert all(c.property_type is not None for c in repo.customers)
    assert all(c.square_footage > 0 for c in repo.customers)


@pytest.mark.parametrize(
    "customer_id,field",
    [
        ("CUST005", "phone"),  # Springfield Community Church
        ("CUST007", "system_age"),  # Brewed Awakening Coffee
        ("CUST007", "last_service_date"),
        ("CUST003", "last_service_date"),  # Sunrise Medical Group
    ],
)
def test_absent_optional_fields_stay_none(repo, customer_id, field):
    """Missing must mean missing.

    Defaulting a missing `systemAge` to 0 would make an unknown system read as
    brand new and suppress the repair-vs-replace advisory entirely.
    """
    assert getattr(repo.customer_by_id(customer_id), field) is None


def test_nested_estimated_hours_flattened(repo):
    rate = repo.labor_rate("repair", "major")
    assert rate.hourly_rate == Decimal("135")
    assert rate.min_hours == Decimal("2")
    assert rate.max_hours == Decimal("6")
    assert rate.midpoint_hours == Decimal("4")


def test_multi_system_detection(repo):
    """`systemType` is free text; both conventions in the data must be recognised."""
    assert repo.customer_by_id("CUST001").has_multiple_systems  # "AC + Furnace"
    assert repo.customer_by_id("CUST003").has_multiple_systems  # "(x3)"
    assert not repo.customer_by_id("CUST002").has_multiple_systems  # "Heat Pump"


def test_costs_are_decimal_not_float(repo):
    """Guards the money invariant at the boundary where data enters the system."""
    assert all(isinstance(e.cost, Decimal) for e in repo.equipment)
    assert all(isinstance(r.hourly_rate, Decimal) for r in repo.labor_rates)
