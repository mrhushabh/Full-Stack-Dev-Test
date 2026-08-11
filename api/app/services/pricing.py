"""The estimate math.

    equipment line = quantity x cost x markup
    labor line     = hourly_rate x hours
    subtotal       = equipment + labor + misc
    credit         = diagnostic labor, when the repair is approved on the spot
    tax            = tax_rate x taxable base
    total          = subtotal - credit + tax

Evaluated three times -- at minimum, chosen, and maximum labor hours -- because
the source data expresses duration as a range and collapsing that to one number
would be inventing precision the dataset does not have.

All arithmetic is `Decimal`, and rounding happens once, at the end of each line
and each total, rather than compounding at every step. See app/money.py.
"""

from __future__ import annotations

from decimal import Decimal

from app.config import PricingConfig
from app.models.domain import JobType
from app.models.estimate import (
    Estimate,
    EstimateRequest,
    EstimateTotals,
    PricedEquipmentLine,
    PricedLaborLine,
    PricedMiscLine,
    ScenarioTotals,
)
from app.money import ZERO, to_money
from app.repository import Repository


class PricingError(ValueError):
    """Raised when a request references data that does not exist."""


def _price_equipment(
    request: EstimateRequest, repo: Repository, config: PricingConfig
) -> list[PricedEquipmentLine]:
    # One query for every part on the estimate, rather than one query per part.
    repo.prefetch_equipment([item.equipment_id for item in request.equipment])

    lines: list[PricedEquipmentLine] = []
    for item in request.equipment:
        equipment = repo.equipment_by_id(item.equipment_id)
        if equipment is None:
            raise PricingError(f"Unknown equipment id: {item.equipment_id}")

        unit_price = to_money(equipment.cost * config.equipment_markup)
        lines.append(
            PricedEquipmentLine(
                equipment_id=equipment.id,
                name=equipment.name,
                category=equipment.category,
                brand=equipment.brand,
                model_number=equipment.model_number,
                quantity=item.quantity,
                unit_cost=to_money(equipment.cost),
                unit_price=unit_price,
                total=to_money(unit_price * item.quantity),
            )
        )
    return lines


def _price_labor(
    request: EstimateRequest, repo: Repository, warnings: list[str]
) -> list[PricedLaborLine]:
    lines: list[PricedLaborLine] = []
    for item in request.labor:
        rate = repo.labor_rate(item.job_type.value, item.level)
        if rate is None:
            valid = ", ".join(repo.levels_for(item.job_type.value)) or "none"
            raise PricingError(
                f"No labor rate for {item.job_type.value}/{item.level}. "
                f"Valid levels for {item.job_type.value}: {valid}"
            )

        hours = item.hours if item.hours is not None else rate.midpoint_hours

        # The published range is guidance, not a hard limit -- the tech standing in
        # the mechanical room knows things the rate table does not. Allow the
        # override, but never let it pass silently.
        if hours < rate.min_hours or hours > rate.max_hours:
            warnings.append(
                f"{item.job_type.value}/{item.level}: {hours}h is outside the "
                f"published range of {rate.min_hours}-{rate.max_hours}h."
            )

        lines.append(
            PricedLaborLine(
                job_type=rate.job_type,
                level=rate.level,
                hourly_rate=to_money(rate.hourly_rate),
                hours=hours,
                min_hours=rate.min_hours,
                max_hours=rate.max_hours,
                total=to_money(rate.hourly_rate * hours),
                total_low=to_money(rate.hourly_rate * rate.min_hours),
                total_high=to_money(rate.hourly_rate * rate.max_hours),
            )
        )
    return lines


def _diagnostic_credit_applies(
    labor_lines: list[PricedLaborLine],
    equipment_lines: list[PricedEquipmentLine],
    config: PricingConfig,
) -> bool:
    """A diagnostic fee is only waived when actual work follows it.

    If the visit is diagnosis and nothing else, the customer owes the diagnostic
    fee -- that is the entire service rendered. Waiving it there would zero out
    the invoice.
    """
    if not config.credit_diagnostic_on_approval:
        return False
    has_diagnostic = any(l.job_type is JobType.DIAGNOSTIC for l in labor_lines)
    has_other_work = (
        any(l.job_type is not JobType.DIAGNOSTIC for l in labor_lines)
        or bool(equipment_lines)
    )
    return has_diagnostic and has_other_work


def _scenario(
    labor_lines: list[PricedLaborLine],
    equipment_total: Decimal,
    misc_total: Decimal,
    taxable_misc: Decimal,
    credit_applies: bool,
    config: PricingConfig,
    which: str,
) -> ScenarioTotals:
    """Total the estimate for one hours scenario: low, expected or high."""
    attr = {"low": "total_low", "expected": "total", "high": "total_high"}[which]

    labor_total = sum((getattr(l, attr) for l in labor_lines), ZERO)

    credit = ZERO
    if credit_applies:
        credit = sum(
            (
                getattr(l, attr)
                for l in labor_lines
                if l.job_type is JobType.DIAGNOSTIC
            ),
            ZERO,
        )

    subtotal = equipment_total + labor_total + misc_total

    taxable = equipment_total + taxable_misc
    if config.tax_applies_to_labor:
        taxable += labor_total - credit
    tax = to_money(taxable * config.tax_rate)

    return ScenarioTotals(
        labor=to_money(labor_total),
        subtotal=to_money(subtotal),
        diagnostic_credit=to_money(credit),
        tax=tax,
        total=to_money(subtotal - credit + tax),
    )


def build_estimate(
    request: EstimateRequest,
    repo: Repository,
    default_config: PricingConfig,
) -> Estimate:
    """Price a set of line items into a full estimate."""
    config = request.config or default_config
    warnings: list[str] = []

    equipment_lines = _price_equipment(request, repo, config)
    labor_lines = _price_labor(request, repo, warnings)
    misc_lines = [
        PricedMiscLine(
            description=m.description, amount=to_money(m.amount), taxable=m.taxable
        )
        for m in request.misc
    ]

    equipment_total = sum((l.total for l in equipment_lines), ZERO)
    misc_total = sum((l.amount for l in misc_lines), ZERO)
    taxable_misc = sum((l.amount for l in misc_lines if l.taxable), ZERO)

    credit_applies = _diagnostic_credit_applies(labor_lines, equipment_lines, config)

    totals = EstimateTotals(
        equipment=to_money(equipment_total),
        misc=to_money(misc_total),
        **{
            which: _scenario(
                labor_lines,
                equipment_total,
                misc_total,
                taxable_misc,
                credit_applies,
                config,
                which,
            )
            for which in ("low", "expected", "high")
        },
    )

    if config.tax_rate == ZERO:
        warnings.append(
            "Sales tax is not configured; totals exclude tax. Set the tax rate in "
            "settings for this jurisdiction."
        )
    if config.equipment_markup == Decimal("1.0") and equipment_lines:
        warnings.append(
            "Equipment is quoted at cost (markup 1.0x). If 'baseCost' in the "
            "catalog is a wholesale figure, this estimate carries no parts margin."
        )

    return Estimate(
        customer_id=request.customer_id,
        equipment_lines=equipment_lines,
        labor_lines=labor_lines,
        misc_lines=misc_lines,
        totals=totals,
        config=config,
        warnings=warnings,
        notes=request.notes,
    )
