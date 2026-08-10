"""Presets and pricing assumptions live in the database, not in the code.

They started as Python constants. That meant a shop's markup was a redeploy, and
any change a tech made in the settings panel lived only in browser state -- so it
reverted on refresh, leaving the number on screen disagreeing with the number the
server would actually quote.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.tables import PresetRow, PricingConfigRow
from app.services.presets import SEED_PRESETS


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def test_presets_are_seeded_into_the_database(db_session):
    rows = db_session.query(PresetRow).all()
    assert len(rows) == len(SEED_PRESETS)


def test_presets_are_served_from_the_database_not_the_code(client, db_session):
    """Editing the row changes the API -- proving the code list is only seed data."""
    row = db_session.get(PresetRow, "capacitor")
    row.name = "Capacitor swap (renamed in DB)"
    db_session.commit()

    served = {p["id"]: p["name"] for p in client.get("/api/presets").json()}
    assert served["capacitor"] == "Capacitor swap (renamed in DB)"


def test_a_preset_added_to_the_database_is_usable_immediately(client, db_session):
    """A shop can add its own common job without a redeploy."""
    from app.models.tables import PresetEquipmentRow, PresetLaborRow

    row = PresetRow(
        id="uv-lamp",
        name="UV lamp replacement",
        description="Annual UV bulb change.",
        group_name="maintenance",
        sort_order=99,
    )
    row.equipment.append(PresetEquipmentRow(equipment_id="EQ028", quantity=1))
    row.labor.append(
        PresetLaborRow(job_type="maintenance", level="standard", hours=Decimal("1"))
    )
    db_session.add(row)
    db_session.commit()

    assert "uv-lamp" in [p["id"] for p in client.get("/api/presets").json()]

    request = client.get("/api/presets/uv-lamp/request").json()
    priced = client.post("/api/estimates", json=request).json()
    # $680 air purifier + 1h standard maintenance at $85
    assert priced["estimate"]["totals"]["expected"]["total"] == "765.00"


def test_deleting_a_preset_cascades_its_lines(client, db_session):
    db_session.delete(db_session.get(PresetRow, "capacitor"))
    db_session.commit()

    assert "capacitor" not in [p["id"] for p in client.get("/api/presets").json()]
    assert client.get("/api/presets/capacitor/request").status_code == 404


# ---------------------------------------------------------------------------
# Pricing settings
# ---------------------------------------------------------------------------


def test_config_is_seeded_as_a_single_row(db_session):
    rows = db_session.query(PricingConfigRow).all()
    assert len(rows) == 1
    assert rows[0].equipment_markup == Decimal("1.0")


def test_config_survives_a_round_trip(client):
    client.put(
        "/api/config",
        json={
            **client.get("/api/config").json(),
            "equipmentMarkup": "1.45",
            "taxRate": "0.0825",
        },
    )
    saved = client.get("/api/config").json()
    assert saved["equipmentMarkup"] == "1.45"
    assert saved["taxRate"] == "0.0825"


def test_saved_config_prices_every_later_estimate(client):
    """The whole point: change it once, and it applies without being resent."""
    client.put(
        "/api/config",
        json={**client.get("/api/config").json(), "equipmentMarkup": "1.5"},
    )

    priced = client.post(
        "/api/estimates",
        json={"equipment": [{"equipmentId": "EQ011", "quantity": 1}]},
    ).json()
    assert priced["estimate"]["equipmentLines"][0]["unitPrice"] == "1275.00"


def test_per_request_config_still_overrides_the_stored_one(client):
    """So the UI can preview an assumption change before committing to it."""
    client.put(
        "/api/config",
        json={**client.get("/api/config").json(), "equipmentMarkup": "1.5"},
    )

    priced = client.post(
        "/api/estimates",
        json={
            "equipment": [{"equipmentId": "EQ011", "quantity": 1}],
            "config": {"equipmentMarkup": "2.0"},
        },
    ).json()
    assert priced["estimate"]["equipmentLines"][0]["unitPrice"] == "1700.00"

    # ...and previewing must not have written anything.
    assert client.get("/api/config").json()["equipmentMarkup"] == "1.5"


def test_advisory_thresholds_are_configurable_and_stored(client):
    """A shop that replaces later than the default should be able to say so."""
    job = {
        "customerId": "CUST006",
        "equipment": [{"equipmentId": "EQ011", "quantity": 1}],
        "labor": [{"jobType": "repair", "level": "major", "hours": "4"}],
    }
    assert client.post("/api/estimates", json=job).json()["repairVsReplace"]["triggered"]

    client.put(
        "/api/config",
        json={
            **client.get("/api/config").json(),
            "endOfLifeYears": 30,
            "replaceCostRatio": "0.9",
        },
    )
    assert not client.post("/api/estimates", json=job).json()["repairVsReplace"][
        "triggered"
    ]


def test_seeding_never_overwrites_saved_settings(db_session):
    """Restarting the server must not revert a shop's configuration."""
    from app.seed import seed_if_empty

    row = db_session.get(PricingConfigRow, 1)
    row.equipment_markup = Decimal("1.75")
    db_session.commit()

    seed_if_empty(db_session)  # as the next boot would

    db_session.expire_all()
    assert db_session.get(PricingConfigRow, 1).equipment_markup == Decimal("1.75")


def test_config_renders_identically_on_either_backend(client):
    """Postgres NUMERIC(16,6) returns 1.000000 where SQLite returns 1.0.

    Unfixed, the settings panel reads "1.000000x markup" against Postgres and
    "1.0x" against SQLite -- the same configuration, shown two different ways.
    """
    from app.services.settings import _tidy

    assert _tidy(Decimal("1.000000")) == Decimal("1")
    assert str(_tidy(Decimal("1.450000"))) == "1.45"
    assert str(_tidy(Decimal("0.087500"))) == "0.0875"
    # normalize() alone makes this 5E+3, which would land in the JSON as "5E+3"
    assert str(_tidy(Decimal("5000.000000"))) == "5000"

    served = client.get("/api/config").json()
    assert served["equipmentMarkup"] == "1"
    assert served["replaceRuleMultiplier"] == "5000"
    assert "E" not in served["replaceRuleMultiplier"]


def test_out_of_range_config_is_rejected(client):
    """Guard rails stay on the stored values too -- a 12x markup is a typo."""
    response = client.put(
        "/api/config",
        json={**client.get("/api/config").json(), "equipmentMarkup": "12.0"},
    )
    assert response.status_code == 422
