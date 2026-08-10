"""Loads the provided JSON files into the database, once.

This is where the messy-data handling now lives, and it is a better home for it.
The inconsistent field names in the source files (`baseCost` vs `base_cost`,
`propertyType` vs `property_type`, `squareFootage` vs `sqft`) are exactly what you
get from "exported from different tools at different times" -- a one-off import
problem, not something the application should re-solve on every request.

The Pydantic models in `models/domain.py` still do the reconciling; they now do it
at the boundary where data enters the system permanently rather than on every
read. Nothing downstream ever sees the uneven shapes.

Seeding runs only when a table is empty, so customers added through the app are
not wiped by a restart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PricingConfig
from app.models.domain import Customer, Equipment, _RawLaborRate
from app.models.tables import (
    CustomerRow,
    EquipmentRow,
    LaborRateRow,
    PresetEquipmentRow,
    PresetLaborRow,
    PresetRow,
    PricingConfigRow,
)
from app.services.presets import SEED_PRESETS

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def data_dir() -> Path:
    return Path(os.environ.get("FIELD_ESTIMATE_DATA_DIR", _DEFAULT_DATA_DIR))


def _load_json(filename: str) -> list[dict]:
    path = data_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Expected dataset at {path}. Set FIELD_ESTIMATE_DATA_DIR to override."
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _validate_all(model, rows: list[dict], filename: str) -> list:
    """Validate every row, reporting *all* failures rather than only the first.

    A record that cannot be parsed stops the import. A half-formed object reaching
    the pricing engine would become a wrong number on a customer's estimate, which
    is a far worse failure than refusing to start.
    """
    parsed, failures = [], []
    for index, row in enumerate(rows):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            identifier = row.get("id", f"index {index}")
            failures.append(f"  {filename}[{identifier}]: {exc}")
    if failures:
        raise ValueError(
            f"{len(failures)} record(s) in {filename} failed validation:\n"
            + "\n".join(failures)
        )
    return parsed


def _is_empty(session: Session, table) -> bool:
    return session.execute(select(table).limit(1)).first() is None


def seed_if_empty(session: Session) -> dict[str, int]:
    """Import the reference data. Returns what was inserted, per table."""
    inserted = {
        "equipment": 0,
        "customers": 0,
        "labor_rates": 0,
        "presets": 0,
        "pricing_config": 0,
    }

    if _is_empty(session, EquipmentRow):
        for item in _validate_all(
            Equipment, _load_json("equipment.json"), "equipment.json"
        ):
            session.add(
                EquipmentRow(
                    id=item.id,
                    name=item.name,
                    category=item.category,
                    brand=item.brand,
                    model_number=item.model_number,
                    cost=item.cost,
                )
            )
            inserted["equipment"] += 1

    if _is_empty(session, CustomerRow):
        for item in _validate_all(
            Customer, _load_json("customers.json"), "customers.json"
        ):
            session.add(
                CustomerRow(
                    id=item.id,
                    name=item.name,
                    address=item.address,
                    phone=item.phone,
                    property_type=item.property_type.value,
                    square_footage=item.square_footage,
                    system_type=item.system_type,
                    system_age=item.system_age,
                    last_service_date=item.last_service_date,
                )
            )
            inserted["customers"] += 1

    if _is_empty(session, LaborRateRow):
        for raw in _validate_all(
            _RawLaborRate, _load_json("labor_rates.json"), "labor_rates.json"
        ):
            rate = raw.to_domain()
            session.add(
                LaborRateRow(
                    job_type=rate.job_type.value,
                    level=rate.level,
                    hourly_rate=rate.hourly_rate,
                    min_hours=rate.min_hours,
                    max_hours=rate.max_hours,
                )
            )
            inserted["labor_rates"] += 1

    # Presets and pricing settings start from the definitions in code, then live
    # in the database -- a shop editing them must not have their changes reverted
    # by the next restart.
    if _is_empty(session, PresetRow):
        for order, preset in enumerate(SEED_PRESETS):
            row = PresetRow(
                id=preset.id,
                name=preset.name,
                description=preset.description,
                group_name=preset.group,
                sort_order=order,
            )
            for line in preset.equipment:
                row.equipment.append(
                    PresetEquipmentRow(
                        equipment_id=line.equipment_id, quantity=line.quantity
                    )
                )
            for index, line in enumerate(preset.labor):
                row.labor.append(
                    PresetLaborRow(
                        job_type=line.job_type.value,
                        level=line.level,
                        hours=line.hours,
                        sort_order=index,
                    )
                )
            session.add(row)
            inserted["presets"] += 1

    if _is_empty(session, PricingConfigRow):
        defaults = PricingConfig()
        session.add(
            PricingConfigRow(
                id=1, **defaults.model_dump(exclude={"id"})
            )
        )
        inserted["pricing_config"] += 1

    session.commit()
    return inserted
