"""Estimate pricing, and saving the ones that go somewhere.

`POST /estimates` prices an estimate and returns everything derived from it in one
response -- the UI reprices on every edit, and a tech in a basement should pay one
round trip for that, not four. Nothing is stored.

`POST /estimates/save` is the separate, deliberate act of committing one to the
record, and it **re-prices from the request rather than trusting client-supplied
totals**. The client is not the authority on what a job costs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.services.settings import get_config
from app.db import get_session
from app.deps import get_repo
from app.models.base import ApiModel
from app.models.domain import Customer
from app.config import PricingConfig
from app.models.estimate import Estimate, EstimateRequest
from app.repository import Repository
from app.services.advisory import (
    RepairVsReplace,
    SizingCheck,
    WarrantyFlag,
    check_sizing,
    check_warranty,
    evaluate_repair_vs_replace,
)
from app.services.estimate_store import (
    SavedEstimateDetail,
    SavedEstimateSummary,
    delete_estimate,
    get_row,
    save_estimate,
    set_status,
    to_detail,
)
from app.services.inference import LevelProposal, propose_levels
from app.services.pricing import PricingError, build_estimate

router = APIRouter(tags=["estimates"])


class EstimateResponse(ApiModel):
    estimate: Estimate
    customer: Customer | None = None
    proposals: dict[str, LevelProposal]
    sizing: list[SizingCheck]
    repair_vs_replace: RepairVsReplace
    warranty: WarrantyFlag


class SaveEstimateRequest(ApiModel):
    """Commit an estimate to the customer's record.

    Carries the line items rather than a total: the server re-prices and stores
    what *it* calculated.
    """

    request: EstimateRequest
    #: "approved" -- customer is going ahead. "held" -- they want to think.
    status: str
    notes: str | None = Field(default=None, max_length=2000)


def _price(
    request: EstimateRequest, repo: Repository, config: PricingConfig
) -> Estimate:
    try:
        return build_estimate(request, repo, config)
    except PricingError as exc:
        # A bad equipment id or unknown job/level pair is a malformed request,
        # not a server fault.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/estimates", response_model=EstimateResponse)
def create_estimate(
    request: EstimateRequest,
    session: Session = Depends(get_session),
    repo: Repository = Depends(get_repo),
) -> EstimateResponse:
    customer = repo.customer_by_id(request.customer_id) if request.customer_id else None
    if request.customer_id and customer is None:
        raise HTTPException(
            status_code=404, detail=f"No customer {request.customer_id}"
        )

    # A per-request config overrides the stored settings for this estimate only,
    # which is how the UI previews an assumption change before committing to it.
    config = request.config or get_config(session)
    estimate = _price(request, repo, config)

    selected = [
        e
        for e in (repo.equipment_by_id(line.equipment_id) for line in request.equipment)
        if e is not None
    ]

    return EstimateResponse(
        estimate=estimate,
        customer=customer,
        proposals=propose_levels(customer, selected, config),
        sizing=check_sizing(customer, selected, config),
        repair_vs_replace=evaluate_repair_vs_replace(customer, estimate, repo, config),
        warranty=check_warranty(customer, selected),
    )


@router.post("/estimates/save", response_model=SavedEstimateSummary, status_code=201)
def save(
    payload: SaveEstimateRequest,
    session: Session = Depends(get_session),
    repo: Repository = Depends(get_repo),
) -> SavedEstimateSummary:
    customer_id = payload.request.customer_id
    if not customer_id:
        raise HTTPException(
            status_code=422,
            detail="An estimate must belong to a customer before it can be saved. "
            "Add the property as a customer first.",
        )
    if repo.customer_by_id(customer_id) is None:
        raise HTTPException(status_code=404, detail=f"No customer {customer_id}")

    config = payload.request.config or get_config(session)
    estimate = _price(payload.request, repo, config)
    try:
        return save_estimate(
            session, customer_id, estimate, payload.status, payload.notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/estimates/{estimate_id}", response_model=SavedEstimateDetail)
def get_saved(
    estimate_id: str, session: Session = Depends(get_session)
) -> SavedEstimateDetail:
    row = get_row(session, estimate_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No estimate {estimate_id}")
    return to_detail(row)


@router.patch("/estimates/{estimate_id}/status", response_model=SavedEstimateSummary)
def change_status(
    estimate_id: str,
    status: str,
    session: Session = Depends(get_session),
) -> SavedEstimateSummary:
    """Move a held estimate to approved, or put an approved one back on hold."""
    try:
        updated = set_status(session, estimate_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No estimate {estimate_id}")
    return updated


@router.delete(
    "/estimates/{estimate_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
)
def remove(estimate_id: str, session: Session = Depends(get_session)) -> None:
    if not delete_estimate(session, estimate_id):
        raise HTTPException(status_code=404, detail=f"No estimate {estimate_id}")
