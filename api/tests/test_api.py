"""HTTP surface: routing, serialization and error handling."""

from __future__ import annotations

import pytest


def test_health(client):
    body = client.get("/api/health").json()
    assert body == {
        "status": "ok",
        "equipment": 30,
        "customers": 10,
        "laborRates": 11,
    }


# ---------------------------------------------------------------------------
# Serialization contract
# ---------------------------------------------------------------------------


def test_responses_are_camel_case(client):
    """Python stays snake_case; the wire format matches what the React app expects."""
    item = client.get("/api/equipment").json()[0]
    assert "modelNumber" in item and "model_number" not in item


def test_money_serialized_as_string_not_float(client):
    """Decimals cross the wire as strings.

    Serializing $1,390.00 as a JSON number hands it to JavaScript as an IEEE-754
    double, reintroducing on the client exactly the precision problem Decimal
    exists to avoid on the server.
    """
    body = client.post(
        "/api/estimates",
        json={
            "customerId": "CUST006",
            "equipment": [{"equipmentId": "EQ011", "quantity": 1}],
            "labor": [{"jobType": "repair", "level": "major", "hours": "4"}],
        },
    ).json()
    total = body["estimate"]["totals"]["expected"]["total"]
    assert isinstance(total, str)
    assert total == "1390.00"


# ---------------------------------------------------------------------------
# Catalog and customers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected_id",
    [
        ("capacitor", "EQ018"),
        ("Trane", "EQ002"),
        ("ZR36K5E-PFV", "EQ011"),  # partial model number off a sticker
        ("mini-split", "EQ005"),
    ],
)
def test_equipment_search(client, query, expected_id):
    results = client.get("/api/equipment", params={"q": query}).json()
    assert expected_id in [e["id"] for e in results]


def test_equipment_filter_by_category(client):
    results = client.get("/api/equipment", params={"category": "Compressor"}).json()
    assert {e["id"] for e in results} == {"EQ011", "EQ030"}


def test_customer_search_by_address(client):
    results = client.get("/api/customers", params={"q": "Chatham"}).json()
    assert [c["id"] for c in results] == ["CUST004"]


def test_customer_search_tolerates_missing_phone(client):
    """CUST005 has no phone; a phone-inclusive search must not blow up on it."""
    assert client.get("/api/customers", params={"q": "555"}).status_code == 200


def test_unknown_customer_404s(client):
    assert client.get("/api/customers/NOPE").status_code == 404


def test_guidance_reports_missing_fields(client):
    body = client.get("/api/customers/CUST007/guidance").json()
    assert set(body["missingFields"]) == {"system age", "last service date"}
    assert body["service"]["status"] == "unknown"
    assert body["proposals"]["install"]["confidence"] == "low"


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------


def test_estimate_returns_everything_in_one_round_trip(client):
    """The UI reprices on every edit; one request has to carry the whole answer."""
    body = client.post(
        "/api/estimates",
        json={
            "customerId": "CUST006",
            "equipment": [{"equipmentId": "EQ011", "quantity": 1}],
            "labor": [
                {"jobType": "diagnostic", "level": "standard", "hours": "1"},
                {"jobType": "repair", "level": "major", "hours": "4"},
            ],
        },
    ).json()

    assert body["estimate"]["totals"]["expected"]["total"] == "1390.00"
    assert body["customer"]["name"] == "Patricia Nguyen"
    assert body["repairVsReplace"]["recommendation"] == "replace"
    assert body["proposals"]["repair"]["level"] == "major"
    assert body["warranty"]["applies"] is False


def test_per_request_config_override(client):
    """A shop's markup is a setting, not a redeploy."""
    body = client.post(
        "/api/estimates",
        json={
            "equipment": [{"equipmentId": "EQ011", "quantity": 1}],
            "config": {"equipmentMarkup": "1.5"},
        },
    ).json()
    assert body["estimate"]["equipmentLines"][0]["unitPrice"] == "1275.00"


def test_bad_equipment_id_is_422_not_500(client):
    response = client.post(
        "/api/estimates", json={"equipment": [{"equipmentId": "EQ999", "quantity": 1}]}
    )
    assert response.status_code == 422
    assert "EQ999" in response.json()["detail"]


def test_bad_level_is_422_with_valid_options(client):
    response = client.post(
        "/api/estimates",
        json={"labor": [{"jobType": "diagnostic", "level": "major", "hours": "1"}]},
    )
    assert response.status_code == 422
    assert "standard" in response.json()["detail"]


def test_estimate_for_unknown_customer_404s(client):
    response = client.post("/api/estimates", json={"customerId": "NOPE"})
    assert response.status_code == 404


def test_walk_up_estimate_needs_no_customer(client):
    """A tech at a property that is not on file still has to be able to quote."""
    body = client.post(
        "/api/estimates",
        json={"labor": [{"jobType": "repair", "level": "minor", "hours": "1"}]},
    ).json()
    assert body["estimate"]["totals"]["expected"]["total"] == "110.00"
    assert body["customer"] is None


def test_negative_quantity_rejected_by_schema(client):
    response = client.post(
        "/api/estimates", json={"equipment": [{"equipmentId": "EQ011", "quantity": -1}]}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def test_presets_listed(client):
    presets = client.get("/api/presets").json()
    assert len(presets) >= 15
    assert "capacitor" in [p["id"] for p in presets]


def test_preset_resolves_install_level_per_customer(client):
    """The same preset yields different labour depending on the property."""

    def level_for(customer_id):
        body = client.get(
            "/api/presets/ac-replacement/request",
            params={"customer_id": customer_id},
        ).json()
        return body["labor"][0]["level"]

    assert level_for("CUST001") == "residential"
    assert level_for("CUST003") == "commercial"


def test_every_preset_prices_without_error(client):
    """No preset may ship referencing a part or level that does not exist."""
    for preset in client.get("/api/presets").json():
        request = client.get(f"/api/presets/{preset['id']}/request").json()
        response = client.post("/api/estimates", json=request)
        assert response.status_code == 200, f"{preset['id']}: {response.text}"


def test_preset_end_to_end_produces_a_priced_estimate(client):
    request = client.get(
        "/api/presets/capacitor/request", params={"customer_id": "CUST001"}
    ).json()
    body = client.post("/api/estimates", json=request).json()
    # $32 capacitor + 1h minor repair at $110, diagnostic waived on approval
    assert body["estimate"]["totals"]["expected"]["total"] == "142.00"


def test_unknown_preset_404s(client):
    assert client.get("/api/presets/nope/request").status_code == 404
