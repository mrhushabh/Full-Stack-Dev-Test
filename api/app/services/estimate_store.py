"""Saving, listing and deleting estimates.

An estimate reaches the database only when the tech acts on it -- the customer is
going ahead, or wants to think about it. Building and showing a quote leaves no
trace, because most quotes are conversations rather than records, and a history
cluttered with every number ever shown on a doorstep is a history nobody reads.

What gets stored is a *snapshot*, not a reference. Line prices, labour rates,
hours and the pricing assumptions are all copied onto the saved rows. If the
catalog changes next month, the estimate a customer is holding in their hand still
says what it said on the day.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import ApiModel
from app.models.estimate import Estimate
from app.money import plain, to_money
from app.models.tables import (
    STATUS_APPROVED,
    STATUS_HELD,
    EstimateEquipmentLineRow,
    EstimateLaborLineRow,
    EstimateMiscLineRow,
    EstimateRow,
)

VALID_STATUSES = {STATUS_APPROVED, STATUS_HELD}


def _money(value: Decimal) -> str:
    """Money as a two-decimal string, whichever database it came out of.

    Postgres NUMERIC(16,6) returns 1390.000000 where SQLite's text column returns
    1390.00. Normalising here means the API emits the same bytes either way, so
    the frontend and the tests cannot tell which backend is behind them.
    """
    return f"{to_money(value):f}"


def _plain(value: Decimal) -> str:
    """Non-money decimals -- hours, markup, tax rate -- without trailing zeros.

    The `:f` format matters: `Decimal('20.000000').normalize()` is `2E+1`, and
    plain `str()` would put that in the response.
    """
    return str(plain(value))


class SavedEstimateSummary(ApiModel):
    """List view: enough to recognise a job without loading its line items."""

    id: str
    customer_id: str
    status: str
    created_at: datetime
    total: str
    line_count: int
    summary: str
    notes: str | None = None


class SavedEquipmentLine(ApiModel):
    equipment_id: str
    name: str
    category: str
    brand: str
    model_number: str
    quantity: int
    unit_price: str
    total: str


class SavedLaborLine(ApiModel):
    job_type: str
    level: str
    hourly_rate: str
    hours: str
    total: str


class SavedMiscLine(ApiModel):
    description: str
    amount: str


class SavedEstimateDetail(ApiModel):
    """A saved estimate reads back from the snapshot, never from the live catalog.

    Deliberately its own shape rather than the live `Estimate` model: this is a
    record of what was quoted on a day, not something the pricing engine should be
    invited to recalculate.
    """

    id: str
    customer_id: str
    status: str
    created_at: datetime
    notes: str | None

    equipment_lines: list[SavedEquipmentLine]
    labor_lines: list[SavedLaborLine]
    misc_lines: list[SavedMiscLine]

    equipment_total: str
    misc_total: str
    labor_total: str
    subtotal: str
    diagnostic_credit: str
    tax: str
    total: str
    total_low: str
    total_high: str

    # The assumptions in force at the time, so the number can be explained later.
    equipment_markup: str
    tax_rate: str


def _describe(row: EstimateRow) -> str:
    """A one-line label for the history list.

    Leads with the parts, because "Copeland Scroll Compressor" is what a tech
    remembers about a job. Falls back to the labour when there were no parts.
    """
    if row.equipment_lines:
        first = row.equipment_lines[0].name
        extra = len(row.equipment_lines) - 1
        return f"{first}{f' +{extra} more' if extra else ''}"
    if row.labor_lines:
        line = row.labor_lines[0]
        return f"{line.job_type.title()} · {line.level.title()}"
    return "Empty estimate"


def save_estimate(
    session: Session,
    customer_id: str,
    estimate: Estimate,
    status: str,
    notes: str | None = None,
) -> SavedEstimateSummary:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Unknown status {status!r}. Expected one of {sorted(VALID_STATUSES)}."
        )

    totals = estimate.totals
    row = EstimateRow(
        id=uuid.uuid4().hex[:16],
        customer_id=customer_id,
        status=status,
        notes=notes,
        equipment_total=totals.equipment,
        misc_total=totals.misc,
        labor_total=totals.expected.labor,
        subtotal=totals.expected.subtotal,
        diagnostic_credit=totals.expected.diagnostic_credit,
        tax=totals.expected.tax,
        total=totals.expected.total,
        total_low=totals.low.total,
        total_high=totals.high.total,
        equipment_markup=estimate.config.equipment_markup,
        tax_rate=estimate.config.tax_rate,
    )

    for line in estimate.equipment_lines:
        row.equipment_lines.append(
            EstimateEquipmentLineRow(
                equipment_id=line.equipment_id,
                name=line.name,
                category=line.category,
                brand=line.brand,
                model_number=line.model_number,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                unit_price=line.unit_price,
                total=line.total,
            )
        )

    for line in estimate.labor_lines:
        row.labor_lines.append(
            EstimateLaborLineRow(
                job_type=line.job_type.value,
                level=line.level,
                hourly_rate=line.hourly_rate,
                hours=line.hours,
                min_hours=line.min_hours,
                max_hours=line.max_hours,
                total=line.total,
                total_low=line.total_low,
                total_high=line.total_high,
            )
        )

    for line in estimate.misc_lines:
        row.misc_lines.append(
            EstimateMiscLineRow(
                description=line.description,
                amount=line.amount,
                taxable=line.taxable,
            )
        )

    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_summary(row)


def _to_summary(row: EstimateRow) -> SavedEstimateSummary:
    return SavedEstimateSummary(
        id=row.id,
        customer_id=row.customer_id,
        status=row.status,
        created_at=row.created_at,
        total=_money(row.total),
        line_count=len(row.equipment_lines) + len(row.labor_lines) + len(row.misc_lines),
        summary=_describe(row),
        notes=row.notes,
    )


def list_for_customer(session: Session, customer_id: str) -> list[SavedEstimateSummary]:
    rows = session.scalars(
        select(EstimateRow)
        .where(EstimateRow.customer_id == customer_id)
        .order_by(EstimateRow.created_at.desc())
    )
    return [_to_summary(row) for row in rows]


def get_row(session: Session, estimate_id: str) -> EstimateRow | None:
    return session.get(EstimateRow, estimate_id)


def to_detail(row: EstimateRow) -> SavedEstimateDetail:
    return SavedEstimateDetail(
        id=row.id,
        customer_id=row.customer_id,
        status=row.status,
        created_at=row.created_at,
        notes=row.notes,
        equipment_lines=[
            SavedEquipmentLine(
                equipment_id=line.equipment_id,
                name=line.name,
                category=line.category,
                brand=line.brand,
                model_number=line.model_number,
                quantity=line.quantity,
                unit_price=_money(line.unit_price),
                total=_money(line.total),
            )
            for line in row.equipment_lines
        ],
        labor_lines=[
            SavedLaborLine(
                job_type=line.job_type,
                level=line.level,
                hourly_rate=_money(line.hourly_rate),
                hours=_plain(line.hours),
                total=_money(line.total),
            )
            for line in row.labor_lines
        ],
        misc_lines=[
            SavedMiscLine(description=line.description, amount=_money(line.amount))
            for line in row.misc_lines
        ],
        equipment_total=_money(row.equipment_total),
        misc_total=_money(row.misc_total),
        labor_total=_money(row.labor_total),
        subtotal=_money(row.subtotal),
        diagnostic_credit=_money(row.diagnostic_credit),
        tax=_money(row.tax),
        total=_money(row.total),
        total_low=_money(row.total_low),
        total_high=_money(row.total_high),
        equipment_markup=_plain(row.equipment_markup),
        tax_rate=_plain(row.tax_rate),
    )


def set_status(session: Session, estimate_id: str, status: str) -> SavedEstimateSummary | None:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Unknown status {status!r}. Expected one of {sorted(VALID_STATUSES)}."
        )
    row = session.get(EstimateRow, estimate_id)
    if row is None:
        return None
    row.status = status
    session.commit()
    session.refresh(row)
    return _to_summary(row)


def delete_estimate(session: Session, estimate_id: str) -> bool:
    row = session.get(EstimateRow, estimate_id)
    if row is None:
        return False
    # Line items go with it via cascade; an orphaned line is meaningless.
    session.delete(row)
    session.commit()
    return True
