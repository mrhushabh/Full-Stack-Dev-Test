from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

# Point the app at a throwaway database *before* importing anything that reads
# the setting, so tests never touch the developer's real field_estimate.db.
_TMP_DIR = tempfile.mkdtemp(prefix="field-estimate-tests-")
os.environ["FIELD_ESTIMATE_DATABASE_URL"] = f"sqlite:///{Path(_TMP_DIR) / 'test.db'}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import PricingConfig  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import tables  # noqa: E402,F401  -- registers tables on Base
from app.models.estimate import (  # noqa: E402
    EquipmentLineRequest,
    EstimateRequest,
    LaborLineRequest,
)
from app.repository import Repository  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_database():
    """A clean, freshly seeded database for every test.

    The obvious alternative -- wrapping each test in a transaction and rolling
    back -- does not work reliably here: application code commits (saving an
    estimate is a commit), and pysqlite's transaction handling makes the
    SAVEPOINT-based version of that pattern leak writes between tests. The
    dataset is 51 rows, so rebuilding it outright is both cheap and obviously
    correct.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        seed_if_empty(session)
    yield


@pytest.fixture
def db_session():
    """A session for tests that need to inspect or manipulate the data directly."""
    with Session(engine) as session:
        yield session


@pytest.fixture
def repo(db_session):
    return Repository(db_session)


@pytest.fixture
def client():
    """The app talks to the same test database via its normal session factory."""
    return TestClient(app)


@pytest.fixture
def config():
    return PricingConfig()


@pytest.fixture
def make_request():
    """Build an EstimateRequest from terse tuples, to keep tests readable."""

    def _make(
        customer_id: str | None = None,
        equipment: list[tuple[str, int]] | None = None,
        labor: list[tuple[str, str, str | None]] | None = None,
        config: PricingConfig | None = None,
    ) -> EstimateRequest:
        return EstimateRequest(
            customer_id=customer_id,
            equipment=[
                EquipmentLineRequest(equipment_id=eid, quantity=qty)
                for eid, qty in (equipment or [])
            ],
            labor=[
                LaborLineRequest(
                    job_type=job,
                    level=level,
                    hours=Decimal(hours) if hours is not None else None,
                )
                for job, level, hours in (labor or [])
            ],
            config=config,
        )

    return _make
