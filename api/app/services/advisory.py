"""Advice derived from the customer record: sizing, service history, repair-vs-replace.

Without this module `systemAge`, `squareFootage` and `lastServiceDate` are trivia
printed at the top of a form. With it they do actual work -- catching a
mis-sized unit before it is quoted, and telling a customer with a 22-year-old
system that the repair they are about to approve is 40% of the cost of replacing
it outright.

The repair-vs-replace call is the one place this tool takes a position rather than
just adding numbers. It is deliberately conservative: it fires on published
industry heuristics, always shows its arithmetic, and never hides the repair
option. A tech who disagrees ignores it.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from app.config import PricingConfig
from app.models.domain import ApiModel, Customer, Equipment, JobType
from app.models.estimate import (
    EquipmentLineRequest,
    Estimate,
    EstimateRequest,
    LaborLineRequest,
)
from app.money import ZERO, to_money
from app.repository import Repository
from app.services.inference import (
    MAJOR_COMPONENT_CATEGORIES,
    WHOLE_SYSTEM_CATEGORIES,
    is_whole_system,
    propose_install_level,
)

#: One ton of cooling is 12,000 BTU/h. The catalog names capacity both ways
#: ("3-Ton", "12K BTU"), so both spellings are parsed.
BTU_PER_TON = Decimal("12000")

_TON_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*ton", re.IGNORECASE)
_BTU_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*k\s*btu", re.IGNORECASE)

#: Maps the free-text `systemType` on a customer record to catalog categories.
#: A property can match several -- "Central AC + Gas Furnace" is two systems, and
#: which one is relevant depends on what failed.
_SYSTEM_TO_CATEGORY = [
    ("rooftop unit", "Rooftop Unit"),
    ("package unit", "Package Unit"),
    ("mini-split", "Mini-Split"),
    ("heat pump", "Heat Pump"),
    ("air handler", "Air Handler"),
    ("gas furnace", "Furnace"),
    ("furnace", "Furnace"),
    ("central ac", "Air Conditioner"),
]

#: Which whole system a failed component belongs to.
#:
#: Without this, a property listed as "Central AC + Gas Furnace" matches both
#: categories and the tool picks whichever the lookup happens to hit first -- so a
#: failed compressor could return a quote to replace the furnace. The compressor
#: is in the condenser; the relevant replacement is the air conditioner.
_COMPONENT_TO_SYSTEMS = {
    "compressor": {"Air Conditioner", "Heat Pump", "Package Unit", "Rooftop Unit"},
    "coil": {"Air Conditioner", "Heat Pump", "Air Handler"},
    "capacitor": {"Air Conditioner", "Heat Pump"},
    "ignitor": {"Furnace"},
    "gas valve": {"Furnace"},
    "control board": {"Furnace"},
    # Blower motors sit indoors, condenser fan motors outdoors, and the category is
    # just "Motor" for both -- so this stays deliberately wide.
    "motor": {"Air Handler", "Furnace", "Air Conditioner", "Heat Pump"},
}


def capacity_tons(equipment: Equipment) -> Decimal | None:
    """Cooling capacity in tons, parsed from the product name. None if not stated.

    Capacity is not a field in the dataset -- it is embedded in free text like
    "Goodman 3-Ton Central AC" or "Mitsubishi Ductless Mini-Split 12K BTU". Parsing
    it is unavoidably fragile, which is why a failure to parse returns None and the
    sizing check simply stays quiet rather than guessing.
    """
    if match := _TON_PATTERN.search(equipment.name):
        return Decimal(match.group(1))
    if match := _BTU_PATTERN.search(equipment.name):
        return (Decimal(match.group(1)) * 1000) / BTU_PER_TON
    return None


def required_tons(customer: Customer, config: PricingConfig) -> Decimal:
    """Rule-of-thumb cooling load. Not a substitute for a Manual J calculation."""
    return Decimal(customer.square_footage) / Decimal(config.sqft_per_ton)


class SizingCheck(ApiModel):
    equipment_id: str
    equipment_name: str
    capacity_tons: Decimal
    required_tons: Decimal
    verdict: str  # ok | undersized | oversized
    message: str


def check_sizing(
    customer: Customer | None, equipment: list[Equipment], config: PricingConfig
) -> list[SizingCheck]:
    """Flag whole-system equipment that is grossly mismatched to the property.

    Only whole systems are checked -- a capacitor has no tonnage, and a 3-ton coil
    in a 5-ton system is a legitimate repair scenario this tool has no business
    second-guessing.
    """
    if customer is None:
        return []

    needed = required_tons(customer, config)
    tolerance = config.sizing_tolerance
    checks: list[SizingCheck] = []

    for item in equipment:
        if not is_whole_system(item):
            continue
        capacity = capacity_tons(item)
        if capacity is None:
            continue

        low = needed * (1 - tolerance)
        high = needed * (1 + tolerance)

        if capacity < low:
            verdict = "undersized"
            message = (
                f"{item.name} is {capacity} ton against roughly "
                f"{needed:.1f} tons for {customer.square_footage:,} sq ft. "
                "An undersized system runs constantly and struggles in peak heat."
            )
        elif capacity > high:
            verdict = "oversized"
            message = (
                f"{item.name} is {capacity} ton against roughly "
                f"{needed:.1f} tons for {customer.square_footage:,} sq ft. "
                "Oversized systems short-cycle, wear faster and dehumidify poorly."
            )
        else:
            verdict = "ok"
            message = (
                f"{capacity} ton suits {customer.square_footage:,} sq ft "
                f"(rule of thumb: ~{needed:.1f} tons)."
            )

        checks.append(
            SizingCheck(
                equipment_id=item.id,
                equipment_name=item.name,
                capacity_tons=capacity,
                required_tons=needed.quantize(Decimal("0.1")),
                verdict=verdict,
                message=message,
            )
        )
    return checks


# ---------------------------------------------------------------------------
# Service history
# ---------------------------------------------------------------------------

#: Annual service is the manufacturer-recommended interval and a common condition
#: of warranty coverage. Past 18 months a system is meaningfully neglected.
_SERVICE_DUE_MONTHS = 12
_SERVICE_OVERDUE_MONTHS = 18


class ServiceStatus(ApiModel):
    status: str  # unknown | current | due | overdue
    months_since: int | None = None
    last_service_date: date | None = None
    message: str


def service_status(customer: Customer, today: date | None = None) -> ServiceStatus:
    """Interpret `lastServiceDate` into something actionable at the door.

    Useful beyond bookkeeping: a system that has not been serviced in two years is
    both a maintenance sale and context for whatever just failed.
    """
    if customer.last_service_date is None:
        return ServiceStatus(
            status="unknown",
            message="No service history on file for this property.",
        )

    today = today or date.today()
    last = customer.last_service_date
    months = (today.year - last.year) * 12 + (today.month - last.month)
    if today.day < last.day:
        months -= 1
    months = max(months, 0)

    if months >= _SERVICE_OVERDUE_MONTHS:
        status, message = (
            "overdue",
            f"Last serviced {months} months ago ({last:%b %Y}) — well past the "
            "annual interval.",
        )
    elif months >= _SERVICE_DUE_MONTHS:
        status, message = (
            "due",
            f"Last serviced {months} months ago ({last:%b %Y}) — due for annual "
            "maintenance.",
        )
    else:
        status, message = (
            "current",
            f"Serviced {months} months ago ({last:%b %Y}) — up to date.",
        )

    return ServiceStatus(
        status=status,
        months_since=months,
        last_service_date=last,
        message=message,
    )


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------

#: HVAC manufacturers commonly warrant parts for 5-10 years and compressors for
#: 10-12 on registered equipment. The dataset has no warranty records, so this can
#: only ever be a prompt to go and check -- but the alternative is quoting a
#: customer for a part the manufacturer would have supplied free, which is the
#: kind of mistake that costs a repeat customer.
_WARRANTY_LIKELY_YEARS = 10


class WarrantyFlag(ApiModel):
    applies: bool
    message: str | None = None


def check_warranty(
    customer: Customer | None, equipment: list[Equipment]
) -> WarrantyFlag:
    if customer is None or customer.system_age is None:
        return WarrantyFlag(applies=False)
    if customer.system_age > _WARRANTY_LIKELY_YEARS:
        return WarrantyFlag(applies=False)

    covered = [
        item
        for item in equipment
        if is_whole_system(item)
        or item.category.strip().lower() in MAJOR_COMPONENT_CATEGORIES
    ]
    if not covered:
        return WarrantyFlag(applies=False)

    names = ", ".join(item.name for item in covered)
    return WarrantyFlag(
        applies=True,
        message=(
            f"This system is only {customer.system_age} years old. {names} may "
            "still be covered by the manufacturer's parts warranty — check "
            "registration before quoting the part."
        ),
    )


# ---------------------------------------------------------------------------
# Repair vs replace
# ---------------------------------------------------------------------------


class ReplacementOption(ApiModel):
    equipment_id: str
    equipment_name: str
    estimate: Estimate


class RepairVsReplace(ApiModel):
    triggered: bool
    #: replace | consider | repair -- how hard the tool is leaning. `repair` means
    #: the comparison ran and repair won, which is worth saying out loud: it lets a
    #: tech tell a customer "I checked, and fixing it is the better value."
    recommendation: str = "repair"
    reasons: list[str]
    repair_total: Decimal
    replacement_total: Decimal | None = None
    cost_ratio: Decimal | None = None
    age_rule_value: Decimal | None = None
    option: ReplacementOption | None = None
    headline: str | None = None


def _customer_system_categories(customer: Customer) -> list[str]:
    """Every catalog category present in the customer's free-text `systemType`."""
    system = customer.system_type.lower()
    found: list[str] = []
    for token, category in _SYSTEM_TO_CATEGORY:
        if token in system and category not in found:
            found.append(category)
    return found


