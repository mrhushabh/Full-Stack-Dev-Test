"""Reference data: equipment catalog, labor rates, and the pricing knobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from sqlalchemy.orm import Session

from app.config import PricingConfig
from app.db import get_session
from app.services.settings import get_config, update_config
from app.models.domain import Equipment, LaborRate
from app.deps import get_repo
from app.repository import Repository

router = APIRouter(tags=["catalog"])


@router.get("/equipment", response_model=list[Equipment])
def list_equipment(
    q: str | None = Query(default=None, description="Free-text search"),
    category: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> list[Equipment]:
    return repo.search_equipment(query=q, category=category)


@router.get("/equipment/categories", response_model=list[str])
def list_categories(repo: Repository = Depends(get_repo)) -> list[str]:
    return repo.categories()


@router.get("/labor-rates", response_model=list[LaborRate])
def list_labor_rates(repo: Repository = Depends(get_repo)) -> list[LaborRate]:
    return repo.labor_rates


@router.get("/config", response_model=PricingConfig)
def read_config(session: Session = Depends(get_session)) -> PricingConfig:
    """The pricing assumptions currently in force.

    Exposed so the UI can render the assumptions rather than hide them -- markup,
    tax and the advisory thresholds are all business decisions the dataset does
    not answer, and a tech deserves to see which ones are in play.
    """
    return get_config(session)


@router.put("/config", response_model=PricingConfig)
def write_config(
    config: PricingConfig, session: Session = Depends(get_session)
) -> PricingConfig:
    """Persist the pricing assumptions.

    Without this the settings panel was theatre: a tech could change the markup,
    watch every total update, and lose it on refresh -- leaving the number on
    screen disagreeing with the number the server would quote.
    """
    return update_config(session, config)
