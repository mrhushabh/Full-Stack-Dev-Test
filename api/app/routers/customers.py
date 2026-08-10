"""Customer lookup, creation, and the guidance derived from a customer record."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.services.settings import get_config
from app.db import get_session
from app.deps import get_repo
from app.models.base import ApiModel
from app.models.domain import Customer, PropertyType
from app.models.tables import CustomerRow
from app.repository import Repository
from app.services.advisory import ServiceStatus, required_tons, service_status
from app.services.estimate_store import SavedEstimateSummary, list_for_customer
from app.services.inference import LevelProposal, propose_levels

router = APIRouter(tags=["customers"])


class NewCustomer(ApiModel):
    """The form behind "this property isn't on file".

    Required and optional here mirror the provided dataset exactly. `phone`,
    `systemAge` and `lastServiceDate` are absent from real records in
    customers.json, and they are the three a tech standing at an unfamiliar
    property is least likely to know. Forcing a value would mean forcing a guess,
    and an invented system age silently drives the repair-vs-replace advice.
    """

    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=400)
    property_type: PropertyType
    square_footage: int = Field(gt=0, le=1_000_000)
    system_type: str = Field(min_length=1, max_length=200)

    phone: str | None = Field(default=None, max_length=40)
    system_age: int | None = Field(default=None, ge=0, le=100)
    last_service_date: date | None = None


@router.get("/customers", response_model=list[Customer])
def list_customers(
    q: str | None = Query(default=None, description="Name, address or phone"),
    repo: Repository = Depends(get_repo),
) -> list[Customer]:
    return repo.search_customers(q)


@router.post("/customers", response_model=Customer, status_code=201)
def create_customer(
    payload: NewCustomer,
    session: Session = Depends(get_session),
    repo: Repository = Depends(get_repo),
) -> Customer:
    row = CustomerRow(
        id=repo.next_customer_id(),
        name=payload.name.strip(),
        address=payload.address.strip(),
        phone=payload.phone.strip() if payload.phone else None,
        property_type=payload.property_type.value,
        square_footage=payload.square_footage,
        system_type=payload.system_type.strip(),
        system_age=payload.system_age,
        last_service_date=payload.last_service_date,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return repo.customer_by_id(row.id)


@router.get("/customers/{customer_id}", response_model=Customer)
def get_customer(
    customer_id: str, repo: Repository = Depends(get_repo)
) -> Customer:
    customer = repo.customer_by_id(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"No customer {customer_id}")
    return customer


# response_model=None is required: FastAPI otherwise infers it from the `-> None`
# return annotation, and NoneType is truthy, which trips its "204 must not have a
# body" assertion at import time.
@router.delete(
    "/customers/{customer_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
)
def delete_customer(
    customer_id: str,
    session: Session = Depends(get_session),
) -> None:
    row = session.get(CustomerRow, customer_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No customer {customer_id}")
    # Saved estimates go with the customer -- an estimate with no one to give it
    # to is not a record of anything.
    session.delete(row)
    session.commit()


@router.get(
    "/customers/{customer_id}/estimates", response_model=list[SavedEstimateSummary]
)
def customer_estimates(
    customer_id: str,
    session: Session = Depends(get_session),
    repo: Repository = Depends(get_repo),
) -> list[SavedEstimateSummary]:
    if repo.customer_by_id(customer_id) is None:
        raise HTTPException(status_code=404, detail=f"No customer {customer_id}")
    return list_for_customer(session, customer_id)


class CustomerGuidance(ApiModel):
    """Everything the UI can pre-fill the moment a customer is selected.

    This is the payload behind the central idea of the tool: by the time the tech
    has tapped a name, the labour levels are already chosen, the service history is
    already interpreted, and the sizing target is already known. The tech confirms
    rather than assembles.
    """

    customer: Customer
    proposals: dict[str, LevelProposal]
    service: ServiceStatus
    required_tons: float
    missing_fields: list[str]
    saved_estimates: list[SavedEstimateSummary]


@router.get("/customers/{customer_id}/guidance", response_model=CustomerGuidance)
def get_guidance(
    customer_id: str,
    session: Session = Depends(get_session),
    repo: Repository = Depends(get_repo),
) -> CustomerGuidance:
    customer = repo.customer_by_id(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"No customer {customer_id}")

    config = get_config(session)

    # Surfaced rather than silently defaulted: a tech should know the record is
    # thin before relying on advice derived from it.
    missing = [
        label
        for label, value in (
            ("phone", customer.phone),
            ("system age", customer.system_age),
            ("last service date", customer.last_service_date),
        )
        if value is None
    ]

    return CustomerGuidance(
        customer=customer,
        proposals=propose_levels(customer, [], config),
        service=service_status(customer),
        required_tons=float(required_tons(customer, config)),
        missing_fields=missing,
        saved_estimates=list_for_customer(session, customer_id),
    )
