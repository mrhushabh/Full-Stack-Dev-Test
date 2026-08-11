"""Domain models -- and the normalization boundary.

The dataset was, per the README, "exported from different tools at different
times", and it shows. Three concrete inconsistencies exist in the provided files:

  * equipment.json  -- EQ012 and EQ028 carry `base_cost`; the other 28 use `baseCost`
  * customers.json  -- CUST008 carries `property_type` and `sqft`; the rest use
                       `propertyType` and `squareFootage`
  * customers.json  -- `phone`, `systemAge` and `lastServiceDate` are absent from
                       some records (mostly commercial ones)

Rather than scatter `or` fallbacks through the application, tolerance for those
variants is declared once, here, on the fields themselves. `AliasChoices` accepts
either spelling at the boundary; everything downstream of validation sees a single
guaranteed shape and never needs to know the source was uneven.

Genuinely-absent optional fields stay `None`. That is different from a default:
we do not know Brewed Awakening's system age, and inventing a zero would let a
made-up number flow into the repair-vs-replace advice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.models.base import ApiModel

__all__ = [
    "ApiModel",
    "Customer",
    "Equipment",
    "JobType",
    "LaborRate",
    "PropertyType",
]


class PropertyType(str, Enum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"


class JobType(str, Enum):
    DIAGNOSTIC = "diagnostic"
    REPAIR = "repair"
    INSTALL = "install"
    MAINTENANCE = "maintenance"
    DUCTWORK = "ductwork"


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------


class Equipment(ApiModel):
    id: str
    name: str
    category: str
    brand: str
    model_number: str = Field(
        validation_alias=AliasChoices("modelNumber", "model_number")
    )

    #: Normalized from `baseCost` (28 records) or `base_cost` (EQ012, EQ028).
    #: Named `cost` rather than `base_cost` because it is unambiguously OUR cost --
    #: what the customer pays is cost x markup, applied in the pricing service.
    cost: Decimal = Field(validation_alias=AliasChoices("baseCost", "base_cost"))


# ---------------------------------------------------------------------------
# Labor
# ---------------------------------------------------------------------------


class LaborRate(ApiModel):
    """A `jobType` + `level` pair with its rate and expected duration.

    Note that `level` is not one consistent dimension across job types -- it means
    property class for `install` (residential/commercial/mini-split), scope for
    `ductwork` (repair/new-install), and subjective severity for `diagnostic`,
    `repair` and `maintenance`. The inference service treats those three kinds of
    level as three different problems; see services/inference.py.
    """

    job_type: JobType = Field(validation_alias=AliasChoices("jobType", "job_type"))
    level: str
    hourly_rate: Decimal = Field(
        validation_alias=AliasChoices("hourlyRate", "hourly_rate")
    )
    min_hours: Decimal
    max_hours: Decimal

    @property
    def key(self) -> str:
        return f"{self.job_type.value}:{self.level}"

    @property
    def midpoint_hours(self) -> Decimal:
        """The default hours for this rate.

        Normalised because the division reintroduces a trailing zero -- the
        midpoint of 0.5-1.5h is Decimal('1.0'), which would show up in the UI's
        hours field as "1.0" rather than "1".
        """
        from app.money import plain

        return plain((self.min_hours + self.max_hours) / 2)


class _RawLaborRate(BaseModel):
    """Ingestion shape for labor_rates.json.

    Exists only because `estimatedHours` arrives as a nested `{min, max}` object,
    which is flattened into `min_hours` / `max_hours` for the domain model.
    """

    model_config = ConfigDict(populate_by_name=True)

    job_type: JobType = Field(validation_alias=AliasChoices("jobType", "job_type"))
    level: str
    hourly_rate: Decimal = Field(
        validation_alias=AliasChoices("hourlyRate", "hourly_rate")
    )
    estimated_hours: dict[str, Decimal] = Field(
        validation_alias=AliasChoices("estimatedHours", "estimated_hours")
    )

    def to_domain(self) -> LaborRate:
        return LaborRate(
            job_type=self.job_type,
            level=self.level,
            hourly_rate=self.hourly_rate,
            min_hours=self.estimated_hours["min"],
            max_hours=self.estimated_hours["max"],
        )


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


class Customer(ApiModel):
    id: str
    name: str
    address: str

    #: Absent on CUST005 (Springfield Community Church).
    phone: str | None = None

    property_type: PropertyType = Field(
        validation_alias=AliasChoices("propertyType", "property_type")
    )
    #: `squareFootage` everywhere except CUST008, which says `sqft`.
    square_footage: int = Field(
        validation_alias=AliasChoices("squareFootage", "sqft", "square_footage")
    )
    system_type: str = Field(validation_alias=AliasChoices("systemType", "system_type"))

    #: Absent on CUST007. Left as None rather than defaulted -- an invented age
    #: would silently drive the repair-vs-replace recommendation.
    system_age: int | None = Field(
        default=None, validation_alias=AliasChoices("systemAge", "system_age")
    )
    #: Absent on CUST003 and CUST007.
    last_service_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("lastServiceDate", "last_service_date"),
    )

    @field_validator("property_type", mode="before")
    @classmethod
    def _normalize_property_type(cls, v: object) -> object:
        """Casefold before enum matching -- guards against 'Residential' drift."""
        return v.strip().lower() if isinstance(v, str) else v

    @property
    def is_commercial(self) -> bool:
        return self.property_type is PropertyType.COMMERCIAL

    @property
    def has_multiple_systems(self) -> bool:
        """True when the system description implies more than one unit.

        `systemType` is free text, so this reads the two conventions actually
        present in the data: a '+' joining systems ("Central AC + Gas Furnace")
        and an '(xN)' multiplier ("Rooftop Units (x3)").
        """
        text = self.system_type.lower()
        return "+" in text or "(x" in text
