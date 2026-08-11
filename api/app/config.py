"""Pricing knobs.

Every value in here is an ASSUMPTION, not a fact from the dataset. The provided
files give us equipment costs and labor rates and nothing else -- no margin, no
tax, no business policy. Rather than bury guesses inside the pricing code, they
all live here, ship with conservative defaults, and are overridable per request
so the UI can expose them.

See the "Assumptions" section of the README for the reasoning behind each.
"""

from decimal import Decimal

from pydantic import Field

from app.models.base import ApiModel


class PricingConfig(ApiModel):
    """Tunable business rules applied on top of the raw dataset."""

    equipment_markup: Decimal = Field(
        default=Decimal("1.0"),
        ge=Decimal("1.0"),
        le=Decimal("5.0"),
        description=(
            "Multiplier applied to equipment cost. The dataset calls this field "
            "'baseCost', which implies a wholesale cost that a customer price is "
            "built on top of -- whereas labor_rates.json is explicitly described "
            "as 'what we charge'. The two files are therefore priced on different "
            "bases. Defaulting to 1.0 (no markup) so the tool never silently "
            "inflates a customer's bill on the strength of our guess; set this to "
            "the real number and every estimate updates."
        ),
    )

    tax_rate: Decimal = Field(
        default=Decimal("0.0"),
        ge=Decimal("0.0"),
        le=Decimal("0.25"),
        description=(
            "Sales tax as a decimal (0.0875 = 8.75%). The dataset contains no tax "
            "information and the correct rate is jurisdiction-specific, so this "
            "defaults to zero and is surfaced in the UI as 'not configured' rather "
            "than presented as a real $0.00 line."
        ),
    )

    tax_applies_to_labor: bool = Field(
        default=False,
        description=(
            "Most US jurisdictions tax parts but not service labor. Configurable "
            "because that is not universal."
        ),
    )

    credit_diagnostic_on_approval: bool = Field(
        default=True,
        description=(
            "Waive the diagnostic fee when the customer approves the repair on the "
            "spot. Near-universal HVAC practice, and it materially changes the "
            "number the customer hears, so it is modelled explicitly."
        ),
    )

    # --- Repair-vs-replace advisory -------------------------------------------------

    replace_rule_multiplier: Decimal = Field(
        default=Decimal("5000"),
        description=(
            "The '$5,000 rule': system age x repair cost. Above this, replacement is "
            "usually the better value. Widely used industry heuristic."
        ),
    )

    replace_cost_ratio: Decimal = Field(
        default=Decimal("0.4"),
        ge=Decimal("0.1"),
        le=Decimal("1.0"),
        description=(
            "Flag replacement when a repair costs at least this fraction of a full "
            "system replacement."
        ),
    )

    end_of_life_years: int = Field(
        default=15,
        description=(
            "System age at which replacement enters the conversation. Typical "
            "residential HVAC service life is 15-20 years."
        ),
    )

    # --- Sizing sanity check --------------------------------------------------------

    sqft_per_ton: int = Field(
        default=500,
        description=(
            "Rule-of-thumb cooling load: one ton per N square feet. Real Manual J "
            "load calculations account for climate, insulation, windows and "
            "orientation -- this is a sanity check to catch gross mismatches, not a "
            "substitute for that."
        ),
    )

    sizing_tolerance: Decimal = Field(
        default=Decimal("0.4"),
        description=(
            "Allowed proportional deviation from the rule-of-thumb tonnage before "
            "the tool warns about equipment sizing."
        ),
    )

    # --- Repair severity ------------------------------------------------------------

    major_repair_cost_threshold: Decimal = Field(
        default=Decimal("500"),
        description=(
            "Parts at or above this cost escalate an otherwise-minor repair to major. "
            "Used to disambiguate categories that span both (a $185 condenser fan "
            "motor is a minor job; a $650 ECM blower motor is not)."
        ),
    )


DEFAULT_CONFIG = PricingConfig()
