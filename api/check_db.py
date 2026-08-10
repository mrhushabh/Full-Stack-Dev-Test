"""Verify the configured database works end to end.

    cd api && .venv/bin/python check_db.py

Connects, creates the schema, imports the dataset if the tables are empty, then
saves and reads back a real estimate to prove decimals survive the round trip.
Prints the host but never the credentials.

Useful when pointing the app at a hosted Postgres for the first time: it fails
here, with a readable message, rather than halfway through a page load.
"""

from __future__ import annotations

import sys
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import DATABASE_URL, IS_SQLITE, Base, engine
from app.models import tables  # noqa: F401  -- registers tables on Base
from app.models.estimate import EquipmentLineRequest, EstimateRequest, LaborLineRequest
from app.repository import Repository
from app.seed import seed_if_empty
from app.services.estimate_store import delete_estimate, get_row, save_estimate, to_detail
from app.services.pricing import build_estimate
from app.config import DEFAULT_CONFIG


def _safe_url() -> str:
    """The database location, with any password removed."""
    if "@" in DATABASE_URL:
        scheme = DATABASE_URL.split("://", 1)[0]
        return f"{scheme}://***@{DATABASE_URL.split('@', 1)[1]}"
    return DATABASE_URL


def main() -> int:
    print(f"database : {_safe_url()}")
    print(f"backend  : {'SQLite' if IS_SQLITE else 'Postgres'}")

    try:
        with engine.connect() as connection:
            if IS_SQLITE:
                version = "sqlite"
            else:
                version = connection.execute(text("SELECT version()")).scalar_one()
                version = version.split(",")[0]
        print(f"connected: {version}")
    except Exception as exc:  # noqa: BLE001 -- the message is the whole point
        print(f"\nFAILED to connect: {exc}\n")
        print("Check that:")
        print("  - FIELD_ESTIMATE_DATABASE_URL is set (see .env.example)")
        print("  - the Postgres driver is installed:")
        print("      pip install -r requirements-postgres.txt")
        print("  - the database is awake -- free tiers suspend when idle")
        return 1

    Base.metadata.create_all(bind=engine)
    print("schema   : ok")

    with Session(engine) as session:
        inserted = seed_if_empty(session)
        if any(inserted.values()):
            print(f"seeded   : {inserted}")

        repo = Repository(session)
        print(
            f"contents : {len(repo.equipment)} equipment, "
            f"{len(repo.customers)} customers, {len(repo.labor_rates)} labor rates"
        )

        # A full write/read cycle. The markup is deliberately awkward: 850 x 1.115
        # is 947.75 exactly, and any float in the storage path shows up here.
        customer = repo.customers[0]
        request = EstimateRequest(
            customer_id=customer.id,
            equipment=[EquipmentLineRequest(equipment_id="EQ011", quantity=3)],
            labor=[
                LaborLineRequest(job_type="repair", level="major", hours=Decimal("4"))
            ],
            config=DEFAULT_CONFIG.model_copy(
                update={"equipment_markup": Decimal("1.115")}
            ),
        )
        estimate = build_estimate(request, repo, request.config)
        saved = save_estimate(session, customer.id, estimate, "held", "check_db probe")

        detail = to_detail(get_row(session, saved.id))
        unit_price, total = detail.equipment_lines[0].unit_price, detail.total

        delete_estimate(session, saved.id)

        ok = unit_price == "947.75" and total == "3383.25"
        print(f"round-trip: unit {unit_price}, total {total} " f"{'ok' if ok else 'MISMATCH'}")
        if not ok:
            print("  expected unit 947.75 and total 3383.25 -- decimals are being")
            print("  degraded somewhere in the storage path.")
            return 1

    print("\nAll good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
