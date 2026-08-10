"""Sizing, service history, warranty, and the repair-vs-replace call."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.config import PricingConfig
from app.services.advisory import (
    capacity_tons,
    check_sizing,
    check_warranty,
    evaluate_repair_vs_replace,
    service_status,
)
from app.services.pricing import build_estimate


@pytest.fixture
def repair(repo, config, make_request):
    """Price a repair for a customer and evaluate it against replacement."""

    def _repair(customer_id, equipment, labor, cfg=None):
        cfg = cfg or config
        estimate = build_estimate(
            make_request(customer_id=customer_id, equipment=equipment, labor=labor),
            repo,
            cfg,
        )
        return estimate, evaluate_repair_vs_replace(
            repo.customer_by_id(customer_id), estimate, repo, cfg
        )

    return _repair


# ---------------------------------------------------------------------------
# Capacity parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "equipment_id,expected",
    [
        ("EQ009", Decimal("3")),  # "Goodman 3-Ton Central AC"
        ("EQ007", Decimal("5")),  # "York 5-Ton Rooftop Unit"
        ("EQ024", Decimal("4")),  # "Trane 4-Ton Heat Pump"
        ("EQ005", Decimal("1")),  # "12K BTU" -> 1 ton
        ("EQ006", Decimal("1.5")),  # "18K BTU" -> 1.5 ton
    ],
)
def test_capacity_parsed_from_product_name(repo, equipment_id, expected):
    """Capacity is not a field -- it is embedded in free text, in two formats."""
    assert capacity_tons(repo.equipment_by_id(equipment_id)) == expected


def test_unparseable_capacity_returns_none(repo):
    """A capacitor has no tonnage; the sizing check must stay quiet, not guess."""
    assert capacity_tons(repo.equipment_by_id("EQ018")) is None


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------


def test_correctly_sized_unit_passes(repo, config):
    """Patricia's 1,400 sq ft needs ~2.8 tons; a 3-ton unit is right."""
    checks = check_sizing(
        repo.customer_by_id("CUST006"), [repo.equipment_by_id("EQ009")], config
    )
    assert [c.verdict for c in checks] == ["ok"]


def test_grossly_oversized_unit_is_flagged(repo, config):
    """A 5-ton rooftop unit on a 1,400 sq ft house."""
    checks = check_sizing(
        repo.customer_by_id("CUST006"), [repo.equipment_by_id("EQ007")], config
    )
    assert checks[0].verdict == "oversized"
    assert "short-cycle" in checks[0].message


def test_undersized_unit_is_flagged(repo, config):
    """A 1-ton mini-split against a 12,000 sq ft church."""
    checks = check_sizing(
        repo.customer_by_id("CUST005"), [repo.equipment_by_id("EQ005")], config
    )
    assert checks[0].verdict == "undersized"


def test_components_are_not_size_checked(repo, config):
    """A 3-ton coil in a 5-ton system is a legitimate repair, not our business."""
    assert check_sizing(
        repo.customer_by_id("CUST006"), [repo.equipment_by_id("EQ014")], config
    ) == []


# ---------------------------------------------------------------------------
# Service history
# ---------------------------------------------------------------------------


def test_service_status_unknown_when_absent(repo):
    assert service_status(repo.customer_by_id("CUST007")).status == "unknown"


@pytest.mark.parametrize(
    "months_ago,expected",
    [(2, "current"), (11, "current"), (13, "due"), (24, "overdue")],
)
def test_service_status_thresholds(repo, months_ago, expected):
    customer = repo.customer_by_id("CUST001").model_copy()
    today = date(2026, 6, 15)
    year, month = divmod((today.year * 12 + today.month - 1) - months_ago, 12)
    customer.last_service_date = date(year, month + 1, 1)
    assert service_status(customer, today=today).status == expected


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------


def test_warranty_flagged_on_young_system_major_part(repo):
    """Alvarez's system is 3 years old -- a compressor is very likely covered."""
    flag = check_warranty(
        repo.customer_by_id("CUST004"), [repo.equipment_by_id("EQ011")]
    )
    assert flag.applies
    assert "3 years old" in flag.message


