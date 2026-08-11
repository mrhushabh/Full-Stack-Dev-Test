"""Reading and writing the pricing assumptions.

These used to be Python constants, which had two problems. A shop's markup was a
code change and a redeploy. And any adjustment a tech made in the settings panel
lived only in browser state, so it silently reverted on refresh -- which is worse
than not offering the control at all, because the number on screen stops matching
what anyone agreed to.

Stored in a single row, they are a real setting: changed once, applied to every
estimate, and still visible on screen rather than buried.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.money import plain

from app.config import DEFAULT_CONFIG, PricingConfig
from app.models.tables import PricingConfigRow, utcnow

#: There is one shop, so there is one row. Per-shop settings would make this a
#: foreign key to an organisation rather than a constant.
CONFIG_ID = 1

_FIELDS = tuple(PricingConfig.model_fields)


def _tidy(value):
    """Strip the storage scale off a decimal without going exponential.

    Postgres NUMERIC(16,6) returns 1.000000 where SQLite's text column returns
    1.0, so without this the same settings render as "1.000000x markup" on one
    backend and "1.0x" on the other.

    `normalize()` alone is not enough: it turns Decimal('5000.000000') into
    Decimal('5E+3'), which Pydantic would serialize as "5E+3" -- so the result is
    round-tripped through fixed-point notation.
    """
    if isinstance(value, Decimal):
        return plain(value)
    return value


def _to_config(row: PricingConfigRow) -> PricingConfig:
    return PricingConfig(**{field: _tidy(getattr(row, field)) for field in _FIELDS})


def get_config(session: Session) -> PricingConfig:
    """The live pricing assumptions.

    Falls back to the code defaults if the row is somehow absent, so pricing keeps
    working rather than failing a request -- an estimate priced on documented
    defaults is far better than no estimate at all in front of a customer.
    """
    row = session.get(PricingConfigRow, CONFIG_ID)
    return _to_config(row) if row else DEFAULT_CONFIG


def update_config(session: Session, config: PricingConfig) -> PricingConfig:
    row = session.get(PricingConfigRow, CONFIG_ID)
    if row is None:
        row = PricingConfigRow(id=CONFIG_ID)
        session.add(row)

    for field in _FIELDS:
        setattr(row, field, getattr(config, field))
    row.updated_at = utcnow()

    session.commit()
    session.refresh(row)
    return _to_config(row)
