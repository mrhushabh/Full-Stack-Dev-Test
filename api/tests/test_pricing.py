"""The estimate math."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import PricingConfig
from app.services.pricing import PricingError, build_estimate


def test_worked_example_patricia_nguyen(repo, config, make_request):
    """The scenario worked by hand before any code was written.

    Patricia Nguyen (CUST006), failed compressor:

        equipment  EQ011 Copeland Scroll Compressor 3-Ton   $850.00
        labor      diagnostic/standard  1.0h x $95           $95.00
        labor      repair/major         4.0h x $135         $540.00
                                                   subtotal $1,485.00
                        diagnostic waived on approval        -$95.00
                                                      total $1,390.00
    """
    estimate = build_estimate(
        make_request(
            customer_id="CUST006",
            equipment=[("EQ011", 1)],
            labor=[("diagnostic", "standard", "1"), ("repair", "major", "4")],
        ),
        repo,
        config,
    )

    assert estimate.totals.equipment == Decimal("850.00")
    assert estimate.totals.expected.labor == Decimal("635.00")
    assert estimate.totals.expected.subtotal == Decimal("1485.00")
    assert estimate.totals.expected.diagnostic_credit == Decimal("95.00")
    assert estimate.totals.expected.total == Decimal("1390.00")


def test_low_and_high_scenarios_use_published_bounds(repo, config, make_request):
    """low/high ignore the chosen hours and use the rate table's own range.

        low   0.5h x $95  +  2h x $135  =  $317.50, less $47.50 diagnostic
        high  1.5h x $95  +  6h x $135  =  $952.50, less $142.50 diagnostic
    """
    estimate = build_estimate(
        make_request(
            customer_id="CUST006",
            equipment=[("EQ011", 1)],
            labor=[("diagnostic", "standard", "1"), ("repair", "major", "4")],
        ),
        repo,
        config,
    )

    assert estimate.totals.low.labor == Decimal("317.50")
    assert estimate.totals.low.total == Decimal("1120.00")
    assert estimate.totals.high.labor == Decimal("952.50")
    assert estimate.totals.high.total == Decimal("1660.00")
    assert (
        estimate.totals.low.total
        <= estimate.totals.expected.total
        <= estimate.totals.high.total
    )


def test_hours_default_to_midpoint_when_omitted(repo, config, make_request):
    """An omitted hours value means the midpoint of the published range."""
    estimate = build_estimate(
        make_request(labor=[("repair", "major", None)]), repo, config
    )
    assert estimate.labor_lines[0].hours == Decimal("4")  # midpoint of 2-6
    assert estimate.labor_lines[0].total == Decimal("540.00")


# ---------------------------------------------------------------------------
# Diagnostic credit
# ---------------------------------------------------------------------------


def test_diagnostic_alone_is_not_waived(repo, config, make_request):
    """A diagnosis-only visit bills the diagnostic fee.

    Waiving it here would zero the invoice for the only service rendered.
    """
    estimate = build_estimate(
        make_request(labor=[("diagnostic", "standard", "1")]), repo, config
    )
    assert estimate.totals.expected.diagnostic_credit == Decimal("0.00")
    assert estimate.totals.expected.total == Decimal("95.00")


def test_diagnostic_waived_when_work_follows(repo, config, make_request):
    estimate = build_estimate(
        make_request(
            labor=[("diagnostic", "standard", "1"), ("repair", "minor", "1")]
        ),
        repo,
        config,
    )
    assert estimate.totals.expected.diagnostic_credit == Decimal("95.00")
    assert estimate.totals.expected.total == Decimal("110.00")


def test_diagnostic_waived_when_only_parts_follow(repo, config, make_request):
    """Parts alone count as work performed."""
    estimate = build_estimate(
        make_request(
            equipment=[("EQ018", 1)], labor=[("diagnostic", "standard", "1")]
        ),
        repo,
        config,
    )
    assert estimate.totals.expected.diagnostic_credit == Decimal("95.00")


def test_credit_can_be_disabled(repo, make_request):
    estimate = build_estimate(
        make_request(
            labor=[("diagnostic", "standard", "1"), ("repair", "minor", "1")]
        ),
        repo,
        PricingConfig(credit_diagnostic_on_approval=False),
    )
    assert estimate.totals.expected.diagnostic_credit == Decimal("0.00")
    assert estimate.totals.expected.total == Decimal("205.00")


# ---------------------------------------------------------------------------
# Markup and tax
# ---------------------------------------------------------------------------


def test_markup_defaults_to_cost_price(repo, config, make_request):
    """Default 1.0x: we do not invent a margin the dataset never stated."""
    estimate = build_estimate(
        make_request(equipment=[("EQ011", 1)]), repo, config
    )
    assert estimate.equipment_lines[0].unit_cost == Decimal("850.00")
    assert estimate.equipment_lines[0].unit_price == Decimal("850.00")


def test_markup_applies_to_equipment_only(repo, make_request):
    estimate = build_estimate(
        make_request(equipment=[("EQ011", 1)], labor=[("repair", "major", "4")]),
        repo,
        PricingConfig(equipment_markup=Decimal("1.5")),
    )
    assert estimate.equipment_lines[0].unit_price == Decimal("1275.00")
    assert estimate.labor_lines[0].total == Decimal("540.00")  # unchanged
    assert estimate.totals.expected.total == Decimal("1815.00")


def test_quantity_multiplies_after_markup(repo, make_request):
    estimate = build_estimate(
        make_request(equipment=[("EQ018", 3)]),
        repo,
        PricingConfig(equipment_markup=Decimal("2.0")),
    )
    assert estimate.equipment_lines[0].unit_price == Decimal("64.00")  # 32 x 2
    assert estimate.equipment_lines[0].total == Decimal("192.00")


def test_tax_excludes_labor_by_default(repo, make_request):
    """Most jurisdictions tax parts and not service labour."""
    estimate = build_estimate(
        make_request(equipment=[("EQ011", 1)], labor=[("repair", "major", "4")]),
        repo,
        PricingConfig(tax_rate=Decimal("0.0875")),
    )
    assert estimate.totals.expected.tax == Decimal("74.38")  # 850 x 0.0875
    assert estimate.totals.expected.total == Decimal("1464.38")


def test_tax_can_include_labor(repo, make_request):
    estimate = build_estimate(
        make_request(equipment=[("EQ011", 1)], labor=[("repair", "major", "4")]),
        repo,
        PricingConfig(tax_rate=Decimal("0.0875"), tax_applies_to_labor=True),
    )
    assert estimate.totals.expected.tax == Decimal("121.63")  # 1390 x 0.0875


# ---------------------------------------------------------------------------
# Money precision
# ---------------------------------------------------------------------------


def test_no_floating_point_drift_across_many_lines(repo, make_request):
    """A rate and markup chosen to expose float error if any crept in.

    In binary floating point this arithmetic drifts by fractions of a cent and the
    total lands off by a penny or more once repeated. With Decimal it is exact.
    """
    estimate = build_estimate(
        make_request(equipment=[("EQ018", 7)]),  # $32 x 7
        repo,
        PricingConfig(equipment_markup=Decimal("1.15"), tax_rate=Decimal("0.0825")),
    )
    # 32 x 1.15 = 36.80 exactly; x7 = 257.60; tax 257.60 x 0.0825 = 21.252 -> 21.25
    assert estimate.equipment_lines[0].unit_price == Decimal("36.80")
    assert estimate.totals.equipment == Decimal("257.60")
    assert estimate.totals.expected.tax == Decimal("21.25")
    assert estimate.totals.expected.total == Decimal("278.85")


def test_half_cent_rounds_up_not_to_even(repo, make_request):
    """Bankers' rounding is Python's default and is wrong for invoicing.

    EQ023 at $45 with a 1.055x markup is 47.475, which must round to 47.48.
    """
    estimate = build_estimate(
        make_request(equipment=[("EQ023", 1)]),
        repo,
        PricingConfig(equipment_markup=Decimal("1.055")),
    )
    assert estimate.equipment_lines[0].unit_price == Decimal("47.48")


# ---------------------------------------------------------------------------
# Misc lines, warnings and failures
# ---------------------------------------------------------------------------


def test_misc_line_included_and_taxed(repo, make_request):
    """Refrigerant and consumables have no catalog entry; the escape hatch works."""
    from app.models.estimate import MiscLineRequest

    request = make_request(labor=[("repair", "major", "2")])
    request.misc = [
        MiscLineRequest(description="R-410A refrigerant, 4 lb", amount=Decimal("120"))
    ]
    estimate = build_estimate(request, repo, PricingConfig(tax_rate=Decimal("0.10")))

    assert estimate.totals.misc == Decimal("120.00")
    assert estimate.totals.expected.tax == Decimal("12.00")
    assert estimate.totals.expected.total == Decimal("402.00")  # 270 + 120 + 12


def test_hours_outside_published_range_warn_but_are_allowed(repo, config, make_request):
    """The tech on site may know better than the rate table -- but never silently."""
    estimate = build_estimate(
        make_request(labor=[("repair", "minor", "9")]), repo, config
    )
    assert estimate.labor_lines[0].total == Decimal("990.00")
    assert any("outside the published range" in w for w in estimate.warnings)


def test_markup_at_cost_is_flagged(repo, config, make_request):
    estimate = build_estimate(
        make_request(equipment=[("EQ011", 1)]), repo, config
    )
    assert any("quoted at cost" in w for w in estimate.warnings)


def test_unconfigured_tax_is_flagged(repo, config, make_request):
    estimate = build_estimate(
        make_request(labor=[("repair", "minor", "1")]), repo, config
    )
    assert any("tax is not configured" in w for w in estimate.warnings)


def test_unknown_equipment_is_rejected(repo, config, make_request):
    with pytest.raises(PricingError, match="EQ999"):
        build_estimate(make_request(equipment=[("EQ999", 1)]), repo, config)


def test_invalid_level_names_the_valid_ones(repo, config, make_request):
    """The error has to be actionable: 'minor' is not a diagnostic level."""
    with pytest.raises(PricingError) as exc:
        build_estimate(make_request(labor=[("diagnostic", "minor", "1")]), repo, config)
    assert "standard" in str(exc.value) and "complex" in str(exc.value)


def test_empty_estimate_is_zero_not_an_error(repo, config, make_request):
    """The UI asks for a price on every keystroke, including before anything exists."""
    estimate = build_estimate(make_request(), repo, config)
    assert estimate.totals.expected.total == Decimal("0.00")
