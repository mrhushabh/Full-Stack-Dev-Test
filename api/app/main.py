"""Field Estimate Tool -- API entry point.

Run locally:
    uvicorn app.main:app --reload --port 8000

Interactive API docs are served at http://localhost:8000/docs
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.caching import CacheHeaders
from app.deps import get_repo

from app.db import Base, SessionLocal, engine
from app.models import tables  # noqa: F401  -- registers the tables on Base
from app.repository import Repository
from app.routers import catalog, customers, estimates, presets
from app.seed import seed_if_empty

DESCRIPTION = """
On-site estimate builder for HVAC field technicians.

The provided JSON files are imported into SQLite on first run. The inconsistent
field names in those files are reconciled during that import -- see `app/seed.py`
and `app/models/domain.py`.

Pricing lives server-side deliberately. Markup, tax and the repair-vs-replace
thresholds are business rules, and business rules that ship to the browser are
business rules a customer can edit with devtools open.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # `create_all` is enough for a project at this size. A deployment with real
    # data would want Alembic migrations instead -- see the README.
    Base.metadata.create_all(bind=engine)

    # Import the dataset if this is a fresh database. A malformed record stops
    # the server here, loudly, rather than surfacing as a wrong number on a
    # customer's estimate an hour later. Existing data is never overwritten, so
    # customers added through the app survive a restart.
    with SessionLocal() as session:
        inserted = seed_if_empty(session)
        repo = Repository(session)
        if any(inserted.values()):
            print(f"[field-estimate] seeded database: {inserted}")
        print(
            f"[field-estimate] ready — {len(repo.equipment)} equipment, "
            f"{len(repo.customers)} customers, {len(repo.labor_rates)} labor rates"
        )
    yield


app = FastAPI(
    title="Field Estimate Tool",
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
)

# Locally the Vite dev server runs on a different port, so the browser treats API
# calls as cross-origin and CORS is required.
#
# In the deployed setup it is not: the static site rewrites /api/* through to this
# service, so the browser only ever sees one domain and the request reaches us
# server-to-server. The extra origins below exist for the case where someone
# points a browser straight at the API host -- set FIELD_ESTIMATE_CORS_ORIGINS to
# a comma-separated list if that is ever needed.
_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
_EXTRA_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("FIELD_ESTIMATE_CORS_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ORIGINS + _EXTRA_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added after CORS so it runs inside it -- a 304 still needs the CORS headers.
app.add_middleware(CacheHeaders)

app.include_router(customers.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(estimates.router, prefix="/api")
app.include_router(presets.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health(repo: Repository = Depends(get_repo)) -> dict:
    return {
        "status": "ok",
        "equipment": len(repo.equipment),
        "customers": len(repo.customers),
        "laborRates": len(repo.labor_rates),
    }
