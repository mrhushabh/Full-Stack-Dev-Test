"""Database-backed access to reference data.

The interface is unchanged from the in-memory version this replaced -- the pricing,
inference and advisory services were written against these methods and did not
need to know the data moved. That was the point of keeping them free of storage
concerns.

Rows are converted to the Pydantic domain models on the way out, so everything
above this layer keeps working with `Decimal` money and real enums rather than
raw columns.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.domain import Customer, Equipment, LaborRate
from app.money import plain, to_money
from app.models.tables import CustomerRow, EquipmentRow, LaborRateRow


def _to_equipment(row: EquipmentRow) -> Equipment:
    # Quantized on the way out: Postgres NUMERIC(16,6) returns Decimal('3200.000000')
    # where SQLite's text column returns Decimal('3200'), and the API must not
    # describe the same catalog differently depending on what is behind it.
    return Equipment(
        id=row.id,
        name=row.name,
        category=row.category,
        brand=row.brand,
        model_number=row.model_number,
        cost=to_money(row.cost),
    )


def _to_customer(row: CustomerRow) -> Customer:
    return Customer(
        id=row.id,
        name=row.name,
        address=row.address,
        phone=row.phone,
        property_type=row.property_type,
        square_footage=row.square_footage,
        system_type=row.system_type,
        system_age=row.system_age,
        last_service_date=row.last_service_date,
    )


def _to_labor_rate(row: LaborRateRow) -> LaborRate:
    # Hours are stripped of the storage scale here rather than at the edge: they
    # flow into the pricing engine, get echoed back as the value in an editable
    # hours field, and Postgres would otherwise make that read "4.0000".
    return LaborRate(
        job_type=row.job_type,
        level=row.level,
        hourly_rate=to_money(row.hourly_rate),
        min_hours=plain(row.min_hours),
        max_hours=plain(row.max_hours),
    )


class Repository:
    """Reference-data access, memoized for the life of one request.

    Pricing an estimate touches the same rows repeatedly: the equipment is looked
    up to price it, again to run the sizing and warranty checks, and again by the
    repair-vs-replace comparison, which prices a whole second estimate through the
    same code path. That measured ten queries for one keystroke.

    The cache lives on the instance, and FastAPI builds a new instance per request
    (see `app/deps.py`), so it cannot serve data from an earlier request. That is
    the point: a request-scoped cache needs no invalidation strategy, because it
    never outlives the consistent view of the data it was built from.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self._equipment_cache: dict[str, Equipment | None] = {}
        self._customer_cache: dict[str, Customer | None] = {}
        self._rate_cache: dict[tuple[str, str], LaborRate | None] = {}
        self._all_equipment: list[Equipment] | None = None

    # -- collections --------------------------------------------------------

    @property
    def equipment(self) -> list[Equipment]:
        if self._all_equipment is None:
            rows = self.session.scalars(select(EquipmentRow).order_by(EquipmentRow.id))
            self._all_equipment = [_to_equipment(r) for r in rows]
            # Seed the per-id cache too: the replacement-candidate search reads the
            # whole catalog, and the lines being priced are already in it.
            self._equipment_cache.update({e.id: e for e in self._all_equipment})
        return self._all_equipment

    @property
    def customers(self) -> list[Customer]:
        rows = self.session.scalars(select(CustomerRow).order_by(CustomerRow.id))
        return [_to_customer(r) for r in rows]

    @property
    def labor_rates(self) -> list[LaborRate]:
        rows = self.session.scalars(select(LaborRateRow).order_by(LaborRateRow.id))
        return [_to_labor_rate(r) for r in rows]

    # -- lookups ------------------------------------------------------------

    def equipment_by_id(self, equipment_id: str) -> Equipment | None:
        if equipment_id not in self._equipment_cache:
            row = self.session.get(EquipmentRow, equipment_id)
            self._equipment_cache[equipment_id] = _to_equipment(row) if row else None
        return self._equipment_cache[equipment_id]

    def customer_by_id(self, customer_id: str) -> Customer | None:
        if customer_id not in self._customer_cache:
            row = self.session.get(CustomerRow, customer_id)
            self._customer_cache[customer_id] = _to_customer(row) if row else None
        return self._customer_cache[customer_id]

    def prefetch_equipment(self, equipment_ids: list[str]) -> None:
        """Load several parts in one query instead of one query each.

        Pricing an estimate with five parts otherwise issued five `SELECT ... WHERE
        id = ?` statements before anything else ran. Ids that do not exist are
        cached as None, so an unknown part still raises from the pricing engine
        rather than silently going missing.
        """
        missing = {i for i in equipment_ids if i not in self._equipment_cache}
        if not missing:
            return
        rows = self.session.scalars(
            select(EquipmentRow).where(EquipmentRow.id.in_(missing))
        )
        found = {row.id: _to_equipment(row) for row in rows}
        for equipment_id in missing:
            self._equipment_cache[equipment_id] = found.get(equipment_id)

    def labor_rate(self, job_type: str, level: str) -> LaborRate | None:
        # There are only eleven rate rows in total, and an estimate typically
        # touches two or three of them. Reading the table once is cheaper than
        # querying per lookup, and bounded regardless of how the estimate grows.
        if not self._rate_cache:
            for rate in self.labor_rates:
                self._rate_cache[(rate.job_type.value, rate.level)] = rate
        return self._rate_cache.get((job_type, level))

    def forget(self, customer_id: str) -> None:
        """Drop a customer from the cache after writing to it.

        Only needed where a request both writes a customer and reads it back --
        creating one, then returning the stored row.
        """
        self._customer_cache.pop(customer_id, None)

    def levels_for(self, job_type: str) -> list[str]:
        return list(
            self.session.scalars(
                select(LaborRateRow.level)
                .where(LaborRateRow.job_type == job_type)
                .order_by(LaborRateRow.id)
            )
        )

    def categories(self) -> list[str]:
        return sorted(
            self.session.scalars(select(EquipmentRow.category).distinct())
        )

    # -- search -------------------------------------------------------------

    def search_equipment(
        self, query: str | None = None, category: str | None = None
    ) -> list[Equipment]:
        """Substring match across name, brand, category and model number.

        Deliberately forgiving: a tech in a mechanical room types "cap" or a
        fragment of a model number read off a sticker, not a well-formed query.
        """
        statement = select(EquipmentRow).order_by(EquipmentRow.id)
        if category:
            statement = statement.where(
                func.lower(EquipmentRow.category) == category.strip().lower()
            )
        if query:
            needle = f"%{query.strip().lower()}%"
            statement = statement.where(
                or_(
                    func.lower(EquipmentRow.name).like(needle),
                    func.lower(EquipmentRow.brand).like(needle),
                    func.lower(EquipmentRow.category).like(needle),
                    func.lower(EquipmentRow.model_number).like(needle),
                )
            )
        return [_to_equipment(r) for r in self.session.scalars(statement)]

    def search_customers(self, query: str | None = None) -> list[Customer]:
        statement = select(CustomerRow).order_by(CustomerRow.id)
        if query:
            needle = f"%{query.strip().lower()}%"
            statement = statement.where(
                or_(
                    func.lower(CustomerRow.name).like(needle),
                    func.lower(CustomerRow.address).like(needle),
                    # phone is nullable; LIKE on NULL is NULL, which is falsey,
                    # so records without a phone simply do not match.
                    func.lower(CustomerRow.phone).like(needle),
                )
            )
        return [_to_customer(r) for r in self.session.scalars(statement)]

    # -- writes -------------------------------------------------------------

    def next_customer_id(self) -> str:
        """Continue the CUST0NN sequence the seeded data uses.

        Keeps added customers visually consistent with the imported ones. A real
        multi-user deployment would use a UUID or a database sequence instead;
        this would race under concurrent writes.
        """
        highest = 0
        for existing in self.session.scalars(select(CustomerRow.id)):
            digits = "".join(c for c in existing if c.isdigit())
            if digits:
                highest = max(highest, int(digits))
        return f"CUST{highest + 1:03d}"


def get_repository(session: Session) -> Repository:
    return Repository(session)
