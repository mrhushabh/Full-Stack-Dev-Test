"""Proposes labor selections, with the reasoning attached.

`level` in labor_rates.json looks like one field but is three different kinds of
decision depending on the job type, and each needs different handling:

  derived   install    residential / commercial / mini-split
                       -> falls out of the customer record; the tech confirms
                          rather than chooses

  declared  ductwork   repair / new-install
                       -> unambiguous scope question only the tech can answer;
                          no inference is possible or useful

  judged    diagnostic standard / complex
            repair     minor / major
            maintenance standard / comprehensive
                       -> subjective severity. minor-vs-major repair is
                          $110/h x 0.5-2h against $135/h x 2-6h: a fifteen-fold
                          spread hiding behind one dropdown. This is where the
                          tool earns its keep.

The rule throughout is PROPOSE, DO NOT DECIDE. Every proposal carries the reason
it was made, a confidence level, and the alternatives it rejected. The tech is the
expert on site and holds the liability; the tool's job is to make the obvious
choice one tap away and the reasoning visible enough to argue with.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from app.config import PricingConfig
from app.models.domain import ApiModel, Customer, Equipment, JobType


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Alternative(ApiModel):
    level: str
    reason: str


class LevelProposal(ApiModel):
    job_type: JobType
    level: str
    reason: str
    confidence: Confidence
    alternatives: list[Alternative] = []


# ---------------------------------------------------------------------------
# Equipment category taxonomy
# ---------------------------------------------------------------------------

#: Categories that constitute a whole system rather than a component. Swapping one
#: of these is an installation, not a repair, and it uses the install rate table.
WHOLE_SYSTEM_CATEGORIES = {
    "air conditioner",
    "heat pump",
    "furnace",
    "air handler",
    "mini-split",
    "rooftop unit",
    "package unit",
}

#: Components whose replacement is inherently a major job -- refrigerant circuit
#: work, recovery and recharge, several hours regardless of the part price.
MAJOR_COMPONENT_CATEGORIES = {"compressor", "coil"}

#: Components that are typically a quick swap: accessible, no refrigerant work.
MINOR_COMPONENT_CATEGORIES = {
    "capacitor",
    "ignitor",
    "control board",
    "thermostat",
    "gas valve",
    "humidifier",
    "air cleaner",
    "air purifier",
}


def is_whole_system(equipment: Equipment) -> bool:
    return equipment.category.strip().lower() in WHOLE_SYSTEM_CATEGORIES


# ---------------------------------------------------------------------------
# Judged: repair severity, anchored to the part
# ---------------------------------------------------------------------------


def propose_repair_level(
    equipment: list[Equipment], config: PricingConfig
) -> LevelProposal:
    """Infer minor vs major repair from the parts involved.

    Asking a tech "is this minor or major?" invites an arbitrary answer to a
    question worth hundreds of dollars. Asking "what are you replacing?" gets a
    factual answer, and the part is a good proxy for the work: a capacitor is
    twenty minutes with a screwdriver, a compressor is a day with a recovery
    machine. Severity is therefore derived from what the tech already told us.
    """
    if not equipment:
        return LevelProposal(
            job_type=JobType.REPAIR,
            level="minor",
            reason="No parts selected yet — defaulting to minor. Add the part "
            "being replaced and this updates automatically.",
            confidence=Confidence.LOW,
            alternatives=[
                Alternative(
                    level="major",
                    reason="Refrigerant circuit work, or anything over "
                    f"${config.major_repair_cost_threshold:,.0f} in parts.",
                )
            ],
        )

    # Worst part governs: a job containing one major component is a major job even
    # if three trivial parts are along for the ride.
    for item in equipment:
        category = item.category.strip().lower()
        if category in MAJOR_COMPONENT_CATEGORIES:
            return LevelProposal(
                job_type=JobType.REPAIR,
                level="major",
                reason=f"{item.name} is a {item.category.lower()} — refrigerant "
                "recovery, brazing and recharge put this well past a minor repair.",
                confidence=Confidence.HIGH,
                alternatives=[
                    Alternative(
                        level="minor",
                        reason="Only if the part is being repaired rather than "
                        "replaced.",
                    )
                ],
            )

    expensive = [i for i in equipment if i.cost >= config.major_repair_cost_threshold]
    if expensive:
        item = max(expensive, key=lambda i: i.cost)
        return LevelProposal(
            job_type=JobType.REPAIR,
            level="major",
            reason=f"{item.name} is a ${item.cost:,.0f} part, at or above the "
            f"${config.major_repair_cost_threshold:,.0f} threshold where a swap "
            "stops being a quick job.",
            confidence=Confidence.MEDIUM,
            alternatives=[
                Alternative(
                    level="minor",
                    reason="If the part is readily accessible and the swap is "
                    "straightforward.",
                )
            ],
        )

    known = [
        i
        for i in equipment
        if i.category.strip().lower() in MINOR_COMPONENT_CATEGORIES
    ]
    if known:
        return LevelProposal(
            job_type=JobType.REPAIR,
            level="minor",
            reason=f"{known[0].name} is a straightforward component swap — no "
            "refrigerant work, no system teardown.",
            confidence=Confidence.HIGH,
            alternatives=[
                Alternative(
                    level="major",
                    reason="If access is poor or the failure damaged other "
                    "components.",
                )
            ],
        )

    return LevelProposal(
        job_type=JobType.REPAIR,
        level="minor",
        reason="Parts selected are under the major-repair cost threshold and "
        "involve no refrigerant work.",
        confidence=Confidence.MEDIUM,
        alternatives=[
            Alternative(level="major", reason="If the job proves more involved.")
        ],
    )


# ---------------------------------------------------------------------------
# Derived: install class from the property
# ---------------------------------------------------------------------------


def propose_install_level(customer: Customer | None) -> LevelProposal:
    if customer is None:
        return LevelProposal(
            job_type=JobType.INSTALL,
            level="residential",
            reason="No customer selected — assuming residential.",
            confidence=Confidence.LOW,
            alternatives=[
                Alternative(level="commercial", reason="Commercial property."),
                Alternative(level="mini-split", reason="Ductless mini-split system."),
            ],
        )

    is_mini_split = "mini-split" in customer.system_type.lower()

    # Genuine ambiguity in the data: Brewed Awakening Coffee (CUST007) is a
    # commercial property running mini-splits, and both levels have a fair claim.
    # $185/h over 6-16h against $140/h over 3-6h is roughly a threefold swing, so
    # this is surfaced rather than silently resolved.
    if is_mini_split and customer.is_commercial:
        return LevelProposal(
            job_type=JobType.INSTALL,
            level="mini-split",
            reason=f"{customer.name} is a commercial property running a "
            "mini-split system. Both rates could apply; the mini-split rate is "
            "proposed as the more specific match to the equipment.",
            confidence=Confidence.LOW,
            alternatives=[
                Alternative(
                    level="commercial",
                    reason="Use the commercial rate if this is a large multi-head "
                    "job or the site needs commercial scheduling and access.",
                )
            ],
        )

    if is_mini_split:
        return LevelProposal(
            job_type=JobType.INSTALL,
            level="mini-split",
            reason=f"System of record is \"{customer.system_type}\" — the "
            "mini-split rate applies.",
            confidence=Confidence.HIGH,
        )

    if customer.is_commercial:
        return LevelProposal(
            job_type=JobType.INSTALL,
            level="commercial",
            reason=f"{customer.name} is a commercial property "
            f"({customer.square_footage:,} sq ft).",
            confidence=Confidence.HIGH,
        )

    return LevelProposal(
        job_type=JobType.INSTALL,
        level="residential",
        reason=f"Residential property, {customer.square_footage:,} sq ft.",
        confidence=Confidence.HIGH,
    )


# ---------------------------------------------------------------------------
# Judged: diagnostic and maintenance complexity
# ---------------------------------------------------------------------------


def _complexity_factors(customer: Customer, config: PricingConfig) -> list[str]:
    """Reasons this property is harder to work on than a baseline single system."""
    factors: list[str] = []
    if customer.is_commercial:
        factors.append("commercial property")
    if customer.has_multiple_systems:
        factors.append(f"multiple systems ({customer.system_type})")
    if customer.system_age is not None and customer.system_age >= config.end_of_life_years:
        factors.append(f"{customer.system_age}-year-old equipment")
    return factors


def propose_diagnostic_level(
    customer: Customer | None, config: PricingConfig
) -> LevelProposal:
    if customer is None:
        return LevelProposal(
            job_type=JobType.DIAGNOSTIC,
            level="standard",
            reason="No customer selected — assuming a single conventional system.",
            confidence=Confidence.LOW,
            alternatives=[
                Alternative(level="complex", reason="Multi-zone or commercial."),
            ],
        )

    factors = _complexity_factors(customer, config)
    if factors:
        return LevelProposal(
            job_type=JobType.DIAGNOSTIC,
            level="complex",
            reason="Complex diagnostic indicated: " + ", ".join(factors) + ".",
            confidence=Confidence.HIGH if len(factors) > 1 else Confidence.MEDIUM,
            alternatives=[
                Alternative(
                    level="standard",
                    reason="If the fault is already isolated to one accessible unit.",
                )
            ],
        )

    return LevelProposal(
        job_type=JobType.DIAGNOSTIC,
        level="standard",
        reason=f"Single conventional system ({customer.system_type}), "
        f"{customer.system_age} years old.",
        confidence=Confidence.HIGH,
        alternatives=[
            Alternative(
                level="complex",
                reason="If the fault is intermittent or spans multiple components.",
            )
        ],
    )


def propose_maintenance_level(
    customer: Customer | None, config: PricingConfig
) -> LevelProposal:
    if customer is None or not _complexity_factors(customer, config):
        return LevelProposal(
            job_type=JobType.MAINTENANCE,
            level="standard",
            reason="Single system, routine service interval.",
            confidence=Confidence.MEDIUM,
            alternatives=[
                Alternative(
                    level="comprehensive",
                    reason="First service in over a year, or a system due for a "
                    "full inspection.",
                )
            ],
        )

    factors = _complexity_factors(customer, config)
    return LevelProposal(
        job_type=JobType.MAINTENANCE,
        level="comprehensive",
        reason="Comprehensive service indicated: " + ", ".join(factors) + ".",
        confidence=Confidence.HIGH if len(factors) > 1 else Confidence.MEDIUM,
        alternatives=[
            Alternative(
                level="standard",
                reason="If this is a routine seasonal check on one unit.",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def propose_levels(
    customer: Customer | None,
    equipment: list[Equipment],
    config: PricingConfig,
) -> dict[str, LevelProposal]:
    """Every level proposal the UI might need, keyed by job type.

    `ductwork` is absent by design: repair versus new-install is a scope question
    about work that has not happened yet, and nothing in the customer record
    predicts it. Guessing would be noise dressed up as help.
    """
    return {
        JobType.DIAGNOSTIC.value: propose_diagnostic_level(customer, config),
        JobType.REPAIR.value: propose_repair_level(equipment, config),
        JobType.INSTALL.value: propose_install_level(customer),
        JobType.MAINTENANCE.value: propose_maintenance_level(customer, config),
    }