def _target_categories(customer: Customer, failed_categories: list[str]) -> list[str]:
    """Narrow the customer's systems down to the one that actually failed.

    Falls back to every system on the property when the failed part maps to none
    of them -- a thermostat is not part of any single unit, and guessing there
    would be worse than offering the obvious candidates.
    """
    present = _customer_system_categories(customer)
    if not failed_categories:
        return present

    affected: set[str] = set()
    for category in failed_categories:
        lowered = category.strip().lower()
        if lowered in WHOLE_SYSTEM_CATEGORIES:
            affected.add(category)
        affected |= _COMPONENT_TO_SYSTEMS.get(lowered, set())

    narrowed = [c for c in present if c in affected]
    return narrowed or present


def _replacement_candidate(
    customer: Customer,
    failed_categories: list[str],
    repo: Repository,
    config: PricingConfig,
) -> Equipment | None:
    """Pick a like-for-like replacement for the system that failed.

    Chooses the cheapest unit of adequate capacity, on the reasoning that a
    comparison quote should represent the realistic entry price rather than the
    most profitable upsell. A good/better/best ladder is the natural extension.
    """
    targets = {c.lower() for c in _target_categories(customer, failed_categories)}
    if not targets:
        return None

    candidates = [
        e
        for e in repo.equipment
        if e.category.lower() in targets and is_whole_system(e)
    ]
    if not candidates:
        return None

    needed = required_tons(customer, config)
    adequate = [
        e
        for e in candidates
        if (cap := capacity_tons(e)) is not None
        and cap >= needed * (1 - config.sizing_tolerance)
    ]
    pool = adequate or candidates
    return min(pool, key=lambda e: e.cost)


