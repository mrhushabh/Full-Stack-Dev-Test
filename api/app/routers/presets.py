"""Job presets, resolved against a customer where one is known."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_repo
from app.models.estimate import EquipmentLineRequest, EstimateRequest, LaborLineRequest
from app.repository import Repository
from app.services.inference import propose_levels
from app.services.presets import Preset, list_presets, preset_by_id
from app.services.settings import get_config

router = APIRouter(tags=["presets"])


@router.get("/presets", response_model=list[Preset])
def read_presets(session: Session = Depends(get_session)) -> list[Preset]:
    return list_presets(session)


@router.get("/presets/{preset_id}/request", response_model=EstimateRequest)
def resolve_preset(
    preset_id: str,
    customer_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    repo: Repository = Depends(get_repo),
) -> EstimateRequest:
    """Expand a preset into a ready-to-price estimate request.

    Presets leave `level` unset wherever the right answer depends on the property
    rather than on the job -- an AC changeout is residential, commercial or
    mini-split labour depending entirely on who is being quoted. Those blanks are
    filled here from the same inference the UI shows its reasoning from, so the
    preset and the proposal can never drift apart.
    """
    preset = preset_by_id(session, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"No preset {preset_id}")

    customer = repo.customer_by_id(customer_id) if customer_id else None
    if customer_id and customer is None:
        raise HTTPException(status_code=404, detail=f"No customer {customer_id}")

    config = get_config(session)
    selected = [
        e
        for e in (repo.equipment_by_id(line.equipment_id) for line in preset.equipment)
        if e is not None
    ]
    proposals = propose_levels(customer, selected, config)

    labor: list[LaborLineRequest] = []
    for line in preset.labor:
        level = line.level or proposals[line.job_type.value].level
        rate = repo.labor_rate(line.job_type.value, level)
        hours = line.hours
        if hours is None and rate is not None:
            hours = rate.midpoint_hours
        labor.append(
            LaborLineRequest(job_type=line.job_type, level=level, hours=hours)
        )

    return EstimateRequest(
        customer_id=customer_id,
        equipment=[
            EquipmentLineRequest(equipment_id=e.equipment_id, quantity=e.quantity)
            for e in preset.equipment
        ],
        labor=labor,
    )
