"""Adding customers, and saving the estimates that go somewhere."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.tables import EquipmentRow

NEW_CUSTOMER = {
    "name": "Test Property LLC",
    "address": "1 Test Way, Springfield, IL 62701",
    "propertyType": "commercial",
    "squareFootage": 4000,
    "systemType": "Rooftop Unit",
}

COMPRESSOR_JOB = {
    "equipment": [{"equipmentId": "EQ011", "quantity": 1}],
    "labor": [
        {"jobType": "diagnostic", "level": "standard", "hours": "1"},
        {"jobType": "repair", "level": "major", "hours": "4"},
    ],
}


# ---------------------------------------------------------------------------
# Adding customers
# ---------------------------------------------------------------------------


def test_create_customer_with_only_required_fields(client):
    """The three optional fields mirror the ones absent from the source data.

    A tech standing at an unfamiliar property genuinely may not know the system's
    age. Requiring it would require a guess, and a guessed age silently drives the
    repair-vs-replace advice.
    """
    created = client.post("/api/customers", json=NEW_CUSTOMER).json()

    assert created["phone"] is None
    assert created["systemAge"] is None
    assert created["lastServiceDate"] is None
    assert created["propertyType"] == "commercial"


def test_created_customer_is_searchable(client):
    created = client.post("/api/customers", json=NEW_CUSTOMER).json()
    found = client.get("/api/customers", params={"q": "Test Property"}).json()
    assert [c["id"] for c in found] == [created["id"]]


def test_customer_id_continues_the_seeded_sequence(client):
    """Seeded records run CUST001-010, so the next one is CUST011."""
    created = client.post("/api/customers", json=NEW_CUSTOMER).json()
    assert created["id"] == "CUST011"


def test_new_customer_gets_guidance_like_any_other(client):
    """A property added at the door is a first-class customer immediately."""
    created = client.post("/api/customers", json=NEW_CUSTOMER).json()
    guidance = client.get(f"/api/customers/{created['id']}/guidance").json()

    assert guidance["proposals"]["install"]["level"] == "commercial"
    assert set(guidance["missingFields"]) == {
        "phone",
        "system age",
        "last service date",
    }
    assert guidance["savedEstimates"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("squareFootage", 0),
        ("squareFootage", -100),
        ("propertyType", "industrial"),
        ("systemAge", -1),
    ],
)
def test_invalid_customer_rejected(client, field, value):
    assert client.post("/api/customers", json={**NEW_CUSTOMER, field: value}).status_code == 422


def test_missing_required_field_rejected(client):
    payload = {k: v for k, v in NEW_CUSTOMER.items() if k != "systemType"}
    assert client.post("/api/customers", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# Saving estimates
# ---------------------------------------------------------------------------


def test_building_an_estimate_saves_nothing(client):
    """Most quotes are conversations. Only the ones acted on become records."""
    client.post("/api/estimates", json={"customerId": "CUST006", **COMPRESSOR_JOB})
    assert client.get("/api/customers/CUST006/estimates").json() == []


@pytest.mark.parametrize("status", ["approved", "held"])
def test_saving_records_the_outcome(client, status):
    saved = client.post(
        "/api/estimates/save",
        json={
            "request": {"customerId": "CUST006", **COMPRESSOR_JOB},
            "status": status,
            "notes": "Customer asked about financing",
        },
    ).json()

    assert saved["status"] == status
    assert saved["total"] == "1390.00"
    assert saved["notes"] == "Customer asked about financing"
    assert saved["summary"] == "Copeland Scroll Compressor 3-Ton"

    history = client.get("/api/customers/CUST006/estimates").json()
    assert [h["id"] for h in history] == [saved["id"]]


def test_saved_estimate_appears_in_guidance(client):
    """The tech sees prior quotes the moment they pick the customer again."""
    client.post(
        "/api/estimates/save",
        json={"request": {"customerId": "CUST006", **COMPRESSOR_JOB}, "status": "held"},
    )
    guidance = client.get("/api/customers/CUST006/guidance").json()
    assert len(guidance["savedEstimates"]) == 1
    assert guidance["savedEstimates"][0]["status"] == "held"


def test_save_reprices_and_ignores_client_totals(client):
    """The client is not the authority on what a job costs.

    Only line items are accepted; the server prices them itself. A tampered total
    posted from the browser must not become the record.
    """
    saved = client.post(
        "/api/estimates/save",
        json={
            "request": {"customerId": "CUST006", **COMPRESSOR_JOB},
            "status": "approved",
            "total": "1.00",  # ignored -- not part of the schema
        },
    ).json()
    assert saved["total"] == "1390.00"


def test_save_requires_a_customer(client):
    """A walk-up estimate can be shown, but it has no record to belong to."""
    response = client.post(
        "/api/estimates/save", json={"request": COMPRESSOR_JOB, "status": "approved"}
    )
    assert response.status_code == 422
    assert "customer" in response.json()["detail"].lower()


def test_unknown_status_rejected(client):
    response = client.post(
        "/api/estimates/save",
        json={
            "request": {"customerId": "CUST006", **COMPRESSOR_JOB},
            "status": "maybe",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# The snapshot guarantee
# ---------------------------------------------------------------------------


def test_saved_prices_survive_a_catalog_change(client, db_session):
    """A quote is a promise made on a particular day.

    If the compressor's cost changes next month, the estimate the customer is
    holding must not quietly change with it. This is the single reason saved lines
    copy their prices instead of referencing the catalog.
    """
    saved = client.post(
        "/api/estimates/save",
        json={
            "request": {"customerId": "CUST006", **COMPRESSOR_JOB},
            "status": "approved",
        },
    ).json()

    # The supplier puts the compressor up by $400.
    db_session.get(EquipmentRow, "EQ011").cost = Decimal("1250")
    db_session.commit()

    detail = client.get(f"/api/estimates/{saved['id']}").json()
    assert detail["equipmentLines"][0]["unitPrice"] == "850.00"
    assert detail["total"] == "1390.00"

    # A *new* estimate does pick up the new price.
    fresh = client.post(
        "/api/estimates", json={"customerId": "CUST006", **COMPRESSOR_JOB}
    ).json()
    assert fresh["estimate"]["equipmentLines"][0]["unitPrice"] == "1250.00"


def test_saved_estimate_records_the_assumptions_used(client):
    """The number has to remain explainable later."""
    saved = client.post(
        "/api/estimates/save",
        json={
            "request": {
                "customerId": "CUST006",
                **COMPRESSOR_JOB,
                "config": {"equipmentMarkup": "1.5", "taxRate": "0.0875"},
            },
            "status": "approved",
        },
    ).json()

    detail = client.get(f"/api/estimates/{saved['id']}").json()
    assert detail["equipmentMarkup"] == "1.5"
    assert detail["taxRate"] == "0.0875"
    assert detail["equipmentLines"][0]["unitPrice"] == "1275.00"


# ---------------------------------------------------------------------------
# Changing and removing
# ---------------------------------------------------------------------------


def test_held_estimate_can_be_approved_later(client):
    """The customer rings back and says go ahead."""
    saved = client.post(
        "/api/estimates/save",
        json={"request": {"customerId": "CUST006", **COMPRESSOR_JOB}, "status": "held"},
    ).json()

    updated = client.patch(
        f"/api/estimates/{saved['id']}/status", params={"status": "approved"}
    ).json()
    assert updated["status"] == "approved"


def test_estimate_can_be_deleted(client):
    saved = client.post(
        "/api/estimates/save",
        json={"request": {"customerId": "CUST006", **COMPRESSOR_JOB}, "status": "held"},
    ).json()

    assert client.delete(f"/api/estimates/{saved['id']}").status_code == 204
    assert client.get(f"/api/estimates/{saved['id']}").status_code == 404
    assert client.get("/api/customers/CUST006/estimates").json() == []


def test_deleting_a_customer_takes_their_estimates(client, db_session):
    """An estimate with nobody to give it to is not a record of anything."""
    created = client.post("/api/customers", json=NEW_CUSTOMER).json()
    saved = client.post(
        "/api/estimates/save",
        json={
            "request": {"customerId": created["id"], **COMPRESSOR_JOB},
            "status": "approved",
        },
    ).json()

    assert client.delete(f"/api/customers/{created['id']}").status_code == 204
    assert client.get(f"/api/estimates/{saved['id']}").status_code == 404


def test_deleting_unknown_records_404(client):
    assert client.delete("/api/estimates/nope").status_code == 404
    assert client.delete("/api/customers/NOPE").status_code == 404


# ---------------------------------------------------------------------------
# Storage integrity
# ---------------------------------------------------------------------------


def test_money_round_trips_exactly_through_sqlite(client):
    """SQLite has no decimal type; `Numeric` would silently degrade to float.

    A markup chosen to land on an awkward fraction: 850 x 1.115 = 947.75 exactly.
    """
    saved = client.post(
        "/api/estimates/save",
        json={
            "request": {
                "customerId": "CUST006",
                "equipment": [{"equipmentId": "EQ011", "quantity": 3}],
                "config": {"equipmentMarkup": "1.115"},
            },
            "status": "approved",
        },
    ).json()

    detail = client.get(f"/api/estimates/{saved['id']}").json()
    assert detail["equipmentLines"][0]["unitPrice"] == "947.75"
    assert detail["total"] == "2843.25"
