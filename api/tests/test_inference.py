"""Level proposals: the right default, and an honest confidence attached to it."""

from __future__ import annotations

import pytest

from app.services.inference import (
    Confidence,
    propose_diagnostic_level,
    propose_install_level,
    propose_levels,
    propose_repair_level,
)


# ---------------------------------------------------------------------------
# Repair severity, anchored to the failed part
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "equipment_id,expected,note",
    [
        ("EQ018", "minor", "$32 capacitor"),
        ("EQ023", "minor", "$45 ignitor"),
        ("EQ022", "minor", "$95 control board"),
        ("EQ016", "minor", "$165 thermostat"),
        ("EQ011", "major", "compressor: refrigerant circuit"),
        ("EQ030", "major", "5-ton compressor"),
        ("EQ014", "major", "evaporator coil"),
        ("EQ029", "major", "$650 ECM blower motor, over the cost threshold"),
        ("EQ013", "minor", "$185 condenser fan motor, under the threshold"),
    ],
)
def test_repair_severity_follows_the_part(repo, config, equipment_id, expected, note):
    """Severity is derived from what the tech is replacing, not asked as a guess.

    The two Motor entries matter most: same category, opposite answers, split by
    cost. That is the case a naive category-only map gets wrong.
    """
    item = repo.equipment_by_id(equipment_id)
    assert propose_repair_level([item], config).level == expected, note


def test_worst_part_governs_a_mixed_job(repo, config):
    """One major component makes the whole job major, whatever else is on it."""
    parts = [repo.equipment_by_id(i) for i in ("EQ018", "EQ023", "EQ011")]
    proposal = propose_repair_level(parts, config)
    assert proposal.level == "major"
    assert proposal.confidence is Confidence.HIGH


def test_no_parts_yet_is_low_confidence(repo, config):
    proposal = propose_repair_level([], config)
    assert proposal.level == "minor"
    assert proposal.confidence is Confidence.LOW


def test_every_proposal_carries_a_reason(repo, config):
    """The reasoning is the product. A bare answer would be worse than none."""
    for item in repo.equipment:
        proposal = propose_repair_level([item], config)
        assert proposal.reason.strip()
        assert item.name in proposal.reason or "threshold" in proposal.reason


# ---------------------------------------------------------------------------
# Install level, derived from the property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "customer_id,expected",
    [
        ("CUST001", "residential"),  # 2,200 sq ft house
        ("CUST003", "commercial"),  # medical group, rooftop units
        ("CUST005", "commercial"),  # church
        ("CUST010", "residential"),  # heat pump house
    ],
)
def test_install_level_from_property(repo, customer_id, expected):
    assert propose_install_level(repo.customer_by_id(customer_id)).level == expected


def test_commercial_mini_split_is_flagged_as_ambiguous(repo):
    """CUST007 is a commercial property running mini-splits.

    $185/h over 6-16h against $140/h over 3-6h is roughly a threefold swing, and
    nothing in the record resolves it. The tool proposes the more specific match,
    marks itself unsure, and offers the alternative rather than quietly picking.
    """
    proposal = propose_install_level(repo.customer_by_id("CUST007"))
    assert proposal.level == "mini-split"
    assert proposal.confidence is Confidence.LOW
    assert [a.level for a in proposal.alternatives] == ["commercial"]


def test_mini_split_residential_is_confident(repo):
    """Alvarez has a mini-split among his systems and is residential: no conflict."""
    proposal = propose_install_level(repo.customer_by_id("CUST004"))
    assert proposal.level == "mini-split"
    assert proposal.confidence is Confidence.HIGH


def test_walk_up_customer_defaults_with_low_confidence():
    proposal = propose_install_level(None)
    assert proposal.level == "residential"
    assert proposal.confidence is Confidence.LOW


# ---------------------------------------------------------------------------
# Diagnostic complexity
# ---------------------------------------------------------------------------


def test_single_conventional_system_is_standard(repo, config):
    """CUST002: heat pump, 8 years old, residential. Nothing complicating."""
    proposal = propose_diagnostic_level(repo.customer_by_id("CUST002"), config)
    assert proposal.level == "standard"


@pytest.mark.parametrize(
    "customer_id,factor",
    [
        ("CUST003", "commercial"),  # 3 rooftop units
        ("CUST006", "22-year-old"),  # ageing equipment
        ("CUST001", "multiple systems"),  # AC + furnace
    ],
)
def test_complicating_factors_escalate_diagnostic(repo, config, customer_id, factor):
    proposal = propose_diagnostic_level(repo.customer_by_id(customer_id), config)
    assert proposal.level == "complex"
    assert factor in proposal.reason


def test_ductwork_is_deliberately_not_proposed(repo, config):
    """repair vs new-install is a scope question no customer record predicts."""
    proposals = propose_levels(repo.customer_by_id("CUST001"), [], config)
    assert "ductwork" not in proposals


def test_every_proposed_level_exists_in_the_rate_table(repo, config):
    """Guards against a proposal that would 422 the moment it was priced."""
    for customer in repo.customers:
        for item in repo.equipment:
            for job_type, proposal in propose_levels(customer, [item], config).items():
                assert repo.labor_rate(job_type, proposal.level) is not None, (
                    f"{customer.id}/{item.id}: {job_type}/{proposal.level} "
                    "is not a real rate"
                )