def evaluate_repair_vs_replace(
    customer: Customer | None,
    repair: Estimate,
    repo: Repository,
    config: PricingConfig,
) -> RepairVsReplace:
    """Compare the quoted repair against replacing the system outright."""
    repair_total = repair.totals.expected.total
    result = RepairVsReplace(triggered=False, reasons=[], repair_total=repair_total)

    if customer is None or customer.system_age is None:
        # CUST007 has no systemAge. Rather than assume, stay silent -- an advisory
        # built on an invented age is worse than no advisory.
        if customer is not None:
            result.reasons.append(
                "System age is not on file for this customer, so no "
                "repair-vs-replace comparison was run."
            )
        return result

    # Only meaningful for repairs; replacing during an install is a tautology.
    if not any(l.job_type is JobType.REPAIR for l in repair.labor_lines):
        return result
    if repair_total <= ZERO:
        return result

    failed_categories = [line.category for line in repair.equipment_lines]
    candidate = _replacement_candidate(customer, failed_categories, repo, config)
    if candidate is None:
        return result

    install = propose_install_level(customer)
    rate = repo.labor_rate(JobType.INSTALL.value, install.level)
    if rate is None:
        return result

    replacement_estimate = _price_replacement(candidate, rate, customer, repo, config)
    replacement_total = replacement_estimate.totals.expected.total
    if replacement_total <= ZERO:
        return result

    ratio = (repair_total / replacement_total).quantize(Decimal("0.01"))
    age_rule = to_money(Decimal(customer.system_age) * repair_total)

    at_end_of_life = customer.system_age >= config.end_of_life_years
    costly_relative = ratio >= config.replace_cost_ratio

    # The $5,000 rule corroborates; it does not trigger on its own. Age x cost
    # clears $5,000 on almost any major repair -- an $1,100 compressor job on an
    # eight-year-old heat pump scores $8,800 and would fire the rule, despite that
    # system having a decade of service left and repair being the right call. Used
    # alone it turns the tool into an upsell machine, which is exactly the thing
    # that would make a tech stop trusting it.
    age_rule_clears = age_rule > config.replace_rule_multiplier

    reasons: list[str] = []
    if at_end_of_life:
        reasons.append(
            f"The system is {customer.system_age} years old, at or past the "
            f"{config.end_of_life_years}-year mark where replacement enters the "
            "conversation."
        )
    if costly_relative:
        reasons.append(
            f"This repair is {ratio:.0%} of the cost of a full replacement."
        )
    if age_rule_clears and (at_end_of_life or costly_relative):
        reasons.append(
            f"Age x repair cost is ${age_rule:,.0f}, above the "
            f"${config.replace_rule_multiplier:,.0f} rule of thumb that favours "
            "replacement."
        )

    result.replacement_total = replacement_total
    result.cost_ratio = ratio
    result.age_rule_value = age_rule
    result.reasons = reasons
    result.triggered = at_end_of_life or costly_relative
    result.recommendation = (
        "replace"
        if at_end_of_life and costly_relative
        else "consider"
        if result.triggered
        else "repair"
    )

    if result.triggered:
        result.option = ReplacementOption(
            equipment_id=candidate.id,
            equipment_name=candidate.name,
            estimate=replacement_estimate,
        )
        result.headline = (
            f"{customer.system_age}-year-old system: this "
            f"${repair_total:,.0f} repair is {ratio:.0%} of the "
            f"${replacement_total:,.0f} cost of replacing it."
        )
    return result


def _price_replacement(
    candidate: Equipment,
    rate,
    customer: Customer,
    repo: Repository,
    config: PricingConfig,
) -> Estimate:
    """Build the replacement quote through the same pricing path as any estimate.

    Imported locally to keep the module import graph acyclic.
    """
    from app.services.pricing import build_estimate

    request = EstimateRequest(
        customer_id=customer.id,
        equipment=[EquipmentLineRequest(equipment_id=candidate.id, quantity=1)],
        labor=[
            LaborLineRequest(
                job_type=JobType.INSTALL,
                level=rate.level,
                hours=rate.midpoint_hours,
            )
        ],
        config=config,
    )
    return build_estimate(request, repo, config)