def test_warranty_not_flagged_on_old_system(repo):
    flag = check_warranty(
        repo.customer_by_id("CUST006"), [repo.equipment_by_id("EQ011")]
    )
    assert not flag.applies


def test_warranty_not_flagged_for_consumable_parts(repo):
    """Capacitors are wear items and are not what a parts warranty covers."""
    flag = check_warranty(
        repo.customer_by_id("CUST004"), [repo.equipment_by_id("EQ018")]
    )
    assert not flag.applies


def test_warranty_silent_without_system_age(repo):
    flag = check_warranty(
        repo.customer_by_id("CUST007"), [repo.equipment_by_id("EQ011")]
    )
    assert not flag.applies


# ---------------------------------------------------------------------------
# Repair vs replace
# ---------------------------------------------------------------------------


def test_old_system_expensive_repair_recommends_replacement(repair):
    """Patricia: 22 years old, $1,390 repair against $3,300 to replace."""
    _, advice = repair(
        "CUST006", [("EQ011", 1)], [("diagnostic", "standard", "1"), ("repair", "major", "4")]
    )
    assert advice.triggered
    assert advice.recommendation == "replace"
    assert advice.cost_ratio == Decimal("0.42")
    assert advice.replacement_total == Decimal("3300.00")


def test_replacement_targets_the_system_that_failed(repair):
    """Patricia has "Central AC + Gas Furnace" -- two systems.

    A compressor is in the condenser, so the comparison must be against the air
    conditioner. Matching on the customer's `systemType` string alone would return
    whichever category the lookup happened to hit first, and quote a furnace to a
    customer whose AC just died.
    """
    _, compressor = repair(
        "CUST006", [("EQ011", 1)], [("repair", "major", "4")]
    )
    _, ignitor = repair("CUST006", [("EQ023", 1)], [("repair", "minor", "1")])

    assert compressor.option.equipment_name == "Goodman 3-Ton Central AC"
    assert ignitor.option.equipment_name == "Bryant Legacy Line Furnace 80%"


def test_newer_system_is_left_alone(repair):
    """An 8-year-old heat pump with a $1,390 compressor job should be repaired.

    Age x cost is $11,120 here, which clears the $5,000 rule of thumb -- so that
    rule cannot be allowed to fire on its own, or the tool recommends replacing
    systems with a decade of life left.
    """
    _, advice = repair(
        "CUST002", [("EQ011", 1)], [("diagnostic", "standard", "1"), ("repair", "major", "4")]
    )
    assert not advice.triggered
    assert advice.recommendation == "repair"
    assert advice.replacement_total is not None  # comparison still available


def test_silent_when_system_age_is_unknown(repair):
    """CUST007 has no systemAge. Advice built on an invented age is worse than none."""
    _, advice = repair("CUST007", [("EQ018", 1)], [("repair", "minor", "1")])
    assert not advice.triggered
    assert advice.option is None
    assert any("not on file" in r for r in advice.reasons)


def test_not_evaluated_for_installs(repair):
    """Comparing a replacement against replacement is a tautology."""
    _, advice = repair("CUST006", [("EQ009", 1)], [("install", "residential", "6")])
    assert not advice.triggered
    assert advice.option is None


def test_thresholds_are_configurable(repair):
    """A shop that replaces later should be able to say so."""
    _, advice = repair(
        "CUST006",
        [("EQ011", 1)],
        [("repair", "major", "4")],
        cfg=PricingConfig(end_of_life_years=30, replace_cost_ratio=Decimal("0.9")),
    )
    assert not advice.triggered


def test_headline_states_the_arithmetic(repair):
    """The tool shows its working; a customer can check the claim."""
    _, advice = repair(
        "CUST006", [("EQ011", 1)], [("diagnostic", "standard", "1"), ("repair", "major", "4")]
    )
    assert "22-year-old" in advice.headline
    assert "$1,390" in advice.headline
    assert "42%" in advice.headline
