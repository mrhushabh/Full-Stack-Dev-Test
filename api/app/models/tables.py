"""Database tables.

Two things here are worth explaining.

**Money is stored as TEXT.** SQLite has no decimal type, and SQLAlchemy's `Numeric`
falls back to float on it -- which would undo the exact-decimal discipline the
pricing engine is built on, at the storage layer, silently. The `Money` type below
round-trips through a string so a stored $1,390.00 is still exactly $1,390.00 when
it comes back.

**Saved estimates snapshot their prices.** Every line carries the unit price, rate
and hours that applied when the estimate was made, rather than a reference to the
current catalog. A quote is a promise made on a particular day: if a compressor's
cost changes next month, the estimate a customer is holding must not change with
it. This is also why the config knobs are frozen onto the estimate row.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Timezone-aware UTC, stored naive.

    `datetime.utcnow()` is deprecated in 3.12+, and its real problem is that it
    returns a naive value that merely claims to be UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Money(TypeDecorator):
    """Exact decimal storage, whichever database is behind it.

    Postgres has a real decimal type, so use it: `NUMERIC` sorts and sums
    correctly, which TEXT does not -- as text, "9.00" sorts above "1000.00", so a
    query like "every estimate over $2,000" would quietly return nonsense.

    SQLite has no decimal type at all, and SQLAlchemy's `Numeric` silently
    degrades to float there -- which would undo the exact-decimal discipline the
    pricing engine is built on, at the last step. So SQLite stores text and
    converts back on read.

    Either way the application only ever sees `Decimal`. Scale 6 leaves room for
    the values that are not money: markup (1.115), tax rates (0.0875) and hours
    (0.5) share these columns.
    """

    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Numeric(16, 6))
        return dialect.type_descriptor(String(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return Decimal(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(value)


# ---------------------------------------------------------------------------
# Reference data (seeded from the provided JSON files)
# ---------------------------------------------------------------------------


class CustomerRow(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(400))

    # Optional in the source data, and optional here for the same reason: a tech
    # standing at a new property may genuinely not know the system's age.
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    property_type: Mapped[str] = mapped_column(String(20))
    square_footage: Mapped[int] = mapped_column(Integer)
    system_type: Mapped[str] = mapped_column(String(200))
    system_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow
    )

    estimates: Mapped[list["EstimateRow"]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="EstimateRow.created_at.desc()",
    )


class EquipmentRow(Base):
    __tablename__ = "equipment"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), index=True)
    brand: Mapped[str] = mapped_column(String(80))
    model_number: Mapped[str] = mapped_column(String(80))
    cost: Mapped[Decimal] = mapped_column(Money)


class LaborRateRow(Base):
    __tablename__ = "labor_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(40))
    hourly_rate: Mapped[Decimal] = mapped_column(Money)
    min_hours: Mapped[Decimal] = mapped_column(Money)
    max_hours: Mapped[Decimal] = mapped_column(Money)


# ---------------------------------------------------------------------------
# Job presets
# ---------------------------------------------------------------------------


class PresetRow(Base):
    """A common job, stored rather than compiled in.

    These started as a Python list. In the database they can be added, retired or
    repriced by a shop without a redeploy -- which is the difference between the
    tool fitting one company and fitting any of them.
    """

    __tablename__ = "presets"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(400))
    group_name: Mapped[str] = mapped_column(String(40), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    equipment: Mapped[list["PresetEquipmentRow"]] = relationship(
        back_populates="preset",
        cascade="all, delete-orphan",
        order_by="PresetEquipmentRow.id",
    )
    labor: Mapped[list["PresetLaborRow"]] = relationship(
        back_populates="preset",
        cascade="all, delete-orphan",
        order_by="PresetLaborRow.sort_order",
    )


class PresetEquipmentRow(Base):
    __tablename__ = "preset_equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_id: Mapped[str] = mapped_column(
        ForeignKey("presets.id", ondelete="CASCADE"), index=True
    )
    equipment_id: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    preset: Mapped[PresetRow] = relationship(back_populates="equipment")


class PresetLaborRow(Base):
    __tablename__ = "preset_labor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_id: Mapped[str] = mapped_column(
        ForeignKey("presets.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(40))

    #: NULL means "resolve from the customer" -- an AC changeout is residential,
    #: commercial or mini-split labour depending entirely on the property.
    level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: NULL means "use the midpoint of the published range".
    hours: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    preset: Mapped[PresetRow] = relationship(back_populates="labor")


# ---------------------------------------------------------------------------
# Pricing settings
# ---------------------------------------------------------------------------


class PricingConfigRow(Base):
    """The pricing assumptions, as a single stored row.

    Previously these were Python constants, which meant a shop's markup was a code
    change and any adjustment a tech made in the UI vanished on refresh. Stored,
    they are a setting: changed once, applied everywhere, and still visible on
    screen rather than buried.
    """

    __tablename__ = "pricing_config"

    #: Singleton. One shop, one set of assumptions -- per-shop settings would make
    #: this a foreign key to an organisation.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    equipment_markup: Mapped[Decimal] = mapped_column(Money)
    tax_rate: Mapped[Decimal] = mapped_column(Money)
    tax_applies_to_labor: Mapped[bool] = mapped_column(Boolean)
    credit_diagnostic_on_approval: Mapped[bool] = mapped_column(Boolean)
    replace_rule_multiplier: Mapped[Decimal] = mapped_column(Money)
    replace_cost_ratio: Mapped[Decimal] = mapped_column(Money)
    end_of_life_years: Mapped[int] = mapped_column(Integer)
    sqft_per_ton: Mapped[int] = mapped_column(Integer)
    sizing_tolerance: Mapped[Decimal] = mapped_column(Money)
    major_repair_cost_threshold: Mapped[Decimal] = mapped_column(Money)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Saved estimates
# ---------------------------------------------------------------------------

#: An estimate only reaches the database when the tech acts on it. Building and
#: showing one leaves no trace -- most quotes are conversations, not records.
STATUS_APPROVED = "approved"  # customer is going ahead
STATUS_HELD = "held"  # customer is thinking about it


class EstimateRow(Base):
    __tablename__ = "estimates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Frozen totals. Recomputing these on read would let a catalog price change
    # rewrite history.
    equipment_total: Mapped[Decimal] = mapped_column(Money)
    misc_total: Mapped[Decimal] = mapped_column(Money)
    labor_total: Mapped[Decimal] = mapped_column(Money)
    subtotal: Mapped[Decimal] = mapped_column(Money)
    diagnostic_credit: Mapped[Decimal] = mapped_column(Money)
    tax: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)
    total_low: Mapped[Decimal] = mapped_column(Money)
    total_high: Mapped[Decimal] = mapped_column(Money)

    # The assumptions in force when this estimate was priced, so the number can
    # always be explained later.
    equipment_markup: Mapped[Decimal] = mapped_column(Money)
    tax_rate: Mapped[Decimal] = mapped_column(Money)

    customer: Mapped[CustomerRow] = relationship(back_populates="estimates")
    equipment_lines: Mapped[list["EstimateEquipmentLineRow"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan"
    )
    labor_lines: Mapped[list["EstimateLaborLineRow"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan"
    )
    misc_lines: Mapped[list["EstimateMiscLineRow"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan"
    )


class EstimateEquipmentLineRow(Base):
    __tablename__ = "estimate_equipment_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    estimate_id: Mapped[str] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), index=True
    )

    # Kept as a plain column, not a foreign key: the estimate must survive the
    # part being discontinued and removed from the catalog.
    equipment_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80))
    brand: Mapped[str] = mapped_column(String(80))
    model_number: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Money)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)

    estimate: Mapped[EstimateRow] = relationship(back_populates="equipment_lines")


class EstimateLaborLineRow(Base):
    __tablename__ = "estimate_labor_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    estimate_id: Mapped[str] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), index=True
    )

    job_type: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(40))
    hourly_rate: Mapped[Decimal] = mapped_column(Money)
    hours: Mapped[Decimal] = mapped_column(Money)
    min_hours: Mapped[Decimal] = mapped_column(Money)
    max_hours: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)
    total_low: Mapped[Decimal] = mapped_column(Money)
    total_high: Mapped[Decimal] = mapped_column(Money)

    estimate: Mapped[EstimateRow] = relationship(back_populates="labor_lines")


class EstimateMiscLineRow(Base):
    __tablename__ = "estimate_misc_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    estimate_id: Mapped[str] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), index=True
    )

    description: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Money)
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)

    estimate: Mapped[EstimateRow] = relationship(back_populates="misc_lines")
