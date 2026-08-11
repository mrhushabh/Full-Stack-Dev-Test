"""Request and response shapes for an estimate."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from app.config import PricingConfig
from app.models.domain import ApiModel, JobType


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class EquipmentLineRequest(ApiModel):
    equipment_id: str
    quantity: int = Field(default=1, ge=1, le=99)


class LaborLineRequest(ApiModel):
    job_type: JobType
    level: str
    #: Omitted means "use the midpoint of the rate's published range". The tech can
    #: pin a specific number once they have seen the job.
    hours: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("200"))


class MiscLineRequest(ApiModel):
    """Free-text line for costs the catalog cannot express.

    The equipment file has no entry for refrigerant, brazing rod, line-set, drain
    fittings or permit fees, all of which are real costs on real jobs. Without an
    escape hatch a tech would either omit them (under-quoting) or bend an unrelated
    catalog item to fit (corrupting the data).
    """

    description: str = Field(min_length=1, max_length=200)
    amount: Decimal
    taxable: bool = True


class EstimateRequest(ApiModel):
    customer_id: str | None = None
    equipment: list[EquipmentLineRequest] = Field(default_factory=list)
    labor: list[LaborLineRequest] = Field(default_factory=list)
    misc: list[MiscLineRequest] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)
    #: Overrides the server defaults for this estimate only.
    config: PricingConfig | None = None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class PricedEquipmentLine(ApiModel):
    equipment_id: str
    name: str
    category: str
    brand: str
    model_number: str
    quantity: int
    unit_cost: Decimal
    unit_price: Decimal
    total: Decimal


class PricedLaborLine(ApiModel):
    job_type: JobType
    level: str
    hourly_rate: Decimal
    hours: Decimal
    min_hours: Decimal
    max_hours: Decimal
    total: Decimal
    total_low: Decimal
    total_high: Decimal


class PricedMiscLine(ApiModel):
    description: str
    amount: Decimal
    taxable: bool


class ScenarioTotals(ApiModel):
    """Totals for one hours scenario.

    Labor in this dataset is a range, so a single number would be a fiction. Three
    scenarios are always returned: `low` (every labor line at its published
    minimum), `expected` (the hours the tech actually chose), and `high` (every
    line at its maximum). The UI leads with `expected` and keeps low/high as the
    honest fallback when a customer asks "could it be more?".
    """

    labor: Decimal
    subtotal: Decimal
    diagnostic_credit: Decimal
    tax: Decimal
    total: Decimal


class EstimateTotals(ApiModel):
    equipment: Decimal
    misc: Decimal
    low: ScenarioTotals
    expected: ScenarioTotals
    high: ScenarioTotals


class Estimate(ApiModel):
    customer_id: str | None
    equipment_lines: list[PricedEquipmentLine]
    labor_lines: list[PricedLaborLine]
    misc_lines: list[PricedMiscLine]
    totals: EstimateTotals
    config: PricingConfig
    #: Non-fatal observations: sizing mismatches, hours outside the published band,
    #: tax left unconfigured. Surfaced to the tech, never to the customer.
    warnings: list[str] = Field(default_factory=list)
    notes: str | None = None
